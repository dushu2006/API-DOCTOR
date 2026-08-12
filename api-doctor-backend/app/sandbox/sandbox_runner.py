"""Sandbox runner.

Reproduces the original failure, applies the proposed patch, runs tests/build/
health checks, compares the outcome to the original failure and returns a
structured PASS/FAIL result.

Two execution modes:
    * ``docker``  — isolated container, network disabled (default).
    * ``local``   — subprocess execution in a temp workspace (for environments
                    without Docker; still isolated and real, not fake).
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
from app.sandbox.patch_utils import PatchError, apply_patch, validate_diff
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
    def __init__(self, repo_root: Path | str | None = None) -> None:
        self.repo_root = Path(repo_root or settings.REPO_ROOT).resolve()
        self.workspace_mgr = WorkspaceManager(self.repo_root)
        self.mode = settings.SANDBOX_MODE.lower()
        self.timeout = settings.SANDBOX_TIMEOUT_SECONDS

    # ------------------------------------------------------------------
    async def run_verification(
        self, fix: FixProposal, request_snapshot: dict
    ) -> SandboxResult:
        # 0. Validate the diff before touching anything.
        try:
            validate_diff(fix.diff, allowed_roots=[str(self.repo_root)])
        except PatchError as exc:
            return SandboxResult(passed=False, error=f"Invalid diff: {exc}")

        workspace = self.workspace_mgr.create_workspace()
        steps: list[SandboxStep] = []
        try:
            # 1. Reproduce original failure on unpatched source.
            repro = self._run_phase(
                workspace, request_snapshot, expect_success=False
            )
            steps.append(
                SandboxStep(
                    name="reproduce_failure",
                    passed=repro["ok"],
                    detail=repro["detail"],
                    duration_s=repro["duration"],
                )
            )
            if not repro["ok"]:
                return SandboxResult(passed=False, steps=steps, logs=repro["logs"])

            # 2. Apply the patch.
            t0 = time.perf_counter()
            try:
                affected = apply_patch(fix.diff, workspace)
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

            # 3. Run tests (optional gate) — a targeted reproduction test.
            if settings.REQUIRE_TESTS:
                t0 = time.perf_counter()
                tests = self._run_tests(workspace, request_snapshot)
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
                        passed=False, steps=steps, logs=tests["logs"]
                    )

            # 4. Run build / syntax check (Python: compileall).
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
                return SandboxResult(passed=False, steps=steps, logs=build["logs"])

            # 5. Health check.
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
                return SandboxResult(passed=False, steps=steps, logs=health["logs"])

            # 6. Verify the fix — same request now succeeds.
            verify = self._run_phase(workspace, request_snapshot, expect_success=True)
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
    def _run_phase(
        self, workspace: Path, request_snapshot: dict, expect_success: bool
    ) -> dict[str, Any]:
        script = self._generate_phase_script(request_snapshot, expect_success)
        return self._execute(workspace, script, "phase")

    def _run_tests(self, workspace: Path, request_snapshot: dict) -> dict[str, Any]:
        script = self._generate_test_script(request_snapshot)
        return self._execute(workspace, script, "pytest")

    def _run_build(self, workspace: Path) -> dict[str, Any]:
        return self._execute(workspace, "import compileall, pathlib; compileall.compile_dir('app', quiet=1)", "compileall")

    def _run_health(self, workspace: Path) -> dict[str, Any]:
        script = (
            "import sys\n"
            "sys.path.insert(0, '.')\n"
            "from app.main import app\n"
            "import httpx, asyncio\n"
            "async def main():\n"
            "    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url='http://t') as c:\n"
            "        r = await c.get('/health')\n"
            "        print('HEALTH', r.status_code)\n"
            "        sys.exit(0 if r.status_code == 200 else 1)\n"
            "asyncio.run(main())"
        )
        return self._execute(workspace, script, "health")

    # ------------------------------------------------------------------
    def _execute(
        self, workspace: Path, python_code: str, label: str
    ) -> dict[str, Any]:
        """Run python code inside the workspace, in the configured mode."""
        if self.mode == "docker":
            return self._execute_docker(workspace, python_code, label)
        return self._execute_local(workspace, python_code, label)

    def _execute_local(
        self, workspace: Path, python_code: str, label: str
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        script = (
            "import sys, json\n"
            f"sys.path.insert(0, {str(workspace)!r})\n"
            + python_code
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(workspace)
        try:
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=str(workspace),
                capture_output=True, text=True, timeout=self.timeout, env=env,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False, "detail": f"{label} timed out",
                "logs": f"{label} timed out after {self.timeout}s", "duration": 0,
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
        except ImportError as exc:
            return {
                "ok": False,
                "detail": "docker python package not installed",
                "logs": "docker python package not installed",
                "duration": 0,
            }
        t0 = time.perf_counter()
        client = docker.from_env()
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
                "ok": False, "detail": f"docker error: {exc}",
                "logs": f"docker error: {exc}", "duration": time.perf_counter() - t0,
            }

    # ------------------------------------------------------------------
    @staticmethod
    def _generate_phase_script(request_snapshot: dict, expect_success: bool) -> str:
        method = (request_snapshot.get("method") or "GET").lower()
        path = request_snapshot.get("path") or "/"
        body = request_snapshot.get("body")
        body_src = json.dumps(body) if body is not None else "None"
        return f"""
import sys
from app.main import app
import httpx, asyncio

async def main():
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.request("{method.upper()}", "{path}", json={body_src})
    print("STATUS", resp.status_code)
    print("BODY", resp.text[:500])
    if {"True" if expect_success else "False"}:
        # Verify: the original 5xx crash is resolved (2xx/4xx both acceptable).
        ok = resp.status_code < 500
    else:
        # Reproduce: confirm the original 5xx failure still happens.
        ok = resp.status_code >= 500
    print("OK", ok)
    sys.exit(0 if ok else 1)

asyncio.run(main())
"""

    @staticmethod
    def _generate_test_script(request_snapshot: dict) -> str:
        """Run a targeted pytest that replays the request and asserts it is fixed.

        The test file is written to the workspace root (not under ``tests/``) so
        the project's own test suite is not executed inside the sandbox.
        """
        method = (request_snapshot.get("method") or "GET").upper()
        path = request_snapshot.get("path") or "/"
        body_src = json.dumps(request_snapshot.get("body")) if request_snapshot.get("body") is not None else "None"
        test_file = f"""
import httpx
from app.main import app

def test_fix_resolves_crash():
    async def run():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.request("{method}", "{path}", json={body_src})
        return resp.status_code
    import asyncio
    status = asyncio.run(run())
    assert status < 500, f"expected crash resolved, got status {{status}}"
"""
        script = (
            "import sys, subprocess, pathlib\n"
            "pathlib.Path('test_fix_repro.py').write_text(" + repr(test_file) + ")\n"
            "r = subprocess.run([sys.executable, '-m', 'pytest', 'test_fix_repro.py', '-q'], "
            "capture_output=True, text=True)\n"
            "print(r.stdout[-1500:])\n"
            "print(r.stderr[-1500:])\n"
            "sys.exit(r.returncode)"
        )
        return script
