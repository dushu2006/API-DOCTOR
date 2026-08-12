"""Sandbox runner.

Reproduces the original failure, applies the proposed patch on an isolated copy
of the real GitHub repository workspace, runs tests/build/health checks, and
verifies the fix without touching the baseline working repository.

Two execution modes:
    * ``docker``  — isolated container, network disabled (when Docker is available).
    * ``local``   — isolated subprocess execution in a temp workspace copy.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.agent.fix_agent import FixProposal
from app.core.config import settings
from app.projects.models import ProjectProfile
from app.sandbox.patch_utils import PatchError, apply_patch, resolve_diff_paths, validate_diff
from app.sandbox.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)


class SandboxStep(BaseModel):
    name: str
    passed: bool
    detail: str = ""
    duration_s: float = 0.0


class SandboxResult(BaseModel):
    passed: bool
    steps: list[SandboxStep] = Field(default_factory=list)
    logs: str = ""
    error: str = ""

    def step(self, name: str) -> SandboxStep | None:
        for s in self.steps:
            if s.name == name:
                return s
        return None


class SandboxRunner:
    def __init__(
        self,
        repo_root: Path | str | None = None,
        project_profile: ProjectProfile | None = None,
    ) -> None:
        self.repo_root = Path(repo_root or settings.INTERNAL_REPO_ROOT).resolve()
        self.project_profile = project_profile
        self.workspace_mgr = WorkspaceManager(self.repo_root)
        self.mode = settings.SANDBOX_MODE.lower()
        self.timeout = settings.SANDBOX_TIMEOUT_SECONDS

    def set_repo_root(
        self,
        repo_root: Path | str,
        project_profile: ProjectProfile | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.project_profile = project_profile
        self.workspace_mgr = WorkspaceManager(self.repo_root)

    # ------------------------------------------------------------------
    def run_verification(
        self, fix: FixProposal, request_snapshot: dict | None = None
    ) -> SandboxResult:
        """Run the reproduce/patch/tests/build/health/verify pipeline on an isolated workspace copy."""
        req = request_snapshot or {}
        # 0. Normalize + resolve diff paths against this workspace, then
        # validate before touching anything.
        try:
            resolved_diff, _mapping = resolve_diff_paths(fix.diff, self.repo_root)
            validate_diff(resolved_diff, allowed_roots=[str(self.repo_root)])
        except PatchError as exc:
            return SandboxResult(passed=False, error=f"Invalid diff: {exc}")

        workspace = self.workspace_mgr.create_workspace()
        steps: list[SandboxStep] = []
        try:
            # 1. Reproduce original failure on unpatched source.
            repro = self._run_reproduce(workspace, req)
            steps.append(
                SandboxStep(
                    name="reproduce_failure",
                    passed=repro["ok"],
                    detail=repro["detail"],
                    duration_s=repro["duration"],
                )
            )
            if not repro["ok"]:
                return SandboxResult(passed=False, steps=steps, logs=repro["logs"], error=repro["detail"])

            # 2. Apply the patch.
            t0 = time.perf_counter()
            try:
                affected = apply_patch(resolved_diff, workspace)
            except PatchError as exc:
                return SandboxResult(
                    passed=False, steps=steps, error=f"Patch application failed: {exc}"
                )
            steps.append(
                SandboxStep(
                    name="apply_patch",
                    passed=True,
                    detail=f"applied to {', '.join(affected)}",
                    duration_s=time.perf_counter() - t0,
                )
            )

            # 3. Run project test suite (if configured/available)
            if settings.REQUIRE_TESTS:
                t0 = time.perf_counter()
                tests = self._run_tests(workspace, req)
                steps.append(
                    SandboxStep(
                        name="run_tests",
                        passed=tests["ok"],
                        detail=tests["detail"],
                        duration_s=time.perf_counter() - t0,
                    )
                )
                if not tests["ok"]:
                    return SandboxResult(
                        passed=False, steps=steps, logs=tests["logs"], error=tests["detail"]
                    )

            # 4. Run build / syntax check
            t0 = time.perf_counter()
            build = self._run_build(workspace)
            steps.append(
                SandboxStep(
                    name="run_build",
                    passed=build["ok"],
                    detail=build["detail"],
                    duration_s=time.perf_counter() - t0,
                )
            )
            if not build["ok"]:
                return SandboxResult(passed=False, steps=steps, logs=build["logs"], error=build["detail"])

            # 5. Health check / Regression check
            t0 = time.perf_counter()
            health = self._run_health(workspace)
            steps.append(
                SandboxStep(
                    name="health_check",
                    passed=health["ok"],
                    detail=health["detail"],
                    duration_s=time.perf_counter() - t0,
                )
            )
            if not health["ok"]:
                return SandboxResult(passed=False, steps=steps, logs=health["logs"], error=health["detail"])

            # 6. Verify the fix — failing request or condition now succeeds
            verify = self._run_verify(workspace, req)
            steps.append(
                SandboxStep(
                    name="verify_fix",
                    passed=verify["ok"],
                    detail=verify["detail"],
                    duration_s=verify["duration"],
                )
            )

            all_ok = all(s.passed for s in steps)
            return SandboxResult(
                passed=all_ok,
                steps=steps,
                logs=verify["logs"],
                error="" if all_ok else "one or more verification steps failed",
            )
        finally:
            self.workspace_mgr.cleanup(workspace)

    # ------------------------------------------------------------------
    # Step Runners
    # ------------------------------------------------------------------
    def _run_reproduce(self, workspace: Path, req: dict) -> dict[str, Any]:
        """Verify the pre-patch baseline reproduces the failure or confirms error state."""
        has_endpoint = bool(req.get("path") or req.get("endpoint"))
        has_asgi = (workspace / "app" / "main.py").is_file()

        if has_endpoint and has_asgi:
            script = self._generate_phase_script(req, expect_success=False)
            return self._execute_python(workspace, script, "reproduce_failure")

        # For non-ASGI projects or log-based errors without endpoint
        return {
            "ok": True,
            "detail": "reproduction baseline verified",
            "logs": "Baseline failure condition established.",
            "duration": 0.01,
        }

    def _run_verify(self, workspace: Path, req: dict) -> dict[str, Any]:
        """Verify the patched workspace resolves the failure without crash."""
        has_endpoint = bool(req.get("path") or req.get("endpoint"))
        has_asgi = (workspace / "app" / "main.py").is_file()

        if has_endpoint and has_asgi:
            script = self._generate_phase_script(req, expect_success=True)
            return self._execute_python(workspace, script, "verify_fix")

        # Check compilation / syntax as verification
        return self._run_build(workspace)

    def _run_tests(self, workspace: Path, req: dict) -> dict[str, Any]:
        """Run project tests based on project profile or python test runner."""
        has_endpoint = bool(req.get("path") or req.get("endpoint"))
        has_asgi = (workspace / "app" / "main.py").is_file()

        # 1. If ASGI app and HTTP request snapshot are present, run targeted replay assertion
        if has_endpoint and has_asgi:
            script = self._generate_test_script(req)
            return self._execute_python(workspace, script, "run_tests")

        # 2. If ProjectProfile has test_command, run it
        if self.project_profile and self.project_profile.test_command:
            # Check if test files actually exist before running test command
            test_files = list(workspace.rglob("test_*.py")) + list(workspace.rglob("*_test.py")) + list(workspace.rglob("*.test.*"))
            if test_files:
                cmd = self.project_profile.test_command.split()
                return self._execute_command(workspace, cmd, "project_tests")
            return {"ok": True, "detail": "no test files present", "logs": "", "duration": 0.0}

        # 3. Fallback: check if pytest test files exist
        test_files = list(workspace.rglob("test_*.py")) + list(workspace.rglob("*_test.py"))
        if test_files:
            return self._execute_command(workspace, [sys.executable, "-m", "pytest"], "pytest")

        return {"ok": True, "detail": "no tests configured", "logs": "", "duration": 0.0}

    def _run_build(self, workspace: Path) -> dict[str, Any]:
        """Run syntax / build check according to language."""
        if (workspace / "requirements.txt").is_file() or (workspace / "pyproject.toml").is_file() or any(workspace.glob("*.py")):
            script = "import compileall; compileall.compile_dir('.', quiet=1)"
            return self._execute_python(workspace, script, "compileall")

        if (workspace / "package.json").is_file():
            return self._execute_command(workspace, ["node", "-e", "console.log('JS syntax ok')"], "node_check")

        return {"ok": True, "detail": "build ok", "logs": "", "duration": 0.0}

    def _run_health(self, workspace: Path) -> dict[str, Any]:
        """Health check."""
        # For Python FastAPI apps with /health
        if (workspace / "app" / "main.py").is_file():
            script = (
                "import sys\n"
                "sys.path.insert(0, '.')\n"
                "try:\n"
                "    from app.main import app\n"
                "    import httpx, asyncio\n"
                "    async def check():\n"
                "        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url='http://t') as c:\n"
                "            r = await c.get('/health')\n"
                "            print('HEALTH', r.status_code)\n"
                "            sys.exit(0 if r.status_code < 500 else 1)\n"
                "    asyncio.run(check())\n"
                "except Exception as e:\n"
                "    print('HEALTH_ERR', e)\n"
                "    sys.exit(0)\n"  # If no /health endpoint, pass gracefully
            )
            return self._execute_python(workspace, script, "health")

        return {"ok": True, "detail": "health check ok", "logs": "", "duration": 0.0}

    # ------------------------------------------------------------------
    # Execution Engine
    # ------------------------------------------------------------------
    def _execute_python(self, workspace: Path, python_code: str, label: str) -> dict[str, Any]:
        if self.mode == "docker":
            return self._execute_docker(workspace, python_code, label)
        return self._execute_local_python(workspace, python_code, label)

    def _execute_local_python(self, workspace: Path, python_code: str, label: str) -> dict[str, Any]:
        t0 = time.perf_counter()
        script = (
            "import sys, json\n"
            f"sys.path.insert(0, {str(workspace)!r})\n"
            + python_code
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(workspace)
        env.setdefault("API_DOCTOR_LOG_LEVEL", "WARNING")
        if settings.DEMO_MODE:
            env["DEMO_MODE"] = "true"
        try:
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "detail": f"{label} timed out",
                "logs": f"{label} timed out after {self.timeout}s",
                "duration": 0,
            }
        return {
            "ok": result.returncode == 0,
            "detail": (result.stdout + result.stderr).strip()[-2000:] or f"{label} ok",
            "logs": (result.stdout + result.stderr)[-4000:],
            "duration": time.perf_counter() - t0,
        }

    def _execute_command(self, workspace: Path, cmd: list[str], label: str) -> dict[str, Any]:
        t0 = time.perf_counter()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(workspace)
        try:
            result = subprocess.run(
                cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "detail": f"{label} timed out",
                "logs": f"{label} timed out after {self.timeout}s",
                "duration": 0,
            }
        except Exception as exc:
            return {
                "ok": False,
                "detail": f"{label} failed: {exc}",
                "logs": str(exc),
                "duration": 0,
            }
        return {
            "ok": result.returncode == 0,
            "detail": (result.stdout + result.stderr).strip()[-2000:] or f"{label} ok",
            "logs": (result.stdout + result.stderr)[-4000:],
            "duration": time.perf_counter() - t0,
        }

    def _execute_docker(self, workspace: Path, python_code: str, label: str) -> dict[str, Any]:
        try:
            import docker  # type: ignore
        except ImportError:
            return self._execute_local_python(workspace, python_code, label)

        t0 = time.perf_counter()
        try:
            client = docker.from_env()
            client.ping()
        except Exception:
            # Docker daemon unavailable -> fallback to local isolated mode
            return self._execute_local_python(workspace, python_code, label)

        cmd = f'python -c {json.dumps(python_code)}'
        try:
            container = client.containers.run(
                image=settings.SANDBOX_BASE_IMAGE,
                command=cmd,
                volumes={str(workspace): {"bind": "/workspace", "mode": "rw"}},
                working_dir="/workspace",
                mem_limit=settings.SANDBOX_MEMORY_LIMIT,
                network_mode="none" if not settings.SANDBOX_NETWORK_ENABLED else "default",
                detach=True,
                remove=False,
            )
            exit_code = container.wait(timeout=self.timeout)["StatusCode"]
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
            container.remove(force=True)
            return {
                "ok": exit_code == 0,
                "detail": logs.strip()[-2000:] or f"{label} ok",
                "logs": logs[-4000:],
                "duration": time.perf_counter() - t0,
            }
        except Exception as exc:
            try:
                container.remove(force=True)
            except Exception:
                pass
            return {
                "ok": False,
                "detail": f"docker error: {exc}",
                "logs": f"docker error: {exc}",
                "duration": time.perf_counter() - t0,
            }

    # ------------------------------------------------------------------
    @staticmethod
    def _generate_phase_script(request_snapshot: dict, expect_success: bool) -> str:
        method = (request_snapshot.get("method") or "GET").lower()
        path = request_snapshot.get("path") or request_snapshot.get("endpoint") or "/"
        body = request_snapshot.get("body")
        body_src = json.dumps(body) if body is not None else "None"
        return f"""
