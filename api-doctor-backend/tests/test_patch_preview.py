"""Tests for the diff-review fallbacks and LLM-tolerant diff parsing.

Regression coverage for three review-pane failures:

* model diffs with blank context lines stripped of their leading space were
  truncated at the first blank line, silently dropping the rest of the hunk;
* a patch that no longer applies rendered as a whole red pane next to an
  empty green pane instead of showing the intended removals/additions;
* a patch whose changes are already present in the workspace showed the same
  broken pane instead of the actual before/after change set.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from app.incidents.models import Incident, IncidentStatus
from app.incidents.store import incident_store
from app.main import app
from app.orchestrator import Orchestrator
from app.projects.discovery import discover_project
from app.sandbox.patch_utils import _parse_unified_diff, apply_patch, preview_patch


# A patch for a typical Python file (blank lines between top-level defs) as a
# model really emits it: the leading space of blank context lines is gone.
_BUGGY_DB = (
    "import sqlite3\n"
    "import os\n"
    "\n"
    'DB_PATH = os.getenv("DATABASE_PATH", "hack_store.db")\n'
    "\n"
    "# allow override via env\n"
    "\n"
    "\n"
    "def init_db():\n"
    "    conn = sqlite3.connect(DB_PATH, check_same_thread=False)\n"
    "    conn.row_factory = sqlite3.Row\n"
    "    cur = conn.cursor()\n"
)

_GET_CONN_DIFF = (
    "--- a/db.py\n"
    "+++ b/db.py\n"
    "@@ -5,11 +5,16 @@\n"
    " # allow override via env\n"
    "\n"
    "\n"
    "+def get_conn():\n"
    "+    conn = sqlite3.connect(DB_PATH, check_same_thread=False)\n"
    "+    conn.row_factory = sqlite3.Row\n"
    "+    return conn\n"
    "+\n"
    "+\n"
    " def init_db():\n"
    "-    conn = sqlite3.connect(DB_PATH, check_same_thread=False)\n"
    "-    conn.row_factory = sqlite3.Row\n"
    "+    conn = get_conn()\n"
    "     cur = conn.cursor()\n"
)

_FIXED_DB = (
    "import sqlite3\n"
    "import os\n"
    "\n"
    'DB_PATH = os.getenv("DATABASE_PATH", "hack_store.db")\n'
    "\n"
    "# allow override via env\n"
    "\n"
    "\n"
    "def get_conn():\n"
    "    conn = sqlite3.connect(DB_PATH, check_same_thread=False)\n"
    "    conn.row_factory = sqlite3.Row\n"
    "    return conn\n"
    "\n"
    "\n"
    "def init_db():\n"
    "    conn = get_conn()\n"
    "    cur = conn.cursor()\n"
)


# ---------------------------------------------------------------------------
# Parsing: bare blank lines inside a hunk are empty context (like GNU patch)
# ---------------------------------------------------------------------------
def test_parse_absorbs_stripped_blank_context_lines():
    patches = _parse_unified_diff(_GET_CONN_DIFF)
    hunk_lines = patches[0]["hunks"][0]["lines"]
    # Previously the hunk ended at the first bare blank line (1 context line);
    # every addition/removal after it was silently dropped.
    assert len(hunk_lines) == 14
    assert "+def get_conn():" in hunk_lines
    assert "+    conn = get_conn()" in hunk_lines


def test_apply_patch_with_stripped_blank_context_lines(tmp_path):
    (tmp_path / "db.py").write_text(_BUGGY_DB)
    affected = apply_patch(_GET_CONN_DIFF, tmp_path)
    assert affected == ["db.py"]
    assert (tmp_path / "db.py").read_text() == _FIXED_DB


def test_blank_line_run_still_separates_file_sections(tmp_path):
    diff = (
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old_a\n"
        "+new_a\n"
        "\n"
        "--- a/b.py\n"
        "+++ b/b.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old_b\n"
        "+new_b\n"
    )
    (tmp_path / "a.py").write_text("old_a\n")
    (tmp_path / "b.py").write_text("old_b\n")
    assert apply_patch(diff, tmp_path) == ["a.py", "b.py"]
    assert (tmp_path / "a.py").read_text() == "new_a\n"
    assert (tmp_path / "b.py").read_text() == "new_b\n"


def test_trailing_blank_lines_are_not_absorbed(tmp_path):
    diff = "--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-old_a\n+new_a\n\n\n"
    (tmp_path / "a.py").write_text("old_a\n")
    assert apply_patch(diff, tmp_path) == ["a.py"]
    assert (tmp_path / "a.py").read_text() == "new_a\n"


# ---------------------------------------------------------------------------
# Preview: readable before/after even when the patch no longer applies
# ---------------------------------------------------------------------------
def test_preview_reconstructs_prefix_state_when_patch_already_present(tmp_path):
    """The fix is already in the file: show the real before/after change set.

    The red side is the reconstructed pre-fix content, the green side is the
    current file, and no error banner pretends the patch is broken.
    """
    (tmp_path / "db.py").write_text(_FIXED_DB)
    [entry] = preview_patch(_GET_CONN_DIFF, tmp_path)
    assert entry["error"] is None
    assert entry["proposed"] == _FIXED_DB
    assert entry["original"] == _BUGGY_DB


def test_preview_stale_patch_still_shows_intended_changes(tmp_path):
    """The file drifted since diagnosis: best-effort preview keeps red/green.

    The green side is no longer empty; removals land on the slotted lines and
    additions are inserted, while the error banner still warns the patch is
    stale.
    """
    drifted = _BUGGY_DB.replace("cur = conn.cursor()", "cursor = conn.cursor()")
    (tmp_path / "db.py").write_text(drifted)
    [entry] = preview_patch(_GET_CONN_DIFF, tmp_path)
    assert entry["error"] is not None
    assert "mismatch" in entry["error"]
    assert entry["original"] == drifted
    assert entry["proposed"]  # not the empty whole-red pane anymore
    assert "def get_conn():" in entry["proposed"]
    assert "    conn = get_conn()" in entry["proposed"]
    # The drifted line survived: it was only context to the patch.
    assert "    cursor = conn.cursor()" in entry["proposed"]


def test_preview_deleted_file_keeps_empty_green_side(tmp_path):
    diff = (
        "--- a/a.py\n"
        "+++ /dev/null\n"
        "@@ -1,1 +0,0 @@\n"
        "-old_a\n"
    )
    (tmp_path / "a.py").write_text("old_a\n")
    [entry] = preview_patch(diff, tmp_path)
    assert entry["error"] is None
    assert entry["proposed"] == ""


# ---------------------------------------------------------------------------
# Orchestrator: a pure patch mismatch must not blame a workspace change
# ---------------------------------------------------------------------------
def _mismatched_incident(project_id: str, file_contents: dict[str, str]) -> Incident:
    inc = Incident(
        project_id=project_id,
        status=IncidentStatus.AWAITING_FIX_APPROVAL,
        stack_trace="Traceback ...",
        fix_proposal={
            "summary": "unrelated patch",
            "files_changed": ["app/services/payment.py"],
            # Context does not exist anywhere in the workspace file.
            "diff": (
                "--- a/app/services/payment.py\n"
                "+++ b/app/services/payment.py\n"
                "@@ -1,3 +1,3 @@\n"
                " def totally_unrelated_function():\n"
                "-    return 'spanish inquisition'\n"
                "+    return 'fixed'\n"
            ),
            "reason": "bad generation",
            "risk": "low",
        },
    )
    inc.context = {
        "incident_id": inc.id,
        "stack_trace": inc.stack_trace,
        "affected_files": ["app/services/payment.py"],
        "code_snippets": {},
        "file_contents": file_contents,
        "_complete": True,
    }
    return incident_store.create(inc)


async def test_pure_patch_mismatch_does_not_claim_workspace_changed(
    tmp_path, authenticated_user, project_factory
):
    user, _ = authenticated_user
    ws = tmp_path / "org" / "payments-api"
    (ws / "app" / "services").mkdir(parents=True)
    current = "def process_payment(user):\n    return user.payment_method.token\n"
    target = ws / "app" / "services" / "payment.py"
    target.write_text(current)
    project_factory(project_id="pp-mismatch", workspace_path=str(ws), profile=discover_project(ws))

    orch = Orchestrator()
    # The workspace still matches the diagnosis snapshot exactly.
    inc = _mismatched_incident("pp-mismatch", {"app/services/payment.py": current})

    outcome = await orch.stage_workspace_apply(inc.id)

    assert outcome["applied"] is False
    assert outcome["conflict"] == "patch_mismatch"
    assert outcome["stale_files"] == []
    assert "File changed since diagnosis" not in outcome["reason"]
    assert "does not match the current file" in outcome["reason"]
    # The refusal never touched the workspace.
    assert target.read_text() == current


# ---------------------------------------------------------------------------
# API: the diff endpoint never serves an empty green pane again
# ---------------------------------------------------------------------------
async def test_diff_endpoint_returns_renderable_preview_for_stale_patch(
    tmp_path, authenticated_user, project_factory, auth_headers
):
    user, _ = authenticated_user
    ws = tmp_path / "org" / "hack-store"
    ws.mkdir(parents=True)
    (ws / "db.py").write_text(_FIXED_DB)  # fix already present in the workspace
    project_factory(project_id="pv-proj", workspace_path=str(ws), profile=discover_project(ws))

    inc = incident_store.create(Incident(
        project_id="pv-proj",
        status=IncidentStatus.AWAITING_FIX_APPROVAL,
        stack_trace="NameError: get_conn not defined",
        fix_proposal={
            "summary": "Fix NameError: get_conn not defined in db.py module scope",
            "files_changed": ["db.py"],
            "diff": _GET_CONN_DIFF,
            "reason": "missing helper",
            "risk": "low",
        },
    ))

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/incidents/{inc.id}/diff", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["present"] is True
    [file_preview] = payload["files"]
    assert file_preview["path"] == "db.py"
    # The already-present fix renders as a normal before/after diff pane:
    # buggy pre-image on the red side, current fixed file on the green side.
    assert file_preview["error"] is None
    assert file_preview["original"] == _BUGGY_DB
    assert file_preview["proposed"] == _FIXED_DB
