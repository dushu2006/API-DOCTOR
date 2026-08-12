"""Central workflow engine.

Drives: detect -> create incident -> collect context -> retrieve relevant code
-> root cause analysis -> fix generation -> sandbox (reproduce/patch/tests/
verify) -> GitHub PR. It contains no provider-specific implementation details —
it composes the service/client classes.

Guarantees:
    * never modifies production directly,
    * never auto-merges,
    * bounded repair attempts,
    * secrets are never sent to the LLM or exposed to the frontend.

Latency / streaming improvements:
- Emits progress events to the SSE hub so dashboard shows live "working..."
- Uses trimmed context (project-relevant frames only) for faster AI calls
"""

from __future__ import annotations

import asyncio
import logging
import time
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
from app.sandbox.sandbox_runner import SandboxResult, SandboxRunner

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self) -> None:
        self.detector = FailureDetector()
        self.context_builder = ContextBuilder()
        self.root_cause_agent = RootCauseAgent()
        self.fix_agent = FixAgent()
        self.sandbox_runner = SandboxRunner()
        # The registry closes the small gap between accepting a diagnosis
        # request and the background coroutine advancing the incident status.
        # Without it, two requests in the same event-loop tick can launch two
        # pipelines that mutate the same Incident instance concurrently.
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

    def start_diagnosis(self, incident_id: str) -> bool:
        """Start one background pipeline for an incident.

        Returns ``False`` when a pipeline is already active or the incident is
        in a completed state. Failed and cancelled incidents may be retried.
        """
        inc = incident_store.get(incident_id)
        if not inc:
            return False

        existing = self._pipeline_tasks.get(incident_id)
        if existing and not existing.done():
            return False

        retryable_states = {
            IncidentStatus.DETECTED,
            IncidentStatus.INVESTIGATION_FAILED,
            IncidentStatus.FIX_GENERATION_FAILED,
            IncidentStatus.VERIFICATION_FAILED,
            IncidentStatus.REPAIR_LIMIT_REACHED,
            IncidentStatus.CANCELLED,
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
            # ``run_pipeline`` normally records its own errors. This protects
            # against an exception outside that boundary and consumes the task
            # result so asyncio does not emit an unhandled-task warning.
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

        t_start = time.perf_counter()
        try:
            await emit(inc.id, "pipeline", "running", "Starting diagnosis pipeline")
            await self._collect_context(inc)
            await self._investigate(inc)
            if inc.status in (
                IncidentStatus.INVESTIGATION_FAILED,
                IncidentStatus.FIX_GENERATION_FAILED,
            ):
                await emit(inc.id, "pipeline", "failed", inc.error_message or "investigation failed")
                return inc
            await self._sandbox_and_verify(inc)
            await emit(inc.id, "pipeline", "done", f"status={inc.status}")
        except Exception as exc:  # noqa: BLE001
            inc.error_message = f"{type(exc).__name__}: {exc}"
            if inc.status not in (
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
    async def _collect_context(self, inc: Incident) -> None:
        inc.status = IncidentStatus.COLLECTING_CONTEXT
        inc.add_activity("collecting_context", "running")
        incident_store.update(inc)
        await emit(inc.id, "collecting_context", "running", "Parsing stack trace and retrieving code")
        t0 = time.perf_counter()
        try:
            context = self.context_builder.build(inc)
            inc.context = context
            inc.add_activity("logs_retrieved", "done")
            inc.add_activity("stack_trace_parsed", "done")
            inc.add_activity("relevant_source_identified", "done", f"{len(context['affected_files'])} files")
            inc.set_activity("collecting_context", "done", f"{len(context['affected_files'])} files")
            log_operation(logger, inc.id, "collect_context", "ok", duration=time.perf_counter() - t0)
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

    async def _investigate(self, inc: Incident) -> None:
        inc.status = IncidentStatus.INVESTIGATING
        inc.add_activity("investigating", "running")
        incident_store.update(inc)
        await emit(inc.id, "investigating", "running", "Analyzing root cause with LLM")
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
            inc.add_activity("root_cause_identified", "done", analysis.category)
            inc.set_activity("investigating", "done", f"{analysis.category} conf={analysis.confidence:.2f}")
            log_operation(logger, inc.id, "root_cause", "ok", duration=time.perf_counter() - t0, error=f"confidence={analysis.confidence:.2f}")
            await emit(inc.id, "investigating", "done", f"{analysis.category} conf={analysis.confidence:.2f}")
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

        if inc.status == IncidentStatus.INVESTIGATION_FAILED:
            return

        # Fix generation.
        inc.status = IncidentStatus.FIX_PLANNED
        inc.add_activity("fix_generated", "running")
        incident_store.update(inc)
        await emit(inc.id, "fix_generated", "running", "Generating minimal patch")
        t0 = time.perf_counter()
        files = self._full_files(inc)
        try:
            proposal: FixProposal = await self.fix_agent.generate_fix(
                analysis, files
            )
            inc.fix_proposal = proposal.model_dump()
            inc.set_activity("fix_generated", "done", proposal.summary)
            log_operation(logger, inc.id, "fix_generation", "ok", duration=time.perf_counter() - t0)
            await emit(inc.id, "fix_generated", "done", proposal.summary)
        except Exception as exc:
            inc.status = IncidentStatus.FIX_GENERATION_FAILED
            inc.error_message = f"fix generation failed: {exc}"
            inc.set_activity("fix_generated", "failed", str(exc)[:200])
            log_operation(logger, inc.id, "fix_generation", "failed", error=str(exc))
            await emit(inc.id, "fix_generated", "failed", str(exc)[:500])
        finally:
            incident_store.update(inc)

    async def _sandbox_and_verify(self, inc: Incident) -> None:
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
        incident_store.update(inc)
        await emit(inc.id, "sandbox_started", "running", "Running verification in sandbox")

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
                # run_verification performs blocking subprocess calls — run it
                # on a worker thread so the status endpoint stays responsive.
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
                # Regenerate the fix with the failure feedback.
                inc.set_activity("fix_generated", "running", f"attempt {attempt} failed — regenerating")
                incident_store.update(inc)
                await emit(inc.id, "fix_generated", "running", f"Attempt {attempt} failed, retrying")
                try:
                    if analysis:
                        proposal = await self.fix_agent.generate_fix(
                            analysis, files, feedback=result.logs[-3000:] or result.error
                        )
                        inc.fix_proposal = proposal.model_dump()
                except Exception:
                    break

        inc.sandbox_result = result.model_dump() if result else {"passed": False, "error": "no result"}

        if result and result.passed:
            inc.status = IncidentStatus.FIX_VERIFIED
            inc.set_activity("sandbox_started", "done")
            for step in result.steps:
                inc.add_activity(step.name, "done" if step.passed else "failed", _summarize_step(step))
            inc.add_activity("fix_verified", "done")
            await emit(inc.id, "sandbox_started", "done", "Verification passed")
            await emit(inc.id, "fix_verified", "done", "Fix verified")
        else:
            inc.status = IncidentStatus.REPAIR_LIMIT_REACHED if attempt >= settings.MAX_REPAIR_ATTEMPTS else IncidentStatus.VERIFICATION_FAILED
            inc.error_message = result.error if result else "verification failed"
            inc.set_activity("sandbox_started", "failed", inc.error_message[:200])
            inc.add_activity("fix_verified", "failed", inc.error_message[:200])
            await emit(inc.id, "fix_verified", "failed", inc.error_message[:500])
        incident_store.update(inc)

        # Auto-create PR only if configured.
        if inc.status == IncidentStatus.FIX_VERIFIED and settings.AUTO_CREATE_PR:
            try:
                await self.create_pull_request(inc.id)
            except Exception as exc:  # noqa: BLE001
                inc.error_message = f"PR creation failed: {exc}"
                incident_store.update(inc)
                await emit(inc.id, "pull_request_created", "failed", str(exc)[:500])

    # ------------------------------------------------------------------
    # GitHub PR
    # ------------------------------------------------------------------
    def _full_files(self, inc: Incident) -> dict[str, str]:
        """Read full content of affected files for the fix agent."""
        files: dict[str, str] = {}
        affected = (inc.root_cause or {}).get("affected_files") or []
        for rel in affected:
            full = self.sandbox_runner.repo_root / rel
            if full.is_file():
                files[rel] = full.read_text(encoding="utf-8", errors="replace")
        if not files and inc.context and inc.context.get("code_snippets"):
            # Fall back to snippet content (trimmed) so the agent still has input.
            for rel, data in inc.context["code_snippets"].items():
                if isinstance(data, dict):
                    files[rel] = data.get("content", "")[:4000]
        return files

    async def create_pull_request(self, incident_id: str) -> dict[str, Any]:
        from app.github.client import GitHubClient
        from app.github.service import GitHubService
        from app.projects.store import project_store

        inc = incident_store.get(incident_id)
        if not inc:
            raise ValueError(f"incident not found: {incident_id}")
        if not inc.fix_proposal or inc.fix_proposal.get("diff") is None:
            raise ValueError("incident has no verified fix to open a PR for")

        project = project_store.get(inc.project_id)
        service = GitHubService(GitHubClient())

        diff = inc.fix_proposal["diff"]
        changes = self._changes_from_diff(diff)
        summary = inc.fix_proposal.get("summary") or "Fix"
        title = f"fix(api-doctor): {summary}"
        body = self._pr_body(inc)

        pr_info = await service.repair(
            incident_id=incident_id,
            changes=changes,
            message=f"fix: {summary}\n\napi-doctor incident {incident_id}",
            title=title,
            body=body,
            project=project,
        )
        inc.pr_info = pr_info
        inc.status = IncidentStatus.PR_CREATED
        inc.add_activity("pull_request_created", "done", pr_info.get("pr_url") or "")
        incident_store.update(inc)
        await emit(inc.id, "pull_request_created", "done", pr_info.get("pr_url") or "")
        return pr_info

    async def pr_status(self, incident_id: str) -> dict[str, Any]:
        from app.github.client import GitHubClient
        from app.github.service import GitHubService

        inc = incident_store.get(incident_id)
        if not inc:
            return {"present": False, "error": "incident not found"}
        service = GitHubService(GitHubClient())
        return await service.pr_status(incident_id, inc.pr_info)

    def _changes_from_diff(self, diff: str) -> list[dict[str, str]]:
        """Split a multi-file unified diff into per-file {path, content} changes.

        Applies the diff to a throwaway workspace copy and reads back the
        resulting file contents (accurate even for new files).
        """
        from app.sandbox.workspace_manager import WorkspaceManager
        from app.sandbox.patch_utils import apply_patch

        wm = WorkspaceManager()
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
            f"**Category:** {rc.get('category')}",
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
            "> Generated automatically. Please review before merging.",
        ]
        return "\n".join(lines)


def _summarize_step(step: Any) -> str:
    """Produce a short, human-friendly summary for a sandbox step's activity
    message. Strips parent JSON log lines so consumers don't see raw
    ``SANDBOX_MODE=local ...`` noise mixed into the step detail."""
    name = getattr(step, "name", "")
    passed = bool(getattr(step, "passed", False))
    detail = (getattr(step, "detail", "") or "").strip()
    if not detail:
        return "ok" if passed else "failed"

    # Drop structured JSON log lines (one per line) coming from sandboxed
    # subprocess stdout/stderr — they start with '{' and contain "timestamp".
    cleaned_lines: list[str] = []
    for line in detail.splitlines():
        s = line.strip()
        if s.startswith("{") and "\"timestamp\"" in s:
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines).strip()

    # For steps that print known markers, pick the human-readable tail.
    if name == "reproduce_failure":
        # Keep just the exception type/message line if present.
        for line in reversed(cleaned_lines):
            s = line.strip()
            if s.startswith("AttributeError") or s.startswith("TypeError") or s.startswith("ValueError") or s.startswith("Error"):
                return s[:200]
        # Fall back to status/body/ok tail.
        tail = _tail_markers(cleaned, ("STATUS", "BODY", "OK"))
        return tail[:200] if tail else ("reproduced 5xx" if passed else "did not reproduce failure")
    if name == "apply_patch":
        return cleaned[:200] or ("patch applied" if passed else "patch failed")
    if name in ("run_tests", "verify_fix"):
        tail = _tail_markers(cleaned, ("TEST_STATUS", "TEST_BODY", "TEST_OK", "STATUS", "BODY", "OK"))
        return tail[:200] if tail else ("passed" if passed else "failed")
    if name == "run_build":
        return cleaned[:200] or ("compileall ok" if passed else "build failed")
    if name == "health_check":
        for line in cleaned_lines:
            if line.strip().startswith("HEALTH"):
                return line.strip()[:200]
        return cleaned[:200] or ("health ok" if passed else "health failed")
    return cleaned[:200]


def _tail_markers(text: str, markers: tuple[str, ...]) -> str:
    """Return a compact string made of the last line matching each marker."""
    lines = [l for l in text.splitlines() if l.strip()]
    picked: list[str] = []
    seen: set[str] = set()
    for line in lines:
        for m in markers:
            if line.strip().startswith(m) and m not in seen:
                picked.append(line.strip())
                seen.add(m)
    return " | ".join(picked)


# Singleton for import convenience / background task wiring.
orchestrator = Orchestrator()
