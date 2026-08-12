"""Tests for real GitHub project mode, project discovery, workspace management,
Render log ingestion, and project file APIs.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import httpx

from app.context_builder.stack_trace_parser import parse_stack_trace
from app.detector.failure_detector import FailureDetector
from app.main import app
from app.projects.discovery import discover_project
from app.projects.models import Project, ProjectProfile
from app.projects.store import project_store
from app.sandbox.workspace_manager import WorkspaceManager


async def _request(method: str, path: str, json_body: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=json_body)


def test_project_discovery_python_fastapi():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "requirements.txt").write_text("fastapi==0.110.0\nuvicorn\npytest>=7.0.0\n")
        (root / ".env.example").write_text("PORT=8000\nDATABASE_URL=postgres://...\n")
        app_dir = root / "app"
        app_dir.mkdir()
        (app_dir / "main.py").write_text("import os\nport = os.getenv('PORT')\napp = None\n")

        profile = discover_project(root)
        assert profile.language == "Python"
        assert profile.framework == "FastAPI"
        assert profile.package_manager == "pip"
        assert profile.test_framework == "pytest"
        assert profile.test_command == "pytest"
        assert profile.entrypoint == "app/main.py"
        assert "requirements.txt" in profile.dependency_files
        assert ".env.example" in profile.configuration_files
        assert "PORT" in profile.environment_variable_references or "DATABASE_URL" in profile.environment_variable_references
        assert "app" in profile.source_directories


def test_project_discovery_node_typescript():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        pkg = {
            "name": "my-express-app",
            "dependencies": {"express": "^4.18.0"},
            "devDependencies": {"typescript": "^5.0.0", "jest": "^29.0.0"},
            "scripts": {"test": "jest", "start": "ts-node src/index.ts"},
            "main": "src/index.ts",
        }
        (root / "package.json").write_text(json.dumps(pkg))
        (root / "tsconfig.json").write_text("{}")
        src_dir = root / "src"
        src_dir.mkdir()
        (src_dir / "index.ts").write_text("const port = process.env.API_KEY;\n")

        profile = discover_project(root)
        assert profile.language == "TypeScript"
        assert profile.framework == "Express"
        assert profile.package_manager == "npm"
        assert profile.test_framework == "jest"
        assert profile.test_command == "npm test"
        assert profile.entrypoint == "src/index.ts"
        assert "package.json" in profile.dependency_files
        assert "API_KEY" in profile.environment_variable_references


def test_project_discovery_go():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "go.mod").write_text("module example.com/api\n\nrequire github.com/gin-gonic/gin v1.9.0\n")
        (root / "main.go").write_text("package main\nimport \"os\"\nfunc main() { os.Getenv(\"SECRET\") }\n")

        profile = discover_project(root)
        assert profile.language == "Go"
        assert profile.framework == "Gin"
        assert profile.package_manager == "go mod"
        assert profile.test_command == "go test ./..."
        assert profile.entrypoint == "main.go"


def test_workspace_manager_isolation():
    with tempfile.TemporaryDirectory() as base_tmp:
        repo_dir = Path(base_tmp) / "repo"
        repo_dir.mkdir()
        (repo_dir / "app").mkdir()
        (repo_dir / "app" / "service.py").write_text("def run(): pass\n")

        wm = WorkspaceManager(repo_root=repo_dir, workspace_base=base_tmp)
        files = wm.files()
        assert "app/service.py" in files

        tree = wm.file_tree()
        assert len(tree) > 0
        assert tree[0]["name"] == "app"

        # Isolated sandbox workspace copy
        sb = wm.create_workspace()
        assert (sb / "app" / "service.py").is_file()
        # Modifying sandbox copy should not affect base repo
        (sb / "app" / "service.py").write_text("def run(): modified\n")
        assert (repo_dir / "app" / "service.py").read_text() == "def run(): pass\n"
        wm.cleanup(sb)


def test_log_ingestion_groups_traceback():
    detector = FailureDetector(service="render-web")
    raw_logs = (
        "2026-08-12T10:00:00Z [INFO] Server started\n"
        "2026-08-12T10:01:00Z [INFO] Processing request /users/123/charge\n"
        "Traceback (most recent call last):\n"
        '  File "app/services/payment.py", line 121, in charge_user\n'
        "    token = user.payment_method.token\n"
        "AttributeError: 'NoneType' object has no attribute 'token'\n"
        "2026-08-12T10:02:00Z [INFO] Worker health check OK\n"
    )

    detections = detector.detect_from_logs(raw_logs, source="render")
    assert len(detections) == 1
    det = detections[0]
    assert det["status_code"] == 500
    assert "AttributeError" in det["error_message"]
    assert "payment.py" in det["stack_trace"]
    assert det["source"] == "render"


def test_log_ingestion_detects_http_errors():
    detector = FailureDetector(service="production")
    raw_logs = (
        "[2026-08-12 10:00:00] POST /api/v1/checkout HTTP 500 Internal Server Error\n"
        "[2026-08-12 10:00:05] GET /health HTTP 200 OK\n"
    )
    detections = detector.detect_from_logs(raw_logs, source="manual")
    assert len(detections) == 1
    assert detections[0]["status_code"] == 500
    assert detections[0]["endpoint"] == "/api/v1/checkout"


async def test_api_project_files_endpoint():
    res = await _request("GET", "/api/projects/files/list")
    assert res.status_code == 200
    data = res.json()
    assert "files" in data
    assert "tree" in data


async def test_api_project_file_content_endpoint():
    res = await _request("GET", "/api/projects/file-content?path=requirements.txt")
    assert res.status_code == 200
    data = res.json()
    assert "fastapi" in data["content"]


async def test_api_project_file_content_traversal_rejected():
    res = await _request("GET", "/api/projects/file-content?path=../../../../etc/passwd")
    assert res.status_code == 404


async def test_api_ingest_incident_endpoint():
    body = {
        "source": "manual",
        "log_text": "Traceback (most recent call last):\n  File \"app/test.py\", line 10, in foo\nValueError: invalid param\n",
        "message": "ValueError: invalid param",
        "auto_diagnose": False,
    }
    res = await _request("POST", "/api/incidents/ingest", json_body=body)
    assert res.status_code == 200
    data = res.json()
    assert "incident_id" in data
    assert data["status"] in ("RECEIVED", "DETECTED")


async def test_api_sync_render_unconfigured():
    res = await _request("POST", "/api/incidents/sync-render")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("unconfigured", "ok")


async def test_multilang_stack_trace_parser():
    # JavaScript stack trace
    js_trace = (
        "TypeError: Cannot read properties of undefined (reading 'token')\n"
        "    at chargeUser (/repo/src/services/payment.ts:121:20)\n"
        "    at /repo/src/routes/checkout.ts:45:10\n"
    )
    parsed_js = parse_stack_trace(js_trace, repo_root="/repo")
    assert len(parsed_js.frames) == 2
    assert parsed_js.frames[0].relative_path == "src/services/payment.ts"
    assert parsed_js.frames[0].line == 121
    assert parsed_js.frames[0].function == "chargeUser"
    assert parsed_js.exception_type == "TypeError"
