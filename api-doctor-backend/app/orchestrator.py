"""Central workflow engine.

Drives: detect/ingest -> create run -> collect context -> retrieve relevant code
-> root cause analysis -> fix generation -> sandbox (reproduce/patch/tests/
verify) -> GitHub PR.

Guarantees:
    * operates on isolated copies of real GitHub repositories,
    * never modifies main directly,
    * never auto-merges,
    * bounded repair attempts,
    * secrets are never sent to the LLM or exposed to the frontend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agent.fix_agent import FixAgent, FixProposal
from app.agent.root_cause_agent import RootCauseAgent, RootCauseAnalysis
from app.context_builder.context_builder import ContextBuilder
from app.core.config import settings
from app.core.logging_config import log_operation
from app.detector.failure_detector import FailureDetector
from app.events.hub import emit
from app.runs.models import Run, RunStatus
from app.runs.store import run_store
from app.projects.store import project_store
from app.sandbox.patch_utils import (
    PatchError,
    apply_patch,
    apply_patch_idempotent,
    resolve_diff_paths,
    validate_diff,
)
from app.sandbox.sandbox_runner import SandboxResult, SandboxRunner
from app.security.sanitizer import redact_text, sanitize

logger = logging.getLogger(__name__)

# How many times the coder model may be re-invoked with corrective feedback
# after a FixProposal references file paths that do not exist in the run's
# known context (see _generate_validated_fix). Bounded so a stubborn model can
# never loop forever.
_FIX_PATH_RETRIES = 2

# Statuses a run can be in AFTER the fix-approval gate has been crossed
# (verification running/done, downstream failure, PR opened). Once a
# "fix_approval: done" activity was recorded and the run sits in one of
# these, a repeated "Keep Changes" request is a duplicate (double click,
# browser retry on a dropped response) and must be treated as an idempotent
# success — never as a conflict.
POST_FIX_GATE_STATUSES = frozenset({
    RunStatus.SANDBOX_TESTING,
    RunStatus.SANDBOX_RUNNING,
    RunStatus.TESTING,
    RunStatus.VERIFYING,
    RunStatus.FIX_VERIFIED,
    RunStatus.PR_READY,
    RunStatus.PR_CREATED,
    RunStatus.VERIFICATION_FAILED,
    RunStatus.REPAIR_LIMIT_REACHED,
    RunStatus.FAILED,
})

def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Orchestrator:
    def __init__(self) -> None:
        self.detector = FailureDetector()
        self.context_builder = ContextBuilder()
        self.root_cause_agent = RootCauseAgent()
        self.fix_agent = FixAgent()
        self.sandbox_runner = SandboxRunner()
        self._pipeline_tasks: dict[str, asyncio.Task[Run | None]] = {}
        # run_id -> Keep-Changes application state (rollback snapshot and affected files)
        self._workspace_apply: dict[str, dict[str, Any]] = {}
        # Applying a patch is a read/check/write transaction. Serialize it so a
        # duplicate click (or two runs targeting the same workspace) can
        # never race between the context check and the metadata update.
        self._workspace_apply_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------
    async def reset_current(self, owner_id: str) -> bool:
        """Cancel and forget the owner's current run without archiving it."""
        current = run_store.get_current(owner_id)
        if not current:
            return False

        task = self._pipeline_tasks.get(current.id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # If a patch was staged but never verified, restore the source before
        # forgetting its only in-memory state. Completed changes remain in the
        # workspace because the user explicitly kept them.
        completed = current.status in {
            RunStatus.FIX_VERIFIED,
            RunStatus.PR_READY,
            RunStatus.PR_CREATED,
        }
        if self._load_apply_state(current.id):
            if completed:
                self._discard_apply_snapshot(current.id)
            else:
                await self._restore_workspace_files(current.id)

        self._pipeline_tasks.pop(current.id, None)
        await emit(current.id, "reset", "done", "Diagnosis state cleared")
        run_store.clear(owner_id)
        return True

    async def detect_and_create(
        self,
        endpoint: str,
        method: str = "GET",
        payload: dict | None = None,
        headers: dict[str, str] | None = None,
        project_id: str = "default",
        owner_id: str = "local",
    ) -> Run:
        await self.reset_current(owner_id)
        detection = await self.detector.trigger_diagnosis(endpoint, method, payload, headers)
        run = Run(
            owner_id=owner_id,
            project_id=project_id,
            status=RunStatus.DETECTED,
            detection=detection,
            request_snapshot=detection.get("request_snapshot", {}),
            stack_trace=detection.get("stack_trace", ""),
        )
        run_store.create(run)
        run.add_activity("error_detected", "done", f"HTTP {detection.get('status_code')} on {method} {endpoint}")
        run_store.update(run)
        log_operation(logger, run.id, "detect", "ok", error=str(detection.get("error_message") or "")[:200])
        await emit(run.id, "error_detected", "done", f"{method} {endpoint}")
        return run

    async def ingest_run(
        self,
        *,
        source: str = "manual",
        raw_logs: str = "",
        stack_trace: str = "",
        message: str = "",
        endpoint: str = "",
        method: str = "GET",
        status_code: int = 500,
        service_id: str = "",
        project_id: str = "default",
        owner_id: str = "local",
        request_snapshot: dict | None = None,
    ) -> Run:
        """Start a fresh diagnosis from external logs."""
        await self.reset_current(owner_id)
        safe_raw_logs = redact_text(raw_logs or "")
        safe_trace = redact_text(stack_trace or safe_raw_logs or message)
        safe_message = redact_text(
            message or (safe_trace.splitlines()[-1] if safe_trace else "Run detected from logs")
        )
        safe_request_snapshot = sanitize(
            request_snapshot or {"method": method, "path": endpoint}
        )

        detection = {
            "error": True,
            "status_code": status_code,
            "error_message": safe_message,
            "stack_trace": safe_trace,
            "endpoint": endpoint,
            "method": method,
            "service": service_id or "production",
            "source": source,
            "raw_logs": safe_raw_logs,
            "request_snapshot": safe_request_snapshot,
            "response_snapshot": {},
        }

        run = Run(
            owner_id=owner_id,
            project_id=project_id,
            status=RunStatus.RECEIVED,
            detection=detection,
            request_snapshot=safe_request_snapshot,
            stack_trace=safe_trace,
        )
        run_store.create(run)
        line_count = len(safe_raw_logs.splitlines()) if safe_raw_logs else 0
        log_detail = f"Fetched {line_count} line(s) from {source}"
        error_detail = f"{method.upper()} {endpoint or 'runtime'} - {status_code}"
        run.add_activity("logs_retrieved", "done", log_detail)
        run.add_activity("error_detected", "done", error_detail)
        run_store.update(run)

        log_operation(logger, run.id, "ingest", "ok", error=safe_message[:200])
        await emit(run.id, "logs_retrieved", "done", log_detail)
        await emit(run.id, "error_detected", "done", error_detail)
        return run

    async def restart(self, run_id: str) -> Run:
        """Replace the current run and diagnose its sanitized input again."""
        current = run_store.get(run_id)
        if not current:
            raise ValueError(f"run not found: {run_id}")
        if self.has_active_pipeline(run_id):
            raise ValueError("Cannot restart while diagnosis is still running.")

        detection = json.loads(json.dumps(current.detection or {}))
        request_snapshot = json.loads(json.dumps(current.request_snapshot or {}))
        owner_id = current.owner_id
        project_id = current.project_id
        stack_trace = current.stack_trace
        await self.reset_current(owner_id)

        fresh = Run(
            owner_id=owner_id,
            project_id=project_id,
            status=RunStatus.RECEIVED,
            detection=detection,
            request_snapshot=request_snapshot,
            stack_trace=stack_trace,
        )
        fresh.add_activity("fresh_start", "done", "Fresh diagnosis started")
        fresh.add_activity("logs_retrieved", "done", "Current input loaded")
        fresh.add_activity("error_detected", "done", "Error detected")
        fresh = run_store.create(fresh)
        if not self.start_diagnosis(fresh.id):
            fresh.status = RunStatus.FAILED
            fresh.error_message = "Fresh diagnosis could not be started."
            run_store.update(fresh)
            raise ValueError(fresh.error_message)
        return fresh

    def has_active_pipeline(self, run_id: str) -> bool:
        task = self._pipeline_tasks.get(run_id)
        return bool(task and not task.done())

    def start_diagnosis(self, run_id: str) -> bool:
        """Start or resume one background pipeline for a run."""
        run = run_store.get(run_id)
        if not run:
            return False

        if self.has_active_pipeline(run_id):
            return False

        # Allow resume from paused/stuck in-progress states as long as no
        # worker is running. PR_CREATED is the only non-restartable success.
        if run.status == RunStatus.PR_CREATED:
            return False

        task = asyncio.create_task(
            self.run_pipeline(run_id),
            name=f"api-doctor-pipeline-{run_id}",
        )
        self._pipeline_tasks[run_id] = task
        task.add_done_callback(
            lambda completed, iid=run_id: self._pipeline_finished(iid, completed)
        )
        return True

    def _pipeline_finished(
        self, run_id: str, task: asyncio.Task[Run | None]
    ) -> None:
        if self._pipeline_tasks.get(run_id) is task:
            self._pipeline_tasks.pop(run_id, None)
        try:
            task.result()
        except asyncio.CancelledError:
            logger.info("Diagnosis pipeline cancelled for run %s", run_id)
        except Exception:
            logger.exception("Unhandled diagnosis task failure for %s", run_id)

    async def cancel_diagnosis(self, run_id: str) -> bool:
        """Cancel a running, paused, or stuck diagnosis and close its current state.

        The pipeline task exits when it pauses for user approval, so cancel must
        still succeed for AWAITING_* and other non-terminal statuses even when
        no asyncio task is registered.
        """
        run = run_store.get(run_id)
        if not run:
            return False
        if run.status.is_terminal:
            return False

        task = self._pipeline_tasks.get(run_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        run = run_store.get(run_id)
        if not run:
            return False
        if run.status == RunStatus.CANCELLED:
            return True
        if run.status.is_terminal:
            return False

        run.status = RunStatus.CANCELLED
        run.error_message = "Diagnosis cancelled by user"
        for ev in run.activity:
            if ev.status in {"running", "pending"}:
                ev.status = "cancelled"
        run.add_activity("pipeline", "cancelled", run.error_message)
        run_store.update(run)
        await emit(run_id, "pipeline", "cancelled", run.error_message)
        return True

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------
    async def run_pipeline(self, run_id: str) -> Run | None:
        run = run_store.get(run_id)
        if not run:
            logger.error("Run %s not found", run_id)
            return None

        # Determine the project and workspace
        project = project_store.get(run.project_id) or project_store.get_current()
        workspace_path = None
        if project and project.workspace_path and Path(project.workspace_path).is_dir():
            workspace_path = project.workspace_path
        elif project and project.github_owner and project.github_repo:
            # The project's stored workspace_path may be unset or stale (e.g. a
            # project created before the sync completed). Fall back to the
            # canonical per-repository workspace layout managed by
            # WorkspaceManager so the sandbox/context runners are bound to THIS
            # run's repository and never to a shared global default.
            candidate = self.sandbox_runner.workspace_mgr.get_project_workspace_path(
                project.github_owner, project.github_repo
            )
            if candidate.is_dir():
                workspace_path = str(candidate)
        elif settings.DEMO_MODE:
            workspace_path = settings.INTERNAL_REPO_ROOT
        profile = project.profile if project else None

        if not workspace_path:
            # No workspace to operate on. Fail the run explicitly instead
            # of raising out of the background task, which previously left the
            # run stuck in RECEIVED/DETECTED with no error surfaced. The
            # user can retry once the project is connected (start_diagnosis
            # permits restart from any non-PR_CREATED status).
            run.status = RunStatus.FAILED
            run.error_message = (
                "No synchronized workspace is available for the selected project. "
                "Connect the repository and try again."
            )
            run.add_activity("pipeline", "failed", run.error_message)
            run_store.update(run)
            await emit(run_id, "pipeline", "failed", run.error_message)
            log_operation(logger, run_id, "pipeline", "failed", error=run.error_message)
            return run

        self.context_builder.set_repo_root(workspace_path)
        self.sandbox_runner.set_repo_root(workspace_path, profile)

        t_start = time.perf_counter()
        try:
            await emit(run.id, "pipeline", "running", "Starting diagnosis pipeline")

            # Every timeline step below corresponds to a real operation. The
            # repository state is actually inspected (git branch/commit/dirty
            # state) and the project profile is re-detected from disk instead
            # of echoing canned success messages. When resuming from an
            # interactive approval pause these setup steps already ran once and
            # are deliberately NOT re-emitted — replaying them is what made the
            # timeline look scripted.
            if not self._has_activity(run, "repository_connected", "done"):
                profile = await self._verify_repository(run, project, workspace_path, profile)
                self.sandbox_runner.set_repo_root(workspace_path, profile)

            resuming_approved_fix = self._should_resume_approved_fix(run)

            # Context collection (may pause for file read approval). Skip when
            # we already have context and are only resuming sandbox testing.
            if not (resuming_approved_fix and run.context):
                await self._collect_context(run, profile)
                if run.status == RunStatus.AWAITING_FILE_READ_APPROVAL:
                    await emit(run.id, "pipeline", "paused", "Waiting for file read approval")
                    return run

            # Investigation (may pause for fix approval). Skip when the user
            # already approved an existing proposal so we don't re-call the LLM.
            if not resuming_approved_fix:
                await self._investigate(run, profile)
                if run.status == RunStatus.AWAITING_FIX_APPROVAL:
                    await emit(run.id, "pipeline", "paused", "Waiting for fix approval")
                    return run

            if run.status in (
                RunStatus.FAILED,
                RunStatus.INVESTIGATION_FAILED,
                RunStatus.FIX_GENERATION_FAILED,
                RunStatus.REQUIRES_HUMAN_REVIEW,
            ):
                await emit(run.id, "pipeline", "failed", run.error_message or "investigation failed")
                return run

            if run.fix_proposal:
                await self._sandbox_and_verify(run, profile)
            await emit(run.id, "pipeline", "done", f"status={run.status}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            run.error_message = f"{type(exc).__name__}: {exc}"
            if run.status not in (
                RunStatus.FAILED,
                RunStatus.INVESTIGATION_FAILED,
                RunStatus.FIX_GENERATION_FAILED,
                RunStatus.VERIFICATION_FAILED,
                RunStatus.REPAIR_LIMIT_REACHED,
                RunStatus.CANCELLED,
            ):
                run.status = RunStatus.VERIFICATION_FAILED
            run.add_activity("pipeline_error", "failed", str(exc))
            log_operation(logger, run_id, "pipeline", "failed", error=str(exc))
            await emit(run_id, "pipeline_error", "failed", str(exc)[:500])
        finally:
            # Don't clobber an explicit user cancel that landed during unwind.
            latest = run_store.get(run_id)
            if latest and latest.status == RunStatus.CANCELLED:
                run = latest
            else:
                run_store.update(run)
            log_operation(
                logger, run_id, "pipeline", "done",
                duration=time.perf_counter() - t_start,
                error=run.error_message,
            )
        return run

    @staticmethod
    def _has_activity(run: Run, step: str, status: str) -> bool:
        return any(ev.step == step and ev.status == status for ev in run.activity)

    def _should_resume_approved_fix(self, run: Run) -> bool:
        """True when we should continue from sandbox instead of regenerating a fix."""
        if not run.fix_proposal or not self._has_activity(run, "fix_approval", "done"):
            return False
        return run.status in {
            RunStatus.AWAITING_FIX_APPROVAL,
            RunStatus.FIX_PLANNED,
            RunStatus.FIX_READY,
            RunStatus.SANDBOX_TESTING,
            RunStatus.SANDBOX_RUNNING,
            RunStatus.TESTING,
            RunStatus.VERIFYING,
        }

    # ------------------------------------------------------------------
    async def _collect_context(self, run: Run, profile: Any = None) -> None:
        """Two-phase context collection driven by real operations.

        Phase 1 (before approval): parse the stack trace and identify relevant
        file paths — no file contents are read yet.
        Phase 2 (after approval): read each approved file from disk one by one
        (emitting a live event per real read), then assemble the full context.
        """
        # Resuming from the file-read approval pause: the run already
        # carries the identification result (affected_files) from the first
        # pass, so we must not re-run or re-emit the setup steps.
        resuming = bool(
            run.context
            and (run.context.get("_complete") or run.context.get("affected_files"))
        )
        if not resuming:
            run.status = RunStatus.COLLECTING_CONTEXT
            run.add_activity("collecting_context", "running")
            run_store.update(run)
            await emit(run.id, "collecting_context", "running", "Parsing stack trace and identifying relevant files")
        t0 = time.perf_counter()
        try:
            if not run.context or not run.context.get("_complete"):
                if not (run.context and run.context.get("affected_files")):
                    # Phase 1a — actually parse the stack trace.
                    parsed = await asyncio.to_thread(self.context_builder.parse_trace, run)
                    trace_detail = (
                        f"{len(parsed.frames)} frame(s)"
                        + (f" · {parsed.exception_type}" if parsed.exception_type else "")
                    )
                    run.add_activity("stack_trace_parsed", "done", trace_detail)
                    run_store.update(run)
                    await emit(run.id, "stack_trace_parsed", "done", trace_detail)

                    # Phase 1b — identify relevant files (paths only, no reads).
                    identified = await asyncio.to_thread(
                        self.context_builder.identify_files, run, profile
                    )
                    run.add_activity(
                        "relevant_source_identified", "done", f"{len(identified)} file(s) identified"
                    )
                    run_store.update(run)
                    await emit(
                        run.id,
                        "relevant_source_identified",
                        "done",
                        f"{len(identified)} relevant file(s) identified",
                    )

                    # Carry the identification result on the run so the
                    # pause point can show the file list without having read
                    # anything.
                    run.context = {
                        "run_id": run.id,
                        "stack_trace": (run.stack_trace or "")[-4000:],
                        "affected_files": identified,
                        "code_snippets": {},
                    }
                    run_store.update(run)
                else:
                    # Resume after file-read approval — reuse the identification
                    # already stored at the pause point (no re-discovery).
                    identified = list(run.context.get("affected_files") or [])

                # Pause for file read approval unless the user already approved.
                # The timeline events only carry counts here — filenames first
                # appear in their own per-file "Reading <file>" events once the
                # approval is granted. (The approval card itself still renders
                # the list from the run context API.)
                if identified and not self._has_activity(run, "file_read_approval", "done"):
                    run.add_activity(
                        "files_to_read", "pending", f"{len(identified)} files identified for reading"
                    )
                    run.add_activity(
                        "file_read_approval", "pending", f"Approval needed: {len(identified)} files"
                    )
                    run.set_activity("collecting_context", "running", "Waiting for file read approval")
                    run.status = RunStatus.AWAITING_FILE_READ_APPROVAL
                    run_store.update(run)
                    await emit(
                        run.id, "files_to_read", "pending", f"{len(identified)} files identified for reading"
                    )
                    await emit(
                        run.id, "file_read_approval", "pending", f"Approval needed: {len(identified)} files"
                    )
                    await emit(run.id, "pipeline", "paused", "Waiting for file read approval")
                    return

                # Phase 2 — actually read every file, one at a time. Each event
                # is emitted only after the real read completes, and the full
                # content is cached on the run so later stages (fix
                # generation, retries) never re-read the workspace unless the
                # file's staleness is explicitly suspected.
                affected_files = list(run.context.get("affected_files", []))
                for rel in affected_files:
                    run.add_activity("file_read", "running", f"Reading {rel}")
                    run_store.update(run)
                    await emit(run.id, "file_read", "running", f"Reading {rel}")
                    read_info = await asyncio.to_thread(self._read_workspace_file, rel)
                    if read_info:
                        run.context.setdefault("file_contents", {})[rel] = read_info["content"]
                    run.set_activity("file_read", "done", f"Reading {rel}")
                    run_store.update(run)
                    detail = f"Reading {rel}"
                    if read_info:
                        detail = f"Read {rel} · {read_info['lines']} lines"
                    await emit(run.id, "file_read", "done", detail)

                # Assemble the full context bundle for the investigator. Keep
                # the exact approved source snapshot alongside the sanitized
                # retrieval payload.  Replacing ``run.context`` here used to
                # discard ``file_contents`` immediately after reading it, so a
                # later apply could not distinguish a genuinely changed file
                # from a malformed or already-applied patch.
                file_contents = dict(run.context.get("file_contents") or {})
                try:
                    context = self.context_builder.build(run, project_profile=profile)
                except TypeError:
                    context = self.context_builder.build(run)
                if not context.get("affected_files"):
                    context["affected_files"] = affected_files
                context["file_contents"] = file_contents
                context["_complete"] = True
                run.context = context
                run_store.update(run)

            affected_count = len((run.context or {}).get("affected_files", []))
            run.set_activity("collecting_context", "done", f"{affected_count} files")
            log_operation(logger, run.id, "collect_context", "ok", duration=time.perf_counter() - t0)
            await emit(run.id, "collecting_context", "done", f"{affected_count} relevant file(s) in context")
        except Exception as exc:
            run.status = RunStatus.INVESTIGATION_FAILED
            run.error_message = f"context build failed: {exc}"
            run.set_activity("collecting_context", "failed", str(exc)[:200])
            log_operation(logger, run.id, "collect_context", "failed", error=str(exc))
            await emit(run.id, "collecting_context", "failed", str(exc)[:500])
            raise
        finally:
            run_store.update(run)

    def _read_workspace_file(self, rel: str) -> dict[str, Any] | None:
        """Really read one workspace file from disk (used for live progress).

        Returns the full content as well so it can be cached on the run;
        the fix pipeline then never needs to re-read the workspace unless a
        file's staleness is explicitly suspected.
        """
        full = self.context_builder.repo_root / rel
        try:
            if not full.is_file():
                return None
            text = full.read_text(encoding="utf-8", errors="replace")
            return {
                "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
                "bytes": len(text.encode("utf-8")),
                "content": text,
            }
        except Exception:
            return None

    async def _verify_repository(
        self, run: Run, project: Any, workspace_path: str, profile: Any
    ) -> Any:
        """Actually inspect the workspace repository and emit real results."""
        await emit(run.id, "repository_check", "running", "Verifying repository workspace")
        run.add_activity("repository_check", "running", "Verifying repository workspace")
        run_store.update(run)

        ws = Path(workspace_path)
        branch, sha, dirty = await asyncio.to_thread(self._inspect_git_workspace, ws)

        repo_label = ws.name
        if project is not None:
            owner = getattr(project, "github_owner", "") or ""
            repo = getattr(project, "github_repo", "") or ""
            if owner and repo:
                repo_label = f"{owner}/{repo}"

        if branch and sha:
            detail = f"{repo_label} @ {branch} · {sha}"
        else:
            detail = f"{repo_label} · local workspace"
        run.set_activity("repository_check", "done", detail)
        run.add_activity("repository_connected", "done", detail)
        run_store.update(run)
        await emit(run.id, "repository_connected", "done", detail)

        if branch:
            sync_detail = f"workspace clean @ {sha}" if dirty == 0 else f"{dirty} uncommitted change(s) in workspace"
        else:
            sync_detail = "workspace directory present"
        run.add_activity("repository_synced", "done", sync_detail)
        run_store.update(run)
        await emit(run.id, "repository_synced", "done", sync_detail)

        # Re-detect the project type from the actual files on disk.
        from app.projects.discovery import discover_project

        detected = await asyncio.to_thread(discover_project, ws)
        if detected is not None:
            lang = getattr(detected, "language", None) or "unknown"
            fw = getattr(detected, "framework", None) or ""
            disc = f"{lang} · {fw}" if fw else str(lang)
            run.add_activity("project_discovered", "done", disc)
            run_store.update(run)
            await emit(run.id, "project_discovered", "done", disc)
            if profile is None:
                profile = detected
        return profile

    @staticmethod
    def _inspect_git_workspace(ws: Path) -> tuple[str, str, int]:
        """Return (branch, short sha, dirty file count) for a workspace."""
        if not (ws / ".git").is_dir():
            return "", "", 0

        def _git(*args: str) -> str:
            try:
                res = subprocess.run(
                    ["git", "-C", str(ws), *args],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                return res.stdout.strip() if res.returncode == 0 else ""
            except Exception:
                return ""

        branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
        sha = _git("rev-parse", "--short", "HEAD")
        status = _git("status", "--porcelain")
        dirty = len([ln for ln in status.splitlines() if ln.strip()]) if status else 0
        return branch, sha, dirty

    async def _investigate(self, run: Run, profile: Any = None) -> None:
        run.status = RunStatus.INVESTIGATING
        run.add_activity("investigating", "running")
        run_store.update(run)
        await emit(run.id, "investigating", "running", "Investigating root cause")
        t0 = time.perf_counter()
        try:
            analysis: RootCauseAnalysis = await self.root_cause_agent.analyze(run.context or {})
            run.root_cause = analysis.model_dump()
            if analysis.confidence < settings.MIN_ROOT_CAUSE_CONFIDENCE:
                run.status = RunStatus.INVESTIGATION_FAILED
                run.error_message = (
                    f"Low confidence ({analysis.confidence:.2f} < "
                    f"{settings.MIN_ROOT_CAUSE_CONFIDENCE}): {analysis.reason}"
                )
                run.add_activity("root_cause_identified", "failed", run.error_message)
                run.set_activity("investigating", "failed", run.error_message[:200])
                log_operation(logger, run.id, "root_cause", "failed", duration=time.perf_counter() - t0, error=run.error_message)
                await emit(run.id, "investigating", "failed", run.error_message)
                return

            run.status = RunStatus.ROOT_CAUSE_FOUND
            run.add_activity("root_cause_identified", "done", "Root cause identified")
            run.set_activity("investigating", "done", "Root cause identified")
            log_operation(logger, run.id, "root_cause", "ok", duration=time.perf_counter() - t0, error=f"confidence={analysis.confidence:.2f}")
            await emit(run.id, "root_cause_identified", "done", "Root cause identified")
            await emit(run.id, "investigating", "done", "Root cause identified")
        except Exception as exc:
            run.status = RunStatus.INVESTIGATION_FAILED
            run.error_message = f"root cause analysis failed: {exc}"
            run.add_activity("root_cause_identified", "failed", str(exc))
            run.set_activity("investigating", "failed", str(exc)[:200])
            log_operation(logger, run.id, "root_cause", "failed", error=str(exc))
            await emit(run.id, "investigating", "failed", str(exc)[:500])
            raise
        finally:
            run_store.update(run)

        if run.status in (RunStatus.FAILED, RunStatus.REQUIRES_HUMAN_REVIEW, RunStatus.INVESTIGATION_FAILED):
            return

        # Fix generation
        run.status = RunStatus.FIX_PLANNED
        run.add_activity("fix_generated", "running")
        run_store.update(run)
        await emit(run.id, "fix_generated", "running", "Generating fix")
        t0 = time.perf_counter()
        try:
            # Hard validation gate: the proposal may ONLY reference files that
            # were actually identified/read for this run. A hallucinated
            # path (e.g. "app/main.py" when the repo is flat) is rejected and
            # the model regenerates with corrective feedback instead of being
            # silently handed to the sandbox / apply step, where it would fail
            # with "Original file not found".
            proposal: FixProposal = await self._generate_validated_fix(
                analysis, run, profile
            )
            run.fix_proposal = proposal.model_dump()
            run.set_activity("fix_generated", "done", proposal.summary)
            log_operation(logger, run.id, "fix_generation", "ok", duration=time.perf_counter() - t0)
            await emit(run.id, "fix_generated", "done", proposal.summary)
            
            # Pause for fix approval - show user the proposed fix before sandbox testing
            if proposal and proposal.diff and not self._has_activity(run, "fix_approval", "done"):
                run.status = RunStatus.AWAITING_FIX_APPROVAL
                run.add_activity("fix_approval", "pending", f"Fix proposed: {proposal.summary}")
                run.add_activity("diff_ready", "pending", f"Files to change: {', '.join(proposal.files_changed or [])}")
                run_store.update(run)
                await emit(run.id, "fix_approval", "pending", "Approval needed: review proposed fix")
                await emit(run.id, "pipeline", "paused", "Waiting for fix approval")
                return
        except Exception as exc:
            run.status = RunStatus.FIX_GENERATION_FAILED
            run.error_message = f"fix generation failed: {exc}"
            run.set_activity("fix_generated", "failed", str(exc)[:200])
            log_operation(logger, run.id, "fix_generation", "failed", error=str(exc))
            await emit(run.id, "fix_generated", "failed", str(exc)[:500])
        finally:
            run_store.update(run)

    async def _sandbox_and_verify(self, run: Run, profile: Any = None) -> None:
        proposal_data = run.fix_proposal
        if not proposal_data:
            return
        proposal = FixProposal.model_validate(proposal_data)
        analysis = (
            RootCauseAnalysis.model_validate(run.root_cause)
            if run.root_cause else None
        )

        # When the user chose "Keep Changes", the patch has already been
        # applied to the real workspace. Verification must then run against the
        # pre-apply snapshot so the failure can still be reproduced.
        apply_state = self._load_apply_state(run.id)
        verification_tmp: tempfile.TemporaryDirectory[str] | None = None
        if apply_state:
            from app.sandbox.workspace_manager import _IGNORE_PATTERNS

            workspace = Path(apply_state.get("workspace") or "")
            if workspace.is_dir():
                # Build a short-lived pre-apply workspace for verification.
                # It lives under the OS temp directory and is destroyed when
                # this function returns; no diagnosis snapshot is archived.
                verification_tmp = tempfile.TemporaryDirectory(prefix="api-doctor-verify-")
                verification_root = Path(verification_tmp.name) / "workspace"
                shutil.copytree(
                    workspace,
                    verification_root,
                    ignore=_IGNORE_PATTERNS,
                    dirs_exist_ok=True,
                )
                for rel, content in (apply_state.get("snapshots") or {}).items():
                    destination = verification_root / rel
                    if content is None:
                        destination.unlink(missing_ok=True)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(content)
                self.sandbox_runner.set_repo_root(verification_root, profile)
            proposal_data = dict(proposal_data)
            proposal_data["diff"] = apply_state.get("resolved_diff") or proposal_data["diff"]
            proposal = FixProposal.model_validate(proposal_data)

        def _cleanup_verification_workspace() -> None:
            if verification_tmp is not None:
                verification_tmp.cleanup()
            _project, real_workspace = self._resolve_project_workspace(run)
            if real_workspace is not None:
                self.sandbox_runner.set_repo_root(real_workspace, profile)

        run.status = RunStatus.SANDBOX_TESTING
        run.add_activity("sandbox_started", "running")
        run.add_activity("tests_started", "running")
        run_store.update(run)
        await emit(run.id, "sandbox_started", "running", "Running sandbox verification on isolated copy")
        await emit(run.id, "tests_started", "running", "Running tests")

        # With changes already applied to the workspace we run a single
        # verification pass — regenerating a different fix would desynchronize
        # the workspace from what the user approved.
        max_attempts = 1 if apply_state else max(1, settings.MAX_REPAIR_ATTEMPTS)

        attempt = 0
        result: SandboxResult | None = None
        while attempt < max_attempts:
            attempt += 1
            run.attempt_count = attempt
            run.set_activity("sandbox_started", "running", f"attempt {attempt}")
            run_store.update(run)
            await emit(run.id, "sandbox_started", "running", f"attempt {attempt}")
            t0 = time.perf_counter()
            try:
                result = await asyncio.to_thread(
                    self.sandbox_runner.run_verification, proposal, run.request_snapshot
                )
            except Exception as exc:
                run.status = RunStatus.VERIFICATION_FAILED
                run.error_message = f"sandbox error: {exc}"
                run.set_activity("sandbox_started", "failed", str(exc)[:200])
                run.set_activity("tests_started", "failed", str(exc)[:200])
                log_operation(logger, run.id, "sandbox", "failed", error=str(exc))
                run_store.update(run)
                await emit(run.id, "sandbox_started", "failed", str(exc)[:500])
                await emit(run.id, "tests_started", "failed", str(exc)[:500])
                _cleanup_verification_workspace()
                return

            log_operation(
                logger, run.id, "sandbox_attempt", "ok" if result.passed else "failed",
                duration=time.perf_counter() - t0,
                error="" if result.passed else result.error,
            )

            if result.passed:
                break
            if attempt < max_attempts:
                # A single explicit retry marker replaces any replay of the
                # setup sequence: repository sync, file discovery and file
                # reads already happened once and are cached on the run.
                retry_marker = f"Attempt {attempt + 1} of {max_attempts} — regenerating fix"
                run.set_activity("fix_regenerating", "running", retry_marker)
                run_store.update(run)
                await emit(run.id, "fix_regenerating", "running", retry_marker)
                try:
                    if analysis:
                        proposal = await self._generate_validated_fix(
                            analysis,
                            run,
                            profile,
                            feedback=result.logs[-3000:] or result.error,
                        )
                        run.fix_proposal = proposal.model_dump()
                        # Keep the marker text on the closing "done" so the
                        # timeline row reads "Attempt 2 of 2 — regenerating fix".
                        run.set_activity("fix_regenerating", "done", retry_marker)
                        run_store.update(run)
                        await emit(run.id, "fix_regenerating", "done", retry_marker)
                except Exception:
                    run.set_activity("fix_regenerating", "failed", "regeneration failed")
                    run_store.update(run)
                    await emit(run.id, "fix_regenerating", "failed", "regeneration failed")
                    break

        _cleanup_verification_workspace()
        run.sandbox_result = result.model_dump() if result else {"passed": False, "error": "no result"}

        if result and result.passed:
            run.status = RunStatus.FIX_VERIFIED
            # The retry loop flipped fix_generated to "running" for the
            # regeneration marker; restore it to a completed state so the
            # timeline does not end on a dangling "regenerating" row.
            run.set_activity(
                "fix_generated", "done",
                (run.fix_proposal or {}).get("summary") or "fix regenerated",
            )
            run.set_activity("sandbox_started", "done")
            run.set_activity("tests_started", "done", "tests passed")
            run.add_activity("test_passed", "done", "all sandbox steps passed")
            for step in result.steps:
                run.add_activity(step.name, "done" if step.passed else "failed", _summarize_step(step))
            run.add_activity("fix_verified", "done")
            await emit(run.id, "test_passed", "done", "Sandbox tests passed")
            await emit(run.id, "tests_started", "done", "All sandbox tests passed")
            await emit(run.id, "sandbox_started", "done", "Verification passed")
            await emit(run.id, "fix_verified", "done", "Fix verified")
        else:
            run.status = RunStatus.REPAIR_LIMIT_REACHED if attempt >= max_attempts else RunStatus.VERIFICATION_FAILED
            run.error_message = result.error if result else "verification failed"
            run.set_activity("sandbox_started", "failed", run.error_message[:200])
            run.set_activity("tests_started", "failed", run.error_message[:200])
            run.add_activity("fix_verified", "failed", run.error_message[:200])
            await emit(run.id, "tests_started", "failed", run.error_message[:500])
            await emit(run.id, "fix_verified", "failed", run.error_message[:500])

        # Finalize the Keep-Changes workspace application based on the result.
        if apply_state:
            if result and result.passed:
                self._discard_apply_snapshot(run.id)
                run.add_activity(
                    "workspace_updated",
                    "done",
                    f"Verified fix kept in workspace: {', '.join(apply_state.get('files', []))}",
                )
                await emit(run.id, "workspace_updated", "done", "Verified changes kept in workspace")
            else:
                await self._restore_workspace_files(run.id)
                if run.fix_proposal:
                    run.fix_proposal.pop("applied_files", None)
                    run.fix_proposal.pop("applied_at", None)
                run.add_activity(
                    "changes_rolled_back", "done", "Workspace restored to original state after failed verification"
                )
                await emit(
                    run.id,
                    "changes_rolled_back",
                    "done",
                    f"Verification failed — workspace restored ({(run.error_message or '')[:120]})",
                )

        run_store.update(run)

        # PR Gate
        if run.status == RunStatus.FIX_VERIFIED and settings.AUTO_CREATE_PR:
            try:
                await self.create_pull_request(run.id)
            except Exception as exc:  # noqa: BLE001
                run.error_message = f"PR creation failed: {exc}"
                run_store.update(run)
                await emit(run.id, "pr_created", "failed", str(exc)[:500])

    # ------------------------------------------------------------------
    # Keep Changes — real patch application to the project workspace
    # ------------------------------------------------------------------
    def _resolve_project_workspace(self, run: Run) -> tuple[Any, Path | None]:
        project = project_store.get(run.project_id) or project_store.get_current()
        if not project or not project.workspace_path:
            return project, None
        ws = Path(project.workspace_path)
        if not ws.is_dir():
            return project, None
        return project, ws

    async def stage_workspace_apply(self, run_id: str) -> dict[str, Any]:
        """Apply one run patch as a serialized workspace transaction."""
        async with self._workspace_apply_lock:
            return await self._stage_workspace_apply_locked(run_id)

    async def _stage_workspace_apply_locked(self, run_id: str) -> dict[str, Any]:
        """Apply the proposed patch to the REAL project workspace.

        Called when the user chooses "Keep Changes". A pre-apply snapshot is
        kept so sandbox verification can still reproduce the original failure
        and so the workspace can be rolled back if verification fails.
        The public wrapper serializes this method to make retries idempotent.
        """
        run = run_store.get(run_id)
        if not run:
            return {"applied": False, "reason": "run not found"}
        proposal = run.fix_proposal or {}
        diff = (proposal.get("resolved_diff") or proposal.get("diff") or "").strip()
        if not diff:
            return {"applied": False, "reason": "no fix proposal to apply"}

        # Idempotent: an action may be retried after a slow UI refresh or after
        # verification has discarded its in-memory rollback snapshot.  Never try
        # to apply the original hunk a second time: it will (correctly) no
        # longer match the already-fixed file and used to surface as a confusing
        # "File changed since diagnosis" conflict.
        if proposal.get("applied_files"):
            return {"applied": True, "files": proposal["applied_files"]}

        project, ws = self._resolve_project_workspace(run)
        if ws is None:
            if settings.DEMO_MODE:
                return {
                    "applied": False,
                    "skipped": True,
                    "reason": "demo workspace is read-only",
                }
            return {"applied": False, "reason": "Project workspace is not synchronized."}
        if ws.resolve() == Path(settings.INTERNAL_REPO_ROOT).resolve():
            # Never modify API Doctor's own source tree in demo mode. The
            # approval route may still continue with isolated sandbox-only
            # verification when this explicit skip marker is present.
            return {
                "applied": False,
                "skipped": True,
                "reason": "demo workspace is read-only",
            }

        def _do() -> dict[str, Any]:
            from app.sandbox.patch_utils import _parse_unified_diff, _strip_prefix

            try:
                resolved, mapping = resolve_diff_paths(diff, ws)
                affected_paths = validate_diff(resolved, allowed_roots=[str(ws)])
                file_patches = _parse_unified_diff(resolved)
            except PatchError as exc:
                return {"applied": False, "reason": f"Invalid patch: {exc}"}

            # Rollback data exists only in memory for the lifetime of this run.
            # None marks a file that did not exist before the patch.
            snapshots: dict[str, bytes | None] = {}
            try:
                for rel in affected_paths:
                    source = ws / rel
                    snapshots[rel] = source.read_bytes() if source.is_file() else None
            except Exception as exc:  # noqa: BLE001
                return {"applied": False, "reason": f"Could not create safety snapshot: {exc}"}

            def _restore_affected_from_snapshot() -> None:
                """Best-effort rollback for an unexpected filesystem error."""
                for rel, content in snapshots.items():
                    destination = ws / rel
                    try:
                        if content is None:
                            destination.unlink(missing_ok=True)
                        else:
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            destination.write_bytes(content)
                    except Exception:
                        logger.warning("Failed to restore %s after patch apply error", rel)

            try:
                # Unlike the strict sandbox applicator, the real-workspace path
                # is idempotent.  It recognizes an exact post-image left by a
                # request whose response/metadata write was interrupted.
                affected, already_applied = apply_patch_idempotent(resolved, ws)
                if already_applied:
                    diagnosed = (run.context or {}).get("file_contents") or {}
                    for rel in already_applied:
                        original = diagnosed.get(rel)
                        if isinstance(original, str):
                            snapshots[rel] = original.encode("utf-8")

            except PatchError as exc:
                _restore_affected_from_snapshot()
                message = str(exc)
                stale_files: list[str] = []
                diagnosed = (run.context or {}).get("file_contents") or {}
                for patch in file_patches:
                    if patch["old_path"] == "/dev/null":
                        continue
                    rel_old = _strip_prefix(patch["old_path"])
                    if rel_old not in diagnosed:
                        continue
                    current_file = ws / rel_old
                    current = (
                        current_file.read_text(encoding="utf-8", errors="replace")
                        if current_file.is_file()
                        else None
                    )
                    if current != diagnosed[rel_old] and rel_old not in stale_files:
                        stale_files.append(rel_old)

                if stale_files:
                    changed = f" ({', '.join(stale_files)})"
                    message = (
                        f"File changed since diagnosis{changed} — patch refused for safety. "
                        "Re-run the diagnosis to generate a fresh patch."
                    )
                elif "mismatch" in message:
                    # The workspace still matches the diagnosis snapshot; the
                    # patch itself does not fit (e.g. generated against an
                    # older revision of the file). Do not blame a workspace
                    # change that never happened.
                    message = (
                        "Patch does not match the current file content — patch refused for safety. "
                        "Re-run the diagnosis to generate a fresh patch."
                    )
                return {
                    "applied": False,
                    "reason": message,
                    "conflict": "workspace_changed" if stale_files else "patch_mismatch",
                    "stale_files": stale_files,
                }
            except Exception as exc:  # noqa: BLE001
                _restore_affected_from_snapshot()
                return {"applied": False, "reason": f"Could not apply patch safely: {exc}"}

            state = {
                "snapshots": snapshots,
                "files": affected,
                "resolved_diff": resolved,
                "mapping": mapping,
                "workspace": str(ws),
                "already_applied_files": already_applied,
            }
            self._workspace_apply[run_id] = state
            return {
                "applied": True,
                "files": affected,
                "mapping": mapping,
                "already_applied": bool(already_applied),
            }

        outcome = await asyncio.to_thread(_do)
        if outcome.get("applied"):
            files = outcome.get("files", [])
            if run.fix_proposal is not None:
                run.fix_proposal["applied_files"] = files
                run.fix_proposal["applied_at"] = _utc_iso()
                if outcome.get("mapping"):
                    run.fix_proposal["path_mapping"] = outcome["mapping"]
                # Sandbox + PR creation should use the resolved diff.
                try:
                    resolved_diff, _ = resolve_diff_paths(diff, ws)
                    run.fix_proposal["resolved_diff"] = resolved_diff
                except PatchError:
                    pass
            run.add_activity("changes_applied", "done", f"Applied to {', '.join(files)}")
            run_store.update(run)
            await emit(run.id, "changes_applied", "done", f"Changes applied to workspace: {', '.join(files)}")
            log_operation(logger, run_id, "apply_fix", "ok")
        else:
            run.add_activity("changes_applied", "failed", outcome.get("reason", "apply failed")[:200])
            run_store.update(run)
            await emit(run.id, "changes_applied", "failed", outcome.get("reason", "apply failed")[:300])
            log_operation(logger, run_id, "apply_fix", "failed", error=outcome.get("reason"))
        return outcome

    def _load_apply_state(self, run_id: str) -> dict[str, Any] | None:
        return self._workspace_apply.get(run_id)

    def _discard_apply_snapshot(self, run_id: str) -> None:
        self._workspace_apply.pop(run_id, None)

    async def _restore_workspace_files(self, run_id: str) -> None:
        """Restore workspace files from the current run's memory snapshot."""
        state = self._load_apply_state(run_id)
        if not state:
            return

        def _do() -> None:
            workspace = Path(state.get("workspace") or "")
            if not workspace.is_dir():
                return
            for rel, content in (state.get("snapshots") or {}).items():
                destination = workspace / rel
                try:
                    if content is None:
                        destination.unlink(missing_ok=True)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(content)
                except Exception:
                    logger.warning("Rollback could not restore %s", rel)

        await asyncio.to_thread(_do)
        self._discard_apply_snapshot(run_id)

    async def commit_changes(self, run_id: str) -> dict[str, Any]:
        """Create a real git commit in the project workspace for applied changes."""
        run = run_store.get(run_id)
        if not run:
            raise ValueError(f"run not found: {run_id}")
        proposal = run.fix_proposal or {}
        files = proposal.get("applied_files") or []
        if not files:
            raise ValueError("No applied changes to commit. Use Keep Changes first.")

        project, ws = self._resolve_project_workspace(run)
        if ws is None:
            raise ValueError("Project workspace is not synchronized.")
        if not (ws / ".git").is_dir():
            raise ValueError("Project workspace is not a git repository.")

        summary = proposal.get("summary") or "automated repair"
        message = f"fix: {summary}\n\napi-doctor run {run_id}"

        def _git(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                ["git", "-C", str(ws), *args], capture_output=True, text=True, timeout=30
            )

        def _do() -> dict[str, Any]:
            # Ensure a commit identity exists in this clone.
            if not _git("config", "user.email").stdout.strip():
                _git("config", "user.email", "api-doctor@users.noreply.github.com")
            if not _git("config", "user.name").stdout.strip():
                _git("config", "user.name", "API Doctor")

            add = _git("add", "--", *files)
            if add.returncode != 0:
                raise RuntimeError(f"git add failed: {(add.stderr or '').strip()[:300]}")
            staged = _git("diff", "--cached", "--name-only").stdout.strip()
            if not staged:
                # If nothing is staged, the workspace may already contain the
                # requested changes. Probe a temporary copy with the proposed
                # diff to distinguish "already applied" from a real failure.
                try:
                    from app.sandbox.workspace_manager import WorkspaceManager
                    from app.sandbox.patch_utils import apply_patch_idempotent, PatchError

                    # Probe with the RESOLVED diff: the AI may have referenced
                    # un-relocated paths that only exist in the mapping, and a
                    # raw-diff probe would misread "already applied" as an error.
                    diff_text = proposal.get("resolved_diff") or proposal.get("diff") or ""
                    if diff_text.strip():
                        wm = WorkspaceManager(repo_root=str(ws))
                        tmp = wm.create_workspace()
                        try:
                            affected, already_applied = apply_patch_idempotent(diff_text, tmp)
                        finally:
                            wm.cleanup(tmp)
                        if affected and set(affected) <= set(already_applied):
                            # All changes are already present in the workspace.
                            sha = _git("rev-parse", "HEAD").stdout.strip()
                            return {"sha": sha, "files": affected}
                except PatchError:
                    # Fall through to the original error for clarity to caller.
                    pass

                raise RuntimeError(
                    "Nothing to commit — the workspace already matches the fix or changes were reverted."
                )
            commit = _git("commit", "-m", message)
            if commit.returncode != 0:
                raise RuntimeError(f"git commit failed: {(commit.stderr or '').strip()[:300]}")
            sha = _git("rev-parse", "HEAD").stdout.strip()
            return {"sha": sha, "files": staged.splitlines()}

        try:
            outcome = await asyncio.to_thread(_do)
        except Exception as exc:  # noqa: BLE001
            run.add_activity("local_commit", "failed", str(exc)[:200])
            run_store.update(run)
            await emit(run.id, "local_commit", "failed", str(exc)[:300])
            raise

        proposal["commit_sha"] = outcome["sha"]
        run.add_activity("local_commit", "done", outcome["sha"][:12])
        run_store.update(run)
        await emit(run.id, "local_commit", "done", f"Committed {outcome['sha'][:12]} in workspace")
        return {"sha": outcome["sha"], "message": message, "files": outcome["files"]}

    # ------------------------------------------------------------------
    # Resume from approval pause points
    # ------------------------------------------------------------------
    async def resume_file_read(self, run_id: str) -> bool:
        """Mark file-read as approved and continue the diagnosis pipeline."""
        run = run_store.get(run_id)
        if not run:
            logger.error("Run %s not found", run_id)
            return False
        if run.status != RunStatus.AWAITING_FILE_READ_APPROVAL:
            logger.warning("Run %s not in AWAITING_FILE_READ_APPROVAL state", run_id)
            return False

        run.add_activity("file_read_approval", "done", "User approved file reading")
        run.status = RunStatus.COLLECTING_CONTEXT
        run.set_activity("collecting_context", "running", "Reading approved files")
        run_store.update(run)
        await emit(run.id, "file_read_approval", "done", "File read approved")
        await emit(run.id, "collecting_context", "running", "Reading approved files")

        if not self.start_diagnosis(run_id):
            logger.error("Failed to resume diagnosis after file-read approval for %s", run_id)
            return False
        return True

    async def resume_fix(self, run_id: str) -> bool:
        """Mark the proposed fix as approved and continue into sandbox testing."""
        run = run_store.get(run_id)
        if not run:
            logger.error("Run %s not found", run_id)
            return False
        if run.status != RunStatus.AWAITING_FIX_APPROVAL:
            # Idempotent: a duplicate resume (double click, browser retry on a
            # dropped response) can legitimately land after the gate was
            # already crossed and the pipeline is past the approval pause.
            if (
                self._has_activity(run, "fix_approval", "done")
                and run.status in POST_FIX_GATE_STATUSES
            ):
                return True
            logger.warning("Run %s not in AWAITING_FIX_APPROVAL state", run_id)
            return False

        if not self._has_activity(run, "fix_approval", "done"):
            run.add_activity("fix_approval", "done", "User approved fix")
        # Flip out of the awaiting state in the SAME store write as the
        # recorded approval, so an overlapping approval request observes the
        # gate as already crossed instead of resuming a second time and
        # hitting "no active pipeline slots" (which used to surface as a
        # bogus 500 'Failed to resume fix').
        run.status = RunStatus.SANDBOX_TESTING
        run_store.update(run)
        await emit(run.id, "fix_approval", "done", "Fix approved")

        if not self.start_diagnosis(run_id):
            # A racing earlier resume already started the pipeline — that is
            # the in-flight duplicate case, not a failure.
            if self.has_active_pipeline(run_id):
                return True
            logger.error("Failed to resume diagnosis after fix approval for %s", run_id)
            return False
        return True

    # ------------------------------------------------------------------
    # GitHub PR
    # ------------------------------------------------------------------
    def _full_files(self, run: Run) -> dict[str, str]:
        """Full content of affected files, preferring the per-run cache.

        Files read during context collection are cached on the run
        (``context.file_contents``), so fix generation and sandbox retries do
        not re-read the workspace. Disk is only consulted for files that were
        never cached.
        """
        files: dict[str, str] = {}
        cached = (run.context or {}).get("file_contents") or {}
        affected: list[str] = []
        for rel in (run.context or {}).get("affected_files") or []:
            if rel not in affected:
                affected.append(rel)
        for rel in (run.root_cause or {}).get("affected_files") or []:
            if rel not in affected:
                affected.append(rel)
        for rel in affected:
            # Empty source files are still a valid cached snapshot.
            if rel in cached:
                files[rel] = cached[rel]
                continue
            full = self.sandbox_runner.repo_root / rel
            if full.is_file():
                files[rel] = full.read_text(encoding="utf-8", errors="replace")
        if not files and run.context and run.context.get("code_snippets"):
            for rel, data in run.context["code_snippets"].items():
                if isinstance(data, dict):
                    files[rel] = data.get("content", "")[:4000]
        return files

    # ------------------------------------------------------------------
    # Fix-path validation (anti-hallucination gate)
    # ------------------------------------------------------------------
    def _known_paths(self, run: Run) -> set[str]:
        """Every path the pipeline has actually seen for this run.

        Sources: context files identified by the file-determiner, snippet keys
        produced by the retriever, and files named by the root-cause analysis.
        Anything outside this set is a model invention and must not be applied.
        """
        known: set[str] = set()
        ctx = run.context or {}
        for rel in ctx.get("affected_files") or []:
            if rel:
                known.add(rel)
        for rel in (ctx.get("code_snippets") or {}).keys():
            if rel:
                known.add(rel)
        for rel in (run.root_cause or {}).get("affected_files") or []:
            if rel:
                known.add(rel)
        return known

    def _acceptable_paths(self, run: Run) -> set[str]:
        """Paths a fix may touch: known AND verified to exist.

        ``known`` alone can be poisoned by a model naming a plausible path it
        never saw (e.g. a root-cause agent pattern-matching ``app/`` from the
        tool's own repo). A path only becomes acceptable once it has actually
        been read into the run cache or is found on the bound workspace
        disk — that is the precise guarantee behind "never apply a path that
        does not exist".
        """
        known = self._known_paths(run)
        existing: set[str] = set()
        cached = (run.context or {}).get("file_contents") or {}
        existing.update(cached.keys())
        root = self.sandbox_runner.repo_root
        for rel in known:
            if (root / rel).is_file():
                existing.add(rel)
        return {rel for rel in known if rel in existing}

    def _unknown_paths(
        self, proposal: FixProposal, acceptable: set[str]
    ) -> set[str]:
        """Paths referenced by the proposal that are not acceptable.

        Checks both the structured ``files_changed`` list and the paths the
        unified diff actually touches (old-side headers; brand-new files whose
        old side is ``/dev/null`` are exempt because they have no original file
        to misname).
        """
        unknown: set[str] = set()
        for rel in proposal.files_changed or []:
            if rel and rel not in acceptable:
                unknown.add(rel)
        for line in (proposal.diff or "").splitlines():
            if line.startswith("--- "):
                rel = line[4:].strip()
                rel = rel[2:] if rel.startswith("a/") else rel
                if rel and rel != "/dev/null" and rel not in acceptable:
                    unknown.add(rel)
        return unknown

    @staticmethod
    def _path_feedback(unknown: set[str], known: set[str]) -> str:
        return (
            f"You referenced {sorted(unknown)}, which do not exist in this "
            f"project. You may ONLY use these exact paths: {sorted(known)}. "
            f"Do not invent a directory prefix."
        )

    async def _call_fix_agent(
        self,
        analysis: RootCauseAnalysis,
        files: dict[str, str],
        profile: Any,
        feedback: str | None,
    ) -> FixProposal:
        try:
            return await self.fix_agent.generate_fix(
                analysis, files, project_profile=profile, feedback=feedback
            )
        except TypeError:
            # Legacy signature without project_profile.
            return await self.fix_agent.generate_fix(analysis, files, feedback=feedback)

    async def _generate_validated_fix(
        self,
        analysis: RootCauseAnalysis,
        run: Run,
        profile: Any = None,
        feedback: str | None = None,
    ) -> FixProposal:
        """Generate a fix, rejecting and regenerating hallucinated paths.

        An empty diff raises immediately (a coder model with nothing to say
        should fail fast, not produce a confusing sandbox failure). Proposals
        that reference paths outside the run's known context are rejected
        and regenerated with corrective feedback, up to ``_FIX_PATH_RETRIES``
        times, then fail with a precise message. The sandbox/apply stage is
        only ever handed a proposal whose paths were already proven to exist.
        """
        acceptable = self._acceptable_paths(run)
        files = self._full_files(run)
        correction = feedback
        rejected = False
        last_unknown: set[str] = set()
        for round_no in range(_FIX_PATH_RETRIES + 1):
            proposal = await self._call_fix_agent(analysis, files, profile, correction)
            if not (proposal.diff or "").strip():
                raise ValueError("coder model returned an empty diff; no patch to apply")
            last_unknown = self._unknown_paths(proposal, acceptable)
            if not last_unknown:
                if rejected:
                    # The rejection was visible as its own live step; close it
                    # out with a separate done entry so the timeline does not
                    # end on a spinner and the rejection stays on record.
                    message = "Fix regenerated with corrected paths"
                    run.add_activity("fix_regenerating", "done", message)
                    run_store.update(run)
                    await emit(run.id, "fix_regenerating", "done", message)
                return proposal
            rejected = True
            correction = self._path_feedback(last_unknown, acceptable)
            if round_no < _FIX_PATH_RETRIES:
                message = "Rejected proposal: paths not found in project — regenerating"
                # set_activity keeps a single live row across rejection rounds.
                run.set_activity("fix_regenerating", "running", message)
                run_store.update(run)
                await emit(run.id, "fix_regenerating", "running", message)
        # Retries exhausted — close the regenerating row as failed so the
        # timeline never ends on a dangling spinner.
        message = (
            "Could not regenerate with valid paths: "
            f"{sorted(last_unknown)}"
        )
        run.set_activity("fix_regenerating", "failed", message)
        run_store.update(run)
        await emit(run.id, "fix_regenerating", "failed", message)
        raise ValueError(
            "coder model referenced paths not present in the project: "
            f"{sorted(last_unknown)}"
        )

    async def create_pull_request(self, run_id: str) -> dict[str, Any]:
        from app.github.client import GitHubClient
        from app.github.service import GitHubService

        run = run_store.get(run_id)
        if not run:
            raise ValueError(f"run not found: {run_id}")
        if not run.fix_proposal or not run.fix_proposal.get("diff"):
            raise ValueError("run has no verified fix to open a PR for")

        # Check Repair Gate: must be verified
        if run.status not in (RunStatus.FIX_VERIFIED, RunStatus.PR_READY):
            if not (run.sandbox_result and run.sandbox_result.get("passed")):
                raise ValueError("Cannot create PR: fix has not passed sandbox verification gates.")

        project = project_store.get(run.project_id) or project_store.get_current()
        if not project or not project.workspace_path or not Path(project.workspace_path).is_dir():
            raise ValueError("Cannot create PR: project workspace is not synchronized.")

        # Fail fast with actionable guidance BEFORE touching the network:
        # without a linked repository/token every GitHub call would die with
        # a confusing 4xx deep inside the flow.
        github = project_store.resolve_github(project.id)
        if not (github.get("owner") and github.get("repo")):
            raise ValueError(
                "Cannot create pull request: no GitHub repository is linked to this project. "
                "Set the repository owner and name in Project Settings, then retry."
            )
        if not github.get("token"):
            raise ValueError(
                "Cannot create pull request: no GitHub access token is configured for this project. "
                "Add one in Project Settings, then retry."
            )

        # The orchestrator's context/sandbox runners are singletons whose
        # repo_root is whatever project was diagnosed last. Re-bind them to
        # THIS run's project so _changes_from_diff reads the correct
        # repository and commits the right file contents.
        self.context_builder.set_repo_root(project.workspace_path)
        self.sandbox_runner.set_repo_root(project.workspace_path, project.profile)

        gh_client = GitHubClient(
            token=github.get("token", ""),
            owner=github.get("owner", ""),
            repo=github.get("repo", ""),
            default_branch=github.get("branch", "main"),
        )
        service = GitHubService(gh_client)

        diff = run.fix_proposal.get("resolved_diff") or run.fix_proposal["diff"]
        changes = self._changes_from_diff(diff)
        if not changes:
            raise ValueError(
                "Could not derive file changes from the proposed diff — the workspace layout may have changed."
            )
        summary = run.fix_proposal.get("summary") or "Fix"
        title = f"fix(api-doctor): {summary}"
        body = self._pr_body(run)

        # Report branch work honestly: "running" while GitHub is being asked,
        # "done" only once the PR payload exists, "failed" otherwise. The old
        # flow claimed a created branch BEFORE anything happened, so a failed
        # attempt left a permanently misleading timeline.
        branch_name = f"api-doctor/fix/{run_id}"
        run.add_activity("branch_created", "running", branch_name)
        run_store.update(run)
        await emit(run.id, "branch_created", "running", f"Creating repair branch {branch_name}")
        try:
            pr_info = await service.repair(
                run_id=run_id,
                changes=changes,
                message=f"fix: {summary}\n\napi-doctor run {run_id}",
                title=title,
                body=body,
                project=project,
            )
        except Exception as exc:
            run.set_activity("branch_created", "failed", str(exc)[:200])
            run.error_message = f"PR creation failed: {exc}"
            run_store.update(run)
            await emit(run.id, "branch_created", "failed", str(exc)[:300])
            raise

        run.set_activity("branch_created", "done", branch_name)
        run_store.update(run)
        await emit(run.id, "branch_created", "done", branch_name)

        await emit(run.id, "commit_created", "done", pr_info.get("head_sha", ""))
        run.add_activity("commit_created", "done", pr_info.get("head_sha", ""))

        run.pr_info = pr_info
        run.status = RunStatus.PR_CREATED
        run.add_activity("pr_created", "done", pr_info.get("pr_url") or "")
        # A retry succeeded after an earlier failed attempt — drop the stale
        # failure so the UI does not keep flagging it.
        if (run.error_message or "").startswith("PR creation failed"):
            run.error_message = ""
        run_store.update(run)
        await emit(run.id, "pr_created", "done", pr_info.get("pr_url") or "")
        return pr_info

    async def pr_status(self, run_id: str) -> dict[str, Any]:
        from app.github.client import GitHubClient
        from app.github.service import GitHubService

        run = run_store.get(run_id)
        if not run:
            return {"present": False, "error": "run not found"}

        project = project_store.get(run.project_id) or project_store.get_current()
        github = project_store.resolve_github(project.id if project else None)
        gh_client = GitHubClient(
            token=github.get("token", ""),
            owner=github.get("owner", ""),
            repo=github.get("repo", ""),
            default_branch=github.get("branch", "main"),
        )
        service = GitHubService(gh_client)
        return await service.pr_status(run_id, run.pr_info)

    def _changes_from_diff(self, diff: str) -> list[dict[str, str]]:
        from app.sandbox.workspace_manager import WorkspaceManager
        from app.sandbox.patch_utils import apply_patch_idempotent, PatchError

        wm = WorkspaceManager(repo_root=self.sandbox_runner.repo_root)
        ws = wm.create_workspace()
        try:
            try:
                affected, already_applied = apply_patch_idempotent(diff, ws)
            except PatchError:
                # Fall back to strict apply to raise the original failure
                affected = []
                raise
            changes = []
            for rel in affected:
                content = wm.read_relative(ws, rel)
                if content is not None:
                    changes.append({"path": rel, "content": content})
            return changes
        finally:
            wm.cleanup(ws)

    def _pr_body(self, run: Run) -> str:
        rc = run.root_cause or {}
        fix = run.fix_proposal or {}
        lines = [
            f"## API Doctor — Run `{run.id}`",
            "",
            f"**Classification:** {rc.get('classification') or rc.get('category')}",
            f"**Confidence:** {rc.get('confidence')}",
            "",
            "### Root cause",
            str(rc.get("root_cause") or ""),
            "",
            "### Fix",
            str(fix.get("summary") or ""),
            "",
            "### Risk",
            str(fix.get("risk") or "low"),
            "",
            "> Verified by API Doctor Sandbox. Please review before merging.",
        ]
        return "\n".join(lines)


def _summarize_step(step: Any) -> str:
    name = getattr(step, "name", "")
    passed = bool(getattr(step, "passed", False))
    detail = (getattr(step, "detail", "") or "").strip()
    if not detail:
        return "ok" if passed else "failed"

    cleaned_lines: list[str] = []
    for line in detail.splitlines():
        s = line.strip()
        if s.startswith("{") and "\"timestamp\"" in s:
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines).strip()

    if name == "reproduce_failure":
        for line in reversed(cleaned_lines):
            s = line.strip()
            if s.startswith("AttributeError") or s.startswith("TypeError") or s.startswith("ValueError") or s.startswith("Error"):
                return s[:200]
        tail = _tail_markers(cleaned, ("STATUS", "BODY", "OK"))
        return tail[:200] if tail else ("reproduced failure" if passed else "did not reproduce failure")
    if name == "apply_patch":
        return cleaned[:200] or ("patch applied" if passed else "patch failed")
    if name in ("run_tests", "verify_fix"):
        tail = _tail_markers(cleaned, ("TEST_STATUS", "TEST_BODY", "TEST_OK", "STATUS", "BODY", "OK"))
        return tail[:200] if tail else ("passed" if passed else "failed")
    if name == "run_build":
        return cleaned[:200] or ("syntax check ok" if passed else "build failed")
    if name == "health_check":
        for line in cleaned_lines:
            if line.strip().startswith("HEALTH"):
                return line.strip()[:200]
        return cleaned[:200] or ("health ok" if passed else "health failed")
    return cleaned[:200]


def _tail_markers(text: str, markers: tuple[str, ...]) -> str:
    lines = [l for l in text.splitlines() if l.strip()]
    picked: list[str] = []
    seen: set[str] = set()
    for line in lines:
        for m in markers:
            if line.strip().startswith(m) and m not in seen:
                picked.append(line.strip())
                seen.add(m)
    return " | ".join(picked)


orchestrator = Orchestrator()
