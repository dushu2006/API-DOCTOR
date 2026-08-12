"""Central workflow engine.

Drives: detect/ingest -> create incident -> collect context -> retrieve relevant code
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
import logging
import time
from pathlib import Path
from typing import Any

from app.agent.fix_agent import FixAgent, FixProposal
from app.agent.root_cause_agent import RootCauseAgent, RootCauseAnalysis
from app.context_builder.context_builder import ContextBuilder
from app.core.config import settings
from app.core.logging_config import log_operation
from app.detector.failure_detector import FailureDetector
from app.events.hub import emit
from app.incidents.models import Incident, IncidentStatus
from app.incidents.store import incident_store
from app.projects.store import project_store
from app.sandbox.sandbox_runner import SandboxResult, SandboxRunner
from app.security.sanitizer import redact_text, sanitize

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self) -> None:
        self.detector = FailureDetector()
        self.context_builder = ContextBuilder()
        self.root_cause_agent = RootCauseAgent()
        self.fix_agent = FixAgent()
        self.sandbox_runner = SandboxRunner()
        self._pipeline_tasks: dict[str, asyncio.Task[Incident | None]] = {}

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------
    async def detect_and_create(
        self,
        endpoint: str,
        method: str = "GET",
        payload: dict | None = None,
        headers: dict[str, str] | None = None,
        project_id: str = "default",
    ) -> Incident:
        detection = await self.detector.trigger_diagnosis(endpoint, method, payload, headers)
        incident = Incident(
            project_id=project_id,
            status=IncidentStatus.DETECTED,
            detection=detection,
            request_snapshot=detection.get("request_snapshot", {}),
            stack_trace=detection.get("stack_trace", ""),
        )
        incident_store.create(incident)
        incident.add_activity("error_detected", "done", f"HTTP {detection.get('status_code')} on {method} {endpoint}")
        incident_store.update(incident)
        log_operation(logger, incident.id, "detect", "ok", error=str(detection.get("error_message") or "")[:200])
        await emit(incident.id, "error_detected", "done", f"{method} {endpoint}")
        return incident

    async def ingest_incident(
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
        request_snapshot: dict | None = None,
    ) -> Incident:
        """Create an incident from external log ingestion (Render, CI, manual)."""
        safe_raw_logs = redact_text(raw_logs or "")
        safe_trace = redact_text(stack_trace or safe_raw_logs or message)
        safe_message = redact_text(
            message or (safe_trace.splitlines()[-1] if safe_trace else "Incident detected from logs")
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

        incident = Incident(
            project_id=project_id,
            status=IncidentStatus.RECEIVED,
            detection=detection,
            request_snapshot=safe_request_snapshot,
            stack_trace=safe_trace,
        )
        incident_store.create(incident)
        incident.add_activity("logs_retrieved", "done", "Logs retrieved")
        incident.add_activity("error_detected", "done", "Error detected")
        incident_store.update(incident)

        log_operation(logger, incident.id, "ingest", "ok", error=safe_message[:200])
        await emit(incident.id, "logs_retrieved", "done", "Logs retrieved")
        await emit(incident.id, "error_detected", "done", "Error detected")
        return incident

    def start_diagnosis(self, incident_id: str) -> bool:
        """Start one background pipeline for an incident."""
        inc = incident_store.get(incident_id)
        if not inc:
            return False

        existing = self._pipeline_tasks.get(incident_id)
        if existing and not existing.done():
            return False

        retryable_states = {
            IncidentStatus.RECEIVED,
            IncidentStatus.DETECTED,
            IncidentStatus.FAILED,
            IncidentStatus.REQUIRES_HUMAN_REVIEW,
            IncidentStatus.PR_READY,
            IncidentStatus.INVESTIGATION_FAILED,
            IncidentStatus.FIX_GENERATION_FAILED,
            IncidentStatus.VERIFICATION_FAILED,
            IncidentStatus.REPAIR_LIMIT_REACHED,
            IncidentStatus.CANCELLED,
            # Interactive workflow pause points - can be resumed
            IncidentStatus.AWAITING_FILE_READ_APPROVAL,
            IncidentStatus.AWAITING_FIX_APPROVAL,
        }
        if inc.status not in retryable_states:
            return False

        task = asyncio.create_task(
            self.run_pipeline(incident_id),
            name=f"api-doctor-pipeline-{incident_id}",
        )
        self._pipeline_tasks[incident_id] = task
        task.add_done_callback(
            lambda completed, iid=incident_id: self._pipeline_finished(iid, completed)
        )
        return True

    def _pipeline_finished(
        self, incident_id: str, task: asyncio.Task[Incident | None]
    ) -> None:
        if self._pipeline_tasks.get(incident_id) is task:
            self._pipeline_tasks.pop(incident_id, None)
        try:
            task.result()
        except asyncio.CancelledError:
            logger.info("Diagnosis pipeline cancelled for incident %s", incident_id)
        except Exception:
            logger.exception("Unhandled diagnosis task failure for %s", incident_id)

    async def cancel_diagnosis(self, incident_id: str) -> bool:
        """Cancel an active pipeline and persist an explicit terminal state."""
        task = self._pipeline_tasks.get(incident_id)
        if not task or task.done():
            return False

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        inc = incident_store.get(incident_id)
        if not inc:
            return False
        inc.status = IncidentStatus.CANCELLED
        inc.error_message = "Diagnosis cancelled by user"
        inc.add_activity("pipeline", "cancelled", inc.error_message)
        incident_store.update(inc)
        await emit(incident_id, "pipeline", "cancelled", inc.error_message)
        return True

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------
    async def run_pipeline(self, incident_id: str) -> Incident | None:
        inc = incident_store.get(incident_id)
        if not inc:
            logger.error("Incident %s not found", incident_id)
            return None

        # Determine the project and workspace
        project = project_store.get(inc.project_id) or project_store.get_current()
        if project and project.workspace_path and Path(project.workspace_path).is_dir():
            workspace_path = project.workspace_path
        elif settings.DEMO_MODE:
            workspace_path = settings.INTERNAL_REPO_ROOT
        else:
            raise RuntimeError("No synchronized workspace is available for the selected project.")
        profile = project.profile if project else None

        self.context_builder.set_repo_root(workspace_path)
        self.sandbox_runner.set_repo_root(workspace_path, profile)

        t_start = time.perf_counter()
        try:
            await emit(inc.id, "pipeline", "running", "Starting diagnosis pipeline")
            if project and project.is_connected:
                inc.add_activity("repository_connected", "done", "Repository connected")
                await emit(inc.id, "repository_connected", "done", "Repository connected")
                inc.add_activity("repository_synced", "done", "Project synchronized")
                await emit(inc.id, "repository_synced", "done", "Project synchronized")
                if profile:
                    inc.add_activity("project_discovered", "done", "Project discovered")
                    await emit(inc.id, "project_discovered", "done", "Project discovered")

            # Context collection (may pause for file read approval)
            await self._collect_context(inc, profile)
            if inc.status == IncidentStatus.AWAITING_FILE_READ_APPROVAL:
                # Paused for approval - return and wait
                await emit(inc.id, "pipeline", "paused", "Waiting for file read approval")
                return inc

            # Investigation (may pause for fix approval)
            await self._investigate(inc, profile)
            if inc.status == IncidentStatus.AWAITING_FIX_APPROVAL:
                # Paused for approval - return and wait
                await emit(inc.id, "pipeline", "paused", "Waiting for fix approval")
                return inc

            if inc.status in (
                IncidentStatus.FAILED,
                IncidentStatus.INVESTIGATION_FAILED,
                IncidentStatus.FIX_GENERATION_FAILED,
                IncidentStatus.REQUIRES_HUMAN_REVIEW,
            ):
                await emit(inc.id, "pipeline", "failed", inc.error_message or "investigation failed")
                return inc

            await self._sandbox_and_verify(inc, profile)
            await emit(inc.id, "pipeline", "done", f"status={inc.status}")
        except Exception as exc:  # noqa: BLE001
            inc.error_message = f"{type(exc).__name__}: {exc}"
            if inc.status not in (
                IncidentStatus.FAILED,
                IncidentStatus.INVESTIGATION_FAILED,
                IncidentStatus.FIX_GENERATION_FAILED,
                IncidentStatus.VERIFICATION_FAILED,
                IncidentStatus.REPAIR_LIMIT_REACHED,
            ):
                inc.status = IncidentStatus.VERIFICATION_FAILED
            inc.add_activity("pipeline_error", "failed", str(exc))
            log_operation(logger, incident_id, "pipeline", "failed", error=str(exc))
            await emit(incident_id, "pipeline_error", "failed", str(exc)[:500])
        finally:
            incident_store.update(inc)
            log_operation(
                logger, incident_id, "pipeline", "done",
                duration=time.perf_counter() - t_start,
                error=inc.error_message,
            )
        return inc

    # ------------------------------------------------------------------
    async def _collect_context(self, inc: Incident, profile: Any = None) -> None:
        inc.status = IncidentStatus.COLLECTING_CONTEXT
        inc.add_activity("collecting_context", "running")
        incident_store.update(inc)
        await emit(inc.id, "collecting_context", "running", "Parsing stack trace and retrieving relevant code")
        t0 = time.perf_counter()
        try:
            try:
                context = self.context_builder.build(inc, project_profile=profile)
            except TypeError:
                context = self.context_builder.build(inc)
            inc.context = context
            inc.add_activity("logs_retrieved", "done", "Logs retrieved")
            inc.add_activity("stack_trace_parsed", "done", "Stack trace extracted")
            inc.add_activity("relevant_source_identified", "done", f"{len(context['affected_files'])} files")
            
            # Pause for file read approval - show user which files will be read
            affected_files = context.get("affected_files", [])
            if affected_files:
                file_list = "\n".join(f"  - {f}" for f in affected_files)
                inc.add_activity("files_to_read", "pending", f"{len(affected_files)} files identified for reading")
                inc.add_activity("file_read_approval", "pending", f"Files to read:\n{file_list}")
                inc.status = IncidentStatus.AWAITING_FILE_READ_APPROVAL
                incident_store.update(inc)
                await emit(inc.id, "file_read_approval", "pending", f"Approval needed: {len(affected_files)} files")
                # Don't auto-continue - wait for user approval
                return
            
            # If no files to read, continue as before
            for f in affected_files:
                inc.add_activity("file_read", "done", f"Reading {f}")
                await emit(inc.id, "file_read", "done", f"Reading {f}")
            inc.set_activity("collecting_context", "done", f"{len(context['affected_files'])} files")
            log_operation(logger, inc.id, "collect_context", "ok", duration=time.perf_counter() - t0)
            await emit(inc.id, "stack_trace_parsed", "done", f"{len(context['affected_files'])} files")
            await emit(inc.id, "relevant_source_identified", "done", f"{len(context['affected_files'])} files")
            await emit(inc.id, "collecting_context", "done", f"{len(context['affected_files'])} files")
        except Exception as exc:
            inc.status = IncidentStatus.INVESTIGATION_FAILED
            inc.error_message = f"context build failed: {exc}"
            inc.set_activity("collecting_context", "failed", str(exc)[:200])
            log_operation(logger, inc.id, "collect_context", "failed", error=str(exc))
            await emit(inc.id, "collecting_context", "failed", str(exc)[:500])
            raise
        finally:
            incident_store.update(inc)

    async def _investigate(self, inc: Incident, profile: Any = None) -> None:
        inc.status = IncidentStatus.INVESTIGATING
        inc.add_activity("investigation_started", "running")
        inc.add_activity("investigating", "running")
        incident_store.update(inc)
        await emit(inc.id, "investigation_started", "running", "Investigating root cause")
        await emit(inc.id, "investigating", "running", "Investigating root cause")
        t0 = time.perf_counter()
        try:
            analysis: RootCauseAnalysis = await self.root_cause_agent.analyze(inc.context or {})
            inc.root_cause = analysis.model_dump()
            if analysis.confidence < settings.MIN_ROOT_CAUSE_CONFIDENCE:
                inc.status = IncidentStatus.INVESTIGATION_FAILED
                inc.error_message = (
                    f"Low confidence ({analysis.confidence:.2f} < "
                    f"{settings.MIN_ROOT_CAUSE_CONFIDENCE}): {analysis.reason}"
                )
                inc.add_activity("root_cause_identified", "failed", inc.error_message)
                inc.set_activity("investigating", "failed", inc.error_message[:200])
                log_operation(logger, inc.id, "root_cause", "failed", duration=time.perf_counter() - t0, error=inc.error_message)
                await emit(inc.id, "investigating", "failed", inc.error_message)
                return

            inc.status = IncidentStatus.ROOT_CAUSE_FOUND
            inc.add_activity("root_cause_identified", "done", "Root cause identified")
            inc.set_activity("investigating", "done", "Root cause identified")
            log_operation(logger, inc.id, "root_cause", "ok", duration=time.perf_counter() - t0, error=f"confidence={analysis.confidence:.2f}")
            await emit(inc.id, "root_cause_identified", "done", "Root cause identified")
            await emit(inc.id, "investigating", "done", "Root cause identified")
        except Exception as exc:
            inc.status = IncidentStatus.INVESTIGATION_FAILED
            inc.error_message = f"root cause analysis failed: {exc}"
            inc.add_activity("root_cause_identified", "failed", str(exc))
            inc.set_activity("investigating", "failed", str(exc)[:200])
            log_operation(logger, inc.id, "root_cause", "failed", error=str(exc))
            await emit(inc.id, "investigating", "failed", str(exc)[:500])
            raise
        finally:
            incident_store.update(inc)

        if inc.status in (IncidentStatus.FAILED, IncidentStatus.REQUIRES_HUMAN_REVIEW, IncidentStatus.INVESTIGATION_FAILED):
            return

        # Fix generation
        inc.status = IncidentStatus.FIX_PLANNED
        inc.add_activity("fix_generated", "running")
        incident_store.update(inc)
        await emit(inc.id, "fix_generated", "running", "Generating fix")
        t0 = time.perf_counter()
        files = self._full_files(inc)
        try:
            try:
                proposal: FixProposal = await self.fix_agent.generate_fix(
                    analysis, files, project_profile=profile
                )
            except TypeError:
                proposal = await self.fix_agent.generate_fix(analysis, files)
            inc.fix_proposal = proposal.model_dump()
            inc.set_activity("fix_generated", "done", proposal.summary)
            log_operation(logger, inc.id, "fix_generation", "ok", duration=time.perf_counter() - t0)
            await emit(inc.id, "fix_generated", "done", proposal.summary)
            
            # Pause for fix approval - show user the proposed fix before sandbox testing
            if proposal and proposal.diff:
                inc.status = IncidentStatus.AWAITING_FIX_APPROVAL
                inc.add_activity("fix_approval", "pending", f"Fix proposed: {proposal.summary}")
                inc.add_activity("diff_ready", "pending", f"Files to change: {', '.join(proposal.files_changed or [])}")
                incident_store.update(inc)
                await emit(inc.id, "fix_approval", "pending", "Approval needed: review proposed fix")
                # Don't auto-continue to sandbox - wait for user approval
                return
        except Exception as exc:
            inc.status = IncidentStatus.FIX_GENERATION_FAILED
            inc.error_message = f"fix generation failed: {exc}"
            inc.set_activity("fix_generated", "failed", str(exc)[:200])
            log_operation(logger, inc.id, "fix_generation", "failed", error=str(exc))
            await emit(inc.id, "fix_generated", "failed", str(exc)[:500])
        finally:
            incident_store.update(inc)

    async def _sandbox_and_verify(self, inc: Incident, profile: Any = None) -> None:
        proposal_data = inc.fix_proposal
        if not proposal_data:
            return
        proposal = FixProposal.model_validate(proposal_data)
        analysis = (
            RootCauseAnalysis.model_validate(inc.root_cause)
            if inc.root_cause else None
        )
        files = self._full_files(inc)

        inc.status = IncidentStatus.SANDBOX_TESTING
        inc.add_activity("sandbox_started", "running")
        inc.add_activity("tests_started", "running")
        incident_store.update(inc)
        await emit(inc.id, "sandbox_started", "running", "Running sandbox")
        await emit(inc.id, "tests_started", "running", "Running tests")

        attempt = 0
        result: SandboxResult | None = None
        while attempt < max(1, settings.MAX_REPAIR_ATTEMPTS):
            attempt += 1
            inc.attempt_count = attempt
            inc.set_activity("sandbox_started", "running", f"attempt {attempt}")
            incident_store.update(inc)
            await emit(inc.id, "sandbox_started", "running", f"attempt {attempt}")
            t0 = time.perf_counter()
            try:
                result = await asyncio.to_thread(
                    self.sandbox_runner.run_verification, proposal, inc.request_snapshot
                )
            except Exception as exc:
                inc.status = IncidentStatus.VERIFICATION_FAILED
                inc.error_message = f"sandbox error: {exc}"
                inc.set_activity("sandbox_started", "failed", str(exc)[:200])
                log_operation(logger, inc.id, "sandbox", "failed", error=str(exc))
                incident_store.update(inc)
                await emit(inc.id, "sandbox_started", "failed", str(exc)[:500])
                return

            log_operation(
                logger, inc.id, "sandbox_attempt", "ok" if result.passed else "failed",
                duration=time.perf_counter() - t0,
                error="" if result.passed else result.error,
            )

            if result.passed:
                break
            if attempt < settings.MAX_REPAIR_ATTEMPTS:
                inc.set_activity("fix_generated", "running", f"attempt {attempt} failed — regenerating")
                incident_store.update(inc)
                await emit(inc.id, "fix_generated", "running", f"Attempt {attempt} failed, retrying")
                try:
                    if analysis:
                        proposal = await self.fix_agent.generate_fix(
                            analysis, files, project_profile=profile, feedback=result.logs[-3000:] or result.error
                        )
                        inc.fix_proposal = proposal.model_dump()
                except Exception:
                    break

        inc.sandbox_result = result.model_dump() if result else {"passed": False, "error": "no result"}

        if result and result.passed:
            inc.status = IncidentStatus.FIX_VERIFIED
            inc.set_activity("sandbox_started", "done")
            inc.set_activity("tests_started", "done", "tests passed")
            inc.add_activity("test_passed", "done", "all sandbox steps passed")
            for step in result.steps:
                inc.add_activity(step.name, "done" if step.passed else "failed", _summarize_step(step))
            inc.add_activity("fix_verified", "done")
            await emit(inc.id, "test_passed", "done", "Sandbox tests passed")
            await emit(inc.id, "sandbox_started", "done", "Verification passed")
            await emit(inc.id, "fix_verified", "done", "Fix verified")
        else:
            inc.status = IncidentStatus.REPAIR_LIMIT_REACHED if attempt >= settings.MAX_REPAIR_ATTEMPTS else IncidentStatus.VERIFICATION_FAILED
            inc.error_message = result.error if result else "verification failed"
            inc.set_activity("sandbox_started", "failed", inc.error_message[:200])
            inc.set_activity("tests_started", "failed", inc.error_message[:200])
            inc.add_activity("fix_verified", "failed", inc.error_message[:200])
            await emit(inc.id, "fix_verified", "failed", inc.error_message[:500])
        incident_store.update(inc)

        # PR Gate
        if inc.status == IncidentStatus.FIX_VERIFIED and settings.AUTO_CREATE_PR:
            try:
                await self.create_pull_request(inc.id)
            except Exception as exc:  # noqa: BLE001
                inc.error_message = f"PR creation failed: {exc}"
                incident_store.update(inc)
                await emit(inc.id, "pr_created", "failed", str(exc)[:500])

    # ------------------------------------------------------------------
    # Resume from approval pause points
    # ------------------------------------------------------------------
    async def resume_file_read(self, incident_id: str) -> bool:
        """Resume pipeline after user approves file read."""
        inc = incident_store.get(incident_id)
        if not inc:
            logger.error("Incident %s not found", incident_id)
            return False
        if inc.status != IncidentStatus.AWAITING_FILE_READ_APPROVAL:
            logger.warning("Incident %s not in AWAITING_FILE_READ_APPROVAL state", incident_id)
            return False
        
        # Now actually read the files and continue
        inc.status = IncidentStatus.COLLECTING_CONTEXT
        inc.add_activity("file_read_approval", "done", "User approved file reading")
        incident_store.update(inc)
        await emit(inc.id, "file_read_approval", "done", "File read approved")
        
        # Rebuild context to actually read files
        try:
            context = self.context_builder.build(inc)
            inc.context = context
            for f in context.get("affected_files", []):
                inc.add_activity("file_read", "done", f"Reading {f}")
                await emit(inc.id, "file_read", "done", f"Reading {f}")
            inc.set_activity("collecting_context", "done", f"{len(context['affected_files'])} files")
            log_operation(logger, inc.id, "collect_context", "ok", duration=0)
            await emit(inc.id, "collecting_context", "done", f"{len(context['affected_files'])} files")
        except Exception as exc:
            inc.status = IncidentStatus.INVESTIGATION_FAILED
            inc.error_message = f"context build failed: {exc}"
            incident_store.update(inc)
            return False
        
        incident_store.update(inc)
        return True

    async def resume_fix(self, incident_id: str) -> bool:
        """Resume pipeline after user approves fix."""
        inc = incident_store.get(incident_id)
        if not inc:
            logger.error("Incident %s not found", incident_id)
            return False
        if inc.status != IncidentStatus.AWAITING_FIX_APPROVAL:
            logger.warning("Incident %s not in AWAITING_FIX_APPROVAL state", incident_id)
            return False
        
        inc.add_activity("fix_approval", "done", "User approved fix")
        incident_store.update(inc)
        await emit(inc.id, "fix_approval", "done", "Fix approved")
        return True

    # ------------------------------------------------------------------
    # GitHub PR
    # ------------------------------------------------------------------
    def _full_files(self, inc: Incident) -> dict[str, str]:
        """Read full content of affected files from workspace."""
        files: dict[str, str] = {}
        affected = (inc.root_cause or {}).get("affected_files") or []
        for rel in affected:
            full = self.sandbox_runner.repo_root / rel
            if full.is_file():
                files[rel] = full.read_text(encoding="utf-8", errors="replace")
        if not files and inc.context and inc.context.get("code_snippets"):
            for rel, data in inc.context["code_snippets"].items():
                if isinstance(data, dict):
                    files[rel] = data.get("content", "")[:4000]
        return files

    async def create_pull_request(self, incident_id: str) -> dict[str, Any]:
        from app.github.client import GitHubClient
        from app.github.service import GitHubService

        inc = incident_store.get(incident_id)
        if not inc:
            raise ValueError(f"incident not found: {incident_id}")
        if not inc.fix_proposal or inc.fix_proposal.get("diff") is None:
            raise ValueError("incident has no verified fix to open a PR for")

        # Check Repair Gate: must be verified
        if inc.status not in (IncidentStatus.FIX_VERIFIED, IncidentStatus.PR_READY):
            if not (inc.sandbox_result and inc.sandbox_result.get("passed")):
                raise ValueError("Cannot create PR: fix has not passed sandbox verification gates.")

        project = project_store.get(inc.project_id) or project_store.get_current()
        github = project_store.resolve_github(project.id if project else None)
        gh_client = GitHubClient(
            token=github.get("token", ""),
            owner=github.get("owner", ""),
            repo=github.get("repo", ""),
            default_branch=github.get("branch", "main"),
        )
        service = GitHubService(gh_client)

        diff = inc.fix_proposal["diff"]
        changes = self._changes_from_diff(diff)
        summary = inc.fix_proposal.get("summary") or "Fix"
        title = f"fix(api-doctor): {summary}"
        body = self._pr_body(inc)

        branch_name = f"api-doctor/fix/{incident_id}"
        await emit(inc.id, "branch_created", "done", branch_name)
        inc.add_activity("branch_created", "done", branch_name)

        pr_info = await service.repair(
            incident_id=incident_id,
            changes=changes,
            message=f"fix: {summary}\n\napi-doctor incident {incident_id}",
            title=title,
            body=body,
            project=project,
        )

        await emit(inc.id, "commit_created", "done", pr_info.get("head_sha", ""))
        inc.add_activity("commit_created", "done", pr_info.get("head_sha", ""))

        inc.pr_info = pr_info
        inc.status = IncidentStatus.PR_CREATED
        inc.add_activity("pr_created", "done", pr_info.get("pr_url") or "")
        incident_store.update(inc)
        await emit(inc.id, "pr_created", "done", pr_info.get("pr_url") or "")
        return pr_info

    async def pr_status(self, incident_id: str) -> dict[str, Any]:
        from app.github.client import GitHubClient
        from app.github.service import GitHubService

        inc = incident_store.get(incident_id)
        if not inc:
            return {"present": False, "error": "incident not found"}

        project = project_store.get(inc.project_id) or project_store.get_current()
        github = project_store.resolve_github(project.id if project else None)
        gh_client = GitHubClient(
            token=github.get("token", ""),
            owner=github.get("owner", ""),
            repo=github.get("repo", ""),
            default_branch=github.get("branch", "main"),
        )
        service = GitHubService(gh_client)
        return await service.pr_status(incident_id, inc.pr_info)

    def _changes_from_diff(self, diff: str) -> list[dict[str, str]]:
        from app.sandbox.workspace_manager import WorkspaceManager
        from app.sandbox.patch_utils import apply_patch

        wm = WorkspaceManager(repo_root=self.sandbox_runner.repo_root)
        ws = wm.create_workspace()
        try:
            affected = apply_patch(diff, ws)
            changes = []
            for rel in affected:
                content = wm.read_relative(ws, rel)
                if content is not None:
                    changes.append({"path": rel, "content": content})
            return changes
        finally:
            wm.cleanup(ws)

    def _pr_body(self, inc: Incident) -> str:
        rc = inc.root_cause or {}
        fix = inc.fix_proposal or {}
        lines = [
            f"## API Doctor — Incident `{inc.id}`",
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
