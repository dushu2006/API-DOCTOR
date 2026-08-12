"""Tests for the GitHub client and service (HTTP mocked)."""

from __future__ import annotations

import re

import pytest

from app.github.client import GitHubClient, GitHubError
from app.github.service import GitHubService
from app.projects.models import Project


def _github_client(**overrides) -> GitHubClient:
    """Build a client with explicit project-scoped test credentials."""
    config = {
        "token": "test-token",
        "owner": "acme",
        "repo": "demo",
        "default_branch": "main",
    }
    config.update(overrides)
    return GitHubClient(**config)


async def test_verify_credentials(httpx_mock):
    client = _github_client()
    httpx_mock.add_response(
        url="https://api.github.com/user", method="GET",
        json={"login": "octocat", "id": 1, "name": "The Octocat"},
    )
    info = await client.verify_credentials()
    assert info["verified"] is True
    assert info["login"] == "octocat"


async def test_list_accessible_repositories_uses_account_endpoint_and_paginates(httpx_mock):
    client = _github_client()
    first_page = [
        {
            "full_name": f"acme/repo-{index}",
            "owner": {"login": "acme"},
            "name": f"repo-{index}",
            "private": False,
        }
        for index in range(100)
    ]
    httpx_mock.add_response(
        url=re.compile(r"^https://api\.github\.com/user/repos(?:\?.*)?$"),
        method="GET",
        json=first_page,
    )
    httpx_mock.add_response(
        url=re.compile(r"^https://api\.github\.com/user/repos(?:\?.*)?$"),
        method="GET",
        json=[
            {
                "full_name": "octo/private-repo",
                "owner": {"login": "octo"},
                "name": "private-repo",
                "private": True,
                "default_branch": "trunk",
            }
        ],
    )

    repos = await client.list_accessible_repositories()

    assert len(repos) == 101
    assert repos[-1] == {
        "full_name": "octo/private-repo",
        "owner": "octo",
        "name": "private-repo",
        "private": True,
        "default_branch": "trunk",
        "description": "",
        "html_url": "",
    }
    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    assert requests[0].url.params["page"] == "1"
    assert requests[1].url.params["page"] == "2"
    assert requests[0].url.params["affiliation"] == "owner,collaborator,organization_member"


async def test_get_repo(httpx_mock):
    client = _github_client()
    httpx_mock.add_response(
        url=re.compile(r"^https://api\.github\.com/repos/acme/demo/?$"), method="GET",
        json={"name": "demo", "default_branch": "main"},
    )
    repo = await client.get_repo()
    assert repo["name"] == "demo"


async def test_create_branch(httpx_mock):
    client = _github_client()
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
    client = _github_client()
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/branches?per_page=100", method="GET",
        json=[{"name": "main"}, {"name": "dev"}],
    )
    branches = await client.list_branches()
    assert branches == ["main", "dev"]


async def test_read_file(httpx_mock):
    import base64

    client = _github_client()
    content = base64.b64encode(b"def foo():\n    pass").decode()
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/contents/app/x.py?ref=main",
        method="GET", json={"content": content},
    )
    text = await client.read_file("app/x.py", ref="main")
    assert "def foo" in text


async def test_missing_token_raises():
    client = _github_client(token="")
    with pytest.raises(GitHubError):
        await client.verify_credentials()


async def test_api_error_raises(httpx_mock):
    client = _github_client()
    httpx_mock.add_response(
        url=re.compile(r"^https://api\.github\.com/repos/acme/demo/?$"), method="GET", status_code=404, json={}
    )
    with pytest.raises(GitHubError):
        await client.get_repo()


async def test_service_repair_creates_pr(httpx_mock):
    client = _github_client()
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
    # branch HEAD for commit base: commit SHA (parent) + nested tree SHA
    # (base_tree in the git/trees call MUST be a tree object, not a commit).
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/branches/api-doctor/fix/inc1", method="GET",
        json={"commit": {"sha": "base", "commit": {"tree": {"sha": "base-tree"}}}},
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
    client = _github_client()
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


async def test_create_commit_uses_tree_sha_for_base_tree(httpx_mock):
    """Regression: git/trees ``base_tree`` must be a tree SHA, not the commit SHA.

    Passing the commit SHA made GitHub reject the tree creation with HTTP 422
    "Invalid tree", silently breaking every repair commit.
    """
    import json

    client = _github_client()
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/branches/api-doctor/fix/inc1",
        method="GET",
        json={"commit": {"sha": "commit-sha", "commit": {"tree": {"sha": "tree-sha"}}}},
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/git/blobs", method="POST",
        json={"sha": "blob1"},
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/git/trees", method="POST",
        json={"sha": "new-tree"},
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/git/commits", method="POST",
        json={"sha": "new-commit"},
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/git/refs/heads/api-doctor/fix/inc1",
        method="PATCH", json={},
    )

    sha = await client.create_commit(
        "api-doctor/fix/inc1", "fix bug", [{"path": "app/x.py", "content": "x = 1\n"}]
    )
    assert sha == "new-commit"

    requests = httpx_mock.get_requests()
    trees_post = next(
        r for r in requests
        if r.url.path.endswith("/git/trees") and r.method == "POST"
    )
    commits_post = next(
        r for r in requests
        if r.url.path.endswith("/git/commits") and r.method == "POST"
    )
    trees_body = json.loads(trees_post.content)
    commits_body = json.loads(commits_post.content)

    # base_tree must reference the tree object, not the commit.
    assert trees_body["base_tree"] == "tree-sha"
    assert trees_body["base_tree"] != "commit-sha"
    # the new commit's parent is the branch HEAD commit.
    assert commits_body["parents"] == ["commit-sha"]


async def test_create_commit_recovers_tree_sha_when_branch_payload_stripped(httpx_mock):
    """If the branch response omits the nested tree object, fall back to the
    commit object endpoint to recover the tree SHA instead of failing."""
    import json

    client = _github_client()
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/branches/api-doctor/fix/inc1",
        method="GET", json={"commit": {"sha": "commit-sha"}},  # no nested tree
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/git/commits/commit-sha",
        method="GET", json={"sha": "commit-sha", "tree": {"sha": "tree-sha"}},
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/git/blobs", method="POST",
        json={"sha": "blob1"},
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/git/trees", method="POST",
        json={"sha": "new-tree"},
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/git/commits", method="POST",
        json={"sha": "new-commit"},
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/acme/demo/git/refs/heads/api-doctor/fix/inc1",
        method="PATCH", json={},
    )

    await client.create_commit(
        "api-doctor/fix/inc1", "fix bug", [{"path": "app/x.py", "content": "x = 1\n"}]
    )

    trees_post = next(
        r for r in httpx_mock.get_requests()
        if r.url.path.endswith("/git/trees") and r.method == "POST"
    )
    assert json.loads(trees_post.content)["base_tree"] == "tree-sha"