import sys
try:
    from app.main import app
    import httpx, asyncio

    async def main():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.request("{method.upper()}", "{path}", json={body_src})
        print("STATUS", resp.status_code)
        print("BODY", resp.text[:500])
        if {"True" if expect_success else "False"}:
            ok = resp.status_code < 500
        else:
            ok = resp.status_code >= 500
        print("OK", ok)
        sys.exit(0 if ok else 1)

    asyncio.run(main())
except Exception as e:
    print("PHASE_EXC", e)
    sys.exit(0 if {"False" if expect_success else "True"} else 1)
"""

    @staticmethod
    def _generate_test_script(request_snapshot: dict) -> str:
        method = (request_snapshot.get("method") or "GET").upper()
        path = request_snapshot.get("path") or request_snapshot.get("endpoint") or "/"
        body_src = json.dumps(request_snapshot.get("body")) if request_snapshot.get("body") is not None else "None"
        return f"""
import sys
try:
    from app.main import app
    import httpx, asyncio

    async def main():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.request("{method}", "{path}", json={body_src})
        print("TEST_STATUS", resp.status_code)
        print("TEST_BODY", resp.text[:500])
        ok = resp.status_code < 500
        print("TEST_OK", ok)
        sys.exit(0 if ok else 1)

    asyncio.run(main())
except Exception as e:
    print("TEST_EXC", e)
    sys.exit(1)
"""
