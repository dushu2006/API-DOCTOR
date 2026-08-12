"""Tests for the GitHub client and service (HTTP mocked)."""

from __future__ import annotations

import re

import pytest

from app.github.client import GitHubClient, GitHubError
from app.github.service import GitHubService
from app.projects.models import Project


async def test_get_repo(httpx_mock):
    client = GitHubClient()
    httpx_mock.add_response(
        url=re.compile(r"^https://api\.github\.com/repos/acme/demo/?$"), method="GET",
        json={"name": "demo", "default_branch": "main"},
    )
    repo = await client.get_repo()
    assert repo["name"] == "demo"


async def test_create_branch(httpx_mock):
    client = GitHubClient()
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/branches/main", method="GET",
        json={"commit": {"sha": "abc123"}},
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/git/refs", method="POST",
        json={"ref": "refs/heads/api-doctor/fix/inc1", "sha": "abc123"},
    )
    branch = await client.create_branch("api-doctor/fix/inc1", "main")
    assert branch == "api-doctor/fix/inc1"


async def test_list_branches(httpx_mock):
    client = GitHubClient()
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/branches?per_page=100", method="GET",
        json=[{"name": "main"}, {"name": "dev"}],
    )
    branches = await client.list_branches()
    assert branches == ["main", "dev"]


async def test_read_file(httpx_mock):
    import base64

    client = GitHubClient()
    content = base64.b64encode(b"def foo():\n    pass").decode()
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/contents/app/x.py?ref=main",
        method="GET", json={"content": content},
    )
    text = await client.read_file("app/x.py", ref="main")
    assert "def foo" in text


async def test_missing_token_raises():
    client = GitHubClient(token="")
    with pytest.raises(GitHubError):
        await client.get_repo()


async def test_api_error_raises(httpx_mock):
    client = GitHubClient()
    httpx_mock.add_response(
        url=re.compile(r"^https://api\.github\.com/repos/acme/demo/?$"), method="GET", status_code=404, json={}
    )
    with pytest.raises(GitHubError):
        await client.get_repo()


async def test_service_repair_creates_pr(httpx_mock):
    client = GitHubClient()
    service = GitHubService(client)

    # list open PRs for branch -> none
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/pulls?state=open&head=acme:api-doctor/fix/inc1",
        method="GET", json=[],
    )
    # list branches
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/branches?per_page=100", method="GET",
        json=[{"name": "main"}],
    )
    # branch sha
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/branches/main", method="GET",
        json={"commit": {"sha": "base"}},
    )
    # create ref
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/git/refs", method="POST",
        json={"ref": "refs/heads/api-doctor/fix/inc1"},
    )
    # blob
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/git/blobs", method="POST",
        json={"sha": "blob1"},
    )
    # branch sha again for commit base
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/branches/api-doctor/fix/inc1", method="GET",
        json={"commit": {"sha": "base"}},
    )
    # tree
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/git/trees", method="POST",
        json={"sha": "tree1"},
    )
    # commit
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/git/commits", method="POST",
        json={"sha": "commit1"},
    )
    # update ref
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/git/refs/heads/api-doctor/fix/inc1",
        method="PATCH", json={},
    )
    # create PR
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/pulls", method="POST",
        json={"number": 7, "html_url": "https://github.com/acme/demo/pull/7", "state": "open", "head": {"sha": "commit1"}},
    )

    project = Project(id="default", github_owner="acme", github_repo="demo", github_branch="main")
    info = await service.repair(
        incident_id="inc1",
        changes=[{"path": "app/x.py", "content": "def foo():\n    return 2\n"}],
        message="fix", title="Fix", body="body", project=project,
    )
    assert info["pr_number"] == 7
    assert info["pr_url"] == "https://github.com/acme/demo/pull/7"
    assert info["branch"] == "api-doctor/fix/inc1"


async def test_service_pr_status_uses_normalized_pr_number(httpx_mock):
    client = GitHubClient()
    service = GitHubService(client)
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/pulls/7",
        method="GET",
        json={
            "number": 7,
            "html_url": "https://github.com/acme/demo/pull/7",
            "state": "open",
            "merged": False,
            "head": {"sha": "commit1", "ref": "api-doctor/fix/inc1"},
        },
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/commits/commit1/check-runs",
        method="GET",
        json={"check_runs": [{"name": "tests", "conclusion": "success"}]},
    )

    status = await service.pr_status(
        "inc1",
        {"pr_number": 7, "pr_url": "https://github.com/acme/demo/pull/7"},
    )

    assert status["present"] is True
    assert status["pr_number"] == 7
    assert status["checks"]["success"] == 1
