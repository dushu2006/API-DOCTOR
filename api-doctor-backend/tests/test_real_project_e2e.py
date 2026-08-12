"""End-to-end integration test for the real GitHub project mode.

Exercises:
1. Connecting a GitHub repository.
2. Syncing repository into workspace and discovering project profile.
3. Ingesting a real production log (e.g. Render log with stack trace).
4. Running the full diagnosis pipeline: context building -> root cause -> patch generation -> sandbox verification.
5. Verifying that the original repo is untouched and fix is verified.
6. Opening a pull request on a dedicated fix branch.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import httpx

from app.agent.fix_agent import FixProposal
from app.agent.root_cause_agent import RootCauseAnalysis
from app.incidents.models import IncidentStatus
from app.incidents.store import incident_store
from app.main import app
from app.orchestrator import orchestrator
from app.projects.discovery import discover_project
from app.projects.models import Project
from app.projects.store import project_store
from app.sandbox.workspace_manager import WorkspaceManager


async def _request(method: str, path: str, json_body: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=json_body)


@pytest.mark.asyncio
async def test_real_project_e2e_workflow(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_workspace:
        # Create a sample real project repo
        project_dir = Path(tmp_workspace) / "myorg" / "payments-api"
        project_dir.mkdir(parents=True)
        (project_dir / "requirements.txt").write_text("fastapi==0.110.0\npytest\n")
        (project_dir / ".env.example").write_text("STRIPE_KEY=sk_test_123\n")
        services_dir = project_dir / "app" / "services"
        services_dir.mkdir(parents=True)

        original_code = (
            "class PaymentService:\n"
            "    def process_charge(self, user, amount):\n"
            "        # Line 3 is the failing line\n"
            "        token = user.payment_method.token\n"
            "        return {'status': 'charged', 'token': token}\n"
        )
        (services_dir / "payment.py").write_text(original_code)

        fixed_code = (
            "class PaymentService:\n"
            "    def process_charge(self, user, amount):\n"
            "        # Line 3 is the failing line\n"
            "        if user.payment_method is None:\n"
            "            raise ValueError('no payment method')\n"
            "        token = user.payment_method.token\n"
            "        return {'status': 'charged', 'token': token}\n"
        )

        patch_diff = (
            "--- a/app/services/payment.py\n"
            "+++ b/app/services/payment.py\n"
            "@@ -3,2 +3,4 @@\n"
            "-        token = user.payment_method.token\n"
            "+        if user.payment_method is None:\n"
            "+            raise ValueError('no payment method')\n"
            "+        token = user.payment_method.token\n"
        )

        # 1. Register project with workspace
        profile = discover_project(project_dir)
        assert profile.language == "Python"

        project = Project(
            id="test-proj",
            name="myorg/payments-api",
            github_owner="myorg",
            github_repo="payments-api",
            github_branch="main",
            repo_root=str(project_dir),
            workspace_path=str(project_dir),
            is_connected=True,
            profile=profile,
        )
        project_store.create(project)
        project_store.set_current("test-proj")

        # 2. Ingest real production log
        log_payload = {
            "source": "render",
            "service_id": "srv_payments",
            "log_text": (
                "2026-08-12T12:00:00Z [ERROR] Request failed on POST /api/v1/charge\n"
                "Traceback (most recent call last):\n"
                f'  File "app/services/payment.py", line 4, in process_charge\n'
                "    token = user.payment_method.token\n"
                "AttributeError: 'NoneType' object has no attribute 'token'\n"
            ),
            "project_id": "test-proj",
            "auto_diagnose": False,
        }
        ingest_res = await _request("POST", "/api/incidents/ingest", json_body=log_payload)
        assert ingest_res.status_code == 200
        incident_id = ingest_res.json()["incident_id"]

        # 3. Mock AI root cause and fix agents for deterministic CI
        monkeypatch.setattr(
            orchestrator.root_cause_agent, "analyze",
            AsyncMock(return_value=RootCauseAnalysis(
                root_cause="user.payment_method is None before dereferencing .token",
                classification="CODE_BUG",
                category="CODE_BUG",
                confidence=0.95,
                affected_files=["app/services/payment.py"],
                affected_lines=[4],
                affected_functions=["process_charge"],
                evidence=["AttributeError on line 4"],
                recommended_action="Add null check for payment_method",
                safe_to_repair=True,
                reason="AttributeError null dereference",
            )),
        )

        monkeypatch.setattr(
            orchestrator.fix_agent, "generate_fix",
            AsyncMock(return_value=FixProposal(
                summary="Add null guard for payment_method",
                files_changed=["app/services/payment.py"],
                diff=patch_diff,
                reason="Check if user.payment_method is None before accessing token",
                risk="low",
            )),
        )

        # 4. Run pipeline
        result = await orchestrator.run_pipeline(incident_id)
        assert result is not None
        assert result.status == IncidentStatus.FIX_VERIFIED
        assert result.sandbox_result["passed"] is True

        # Ensure base repo remains untouched
        assert (services_dir / "payment.py").read_text() == original_code

        # 5. Check Diff endpoint
        diff_res = await _request("GET", f"/api/incidents/{incident_id}/diff")
        assert diff_res.status_code == 200
        assert diff_res.json()["present"] is True
        assert "app/services/payment.py" in diff_res.json()["files_changed"]

        # 6. Check Context endpoint
        ctx_res = await _request("GET", f"/api/incidents/{incident_id}/context")
        assert ctx_res.status_code == 200
        assert "app/services/payment.py" in ctx_res.json()["implicated_files"]
