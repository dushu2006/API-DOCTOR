"""GitHub REST client (httpx).

Wraps the GitHub API for repository/branch/file/commit/PR/checks operations.
Never modifies ``main`` directly — repair work happens on a dedicated branch.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import certifi
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class GitHubError(Exception):
    pass


class GitHubClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        owner: str | None = None,
        repo: str | None = None,
        default_branch: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.GITHUB_API_BASE_URL).rstrip("/")
        self.token = token or ""
        self.owner = owner or ""
        self.repo = repo or ""
        self.default_branch = default_branch or "main"

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _request(self, method: str, path: str, **kwargs) -> dict | list:
        # Account-scoped endpoints are meaningful only for an authenticated user.
        # Repository metadata may remain publicly readable without a token.
        if not self.token and (path == "/user" or path.startswith("/user/")):
            raise GitHubError("GitHub token is required for this operation")
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS, verify=certifi.where()) as client:
                resp = await client.request(method, url, headers=self._headers, **kwargs)
        except httpx.ConnectError as exc:
            if 'CERTIFICATE_VERIFY_FAILED' not in str(exc):
                raise
            logger.warning('GitHub API SSL verification failed; retrying without certificate validation for %s %s', method, path)
            async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS, verify=False) as client:  # noqa: S501
                resp = await client.request(method, url, headers=self._headers, **kwargs)
        if resp.status_code >= 400:
            raise GitHubError(
                f"GitHub API {method} {path} -> {resp.status_code}: {resp.text[:400]}"
            )
        if not resp.content:
            return {}
        return resp.json()

    def _repo_path(self, *parts: str) -> str:
        seg = "/".join(parts).strip("/")
        return f"/repos/{self.owner}/{self.repo}/{seg}" if seg else f"/repos/{self.owner}/{self.repo}"

    # ------------------------------------------------------------------
    # Verification & Metadata
    # ------------------------------------------------------------------
    def validate_config(self) -> dict[str, Any]:
        """Validate if GitHub configuration variables are present."""
        return {
            "configured": bool(self.owner and self.repo),
            "owner": self.owner,
            "repo": self.repo,
            "has_token": bool(self.token),
            "default_branch": self.default_branch,
        }

    async def verify_credentials(self) -> dict[str, Any]:
        """Validate the configured token against GET /user. Does not clone a repo."""
        if not self.token:
            raise GitHubError("GITHUB_TOKEN is not configured")
        data = await self._request("GET", "/user")
        if not isinstance(data, dict):
            raise GitHubError("GitHub /user returned an unexpected payload")
        return {
            "verified": True,
            "login": data.get("login"),
            "id": data.get("id"),
            "name": data.get("name"),
        }

    async def verify_access(self) -> dict[str, Any]:
        """Verify repository access and retrieve repository metadata."""
        if not self.owner or not self.repo:
            raise GitHubError("GITHUB_OWNER and GITHUB_REPO must be set")
        data = await self.get_repo()
        return {
            "verified": True,
            "owner": self.owner,
            "repo": self.repo,
            "default_branch": data.get("default_branch") or self.default_branch,
            "name": data.get("name"),
            "full_name": data.get("full_name"),
            "description": data.get("description"),
            "private": data.get("private", False),
            "html_url": data.get("html_url"),
        }

    async def get_repo(self) -> dict:
        return await self._request("GET", self._repo_path())  # type: ignore[return-value]

    async def list_accessible_repositories(self) -> list[dict[str, Any]]:
        """List repositories available to the authenticated account.

        This intentionally uses GitHub's account-scoped ``GET /user/repos``
        endpoint instead of the configured repository path. It powers project
        onboarding, where there is no selected repository yet.
        """
        if not self.token:
            raise GitHubError("GitHub token is required for this operation")

        repositories: list[dict[str, Any]] = []
        page = 1
        while True:
            data = await self._request(
                "GET",
                "/user/repos",
                params={
                    "per_page": 100,
                    "page": page,
                    "sort": "updated",
                    "affiliation": "owner,collaborator,organization_member",
                },
            )
            if not isinstance(data, list):
                raise GitHubError("GitHub /user/repos returned an unexpected payload")

            for repository in data:
                if not isinstance(repository, dict):
                    continue
                owner = repository.get("owner") if isinstance(repository.get("owner"), dict) else {}
                repositories.append(
                    {
                        "full_name": repository.get("full_name") or "",
                        "owner": owner.get("login") or "",
                        "name": repository.get("name") or "",
                        "private": bool(repository.get("private", False)),
                        "default_branch": repository.get("default_branch") or "main",
                        "description": repository.get("description") or "",
                        "html_url": repository.get("html_url") or "",
                    }
                )

            if len(data) < 100:
                break
            page += 1

        return repositories

    async def get_branch_sha(self, branch: str | None = None) -> str:
        branch = branch or self.default_branch
        data = await self._request("GET", self._repo_path("branches", branch))
        return data["commit"]["sha"]  # type: ignore[index]

    async def list_branches(self) -> list[str]:
        data = await self._request("GET", self._repo_path("branches") + "?per_page=100")
        return [b["name"] for b in data]  # type: ignore[union-attr]

    async def read_file(self, path: str, ref: str | None = None) -> str:
        qs = f"?ref={ref}" if ref else ""
        data = await self._request("GET", self._repo_path("contents", path) + qs)
        content = data["content"]  # type: ignore[index]
        return base64.b64decode(content).decode("utf-8", errors="replace")

    async def create_branch(self, branch: str, base_branch: str | None = None) -> str:
        base_branch = base_branch or self.default_branch
        sha = await self.get_branch_sha(base_branch)
        payload = {"ref": f"refs/heads/{branch}", "sha": sha}
        await self._request("POST", f"/repos/{self.owner}/{self.repo}/git/refs", json=payload)
        return branch

    async def create_commit(
        self, branch: str, message: str, changes: list[dict[str, str]]
    ) -> str:
        """Create a commit on ``branch`` from a list of ``{path, content}`` changes.

        Uses the low-level git data API so multiple files commit atomically.
        Returns the new commit sha.
        """
        # Resolve the branch HEAD once and pull both the commit SHA (the new
        # commit's parent) AND its tree SHA. ``base_tree`` below MUST reference a
        # tree object — passing the commit SHA here made GitHub reject the tree
        # creation with HTTP 422 "Invalid tree", which broke every repair commit.
        branch_info = await self._request("GET", self._repo_path("branches", branch))
        base_commit_sha = branch_info["commit"]["sha"]
        base_tree_sha = (
            branch_info.get("commit", {}).get("commit", {}).get("tree", {}).get("sha")
        )
        if not base_tree_sha:
            # Some proxies/mock responses strip the nested tree object; recover
            # it from the commit object itself rather than failing the commit.
            commit_obj = await self._request(
                "GET", f"/repos/{self.owner}/{self.repo}/git/commits/{base_commit_sha}"
            )
            base_tree_sha = commit_obj["tree"]["sha"]

        repo = f"{self.owner}/{self.repo}"

        blobs = {}
        for change in changes:
            path = change["path"]
            content = change["content"]
            data = await self._request(
                "POST", f"/repos/{repo}/git/blobs",
                json={"content": content, "encoding": "utf-8"},
            )
            blobs[path] = data["sha"]

        tree_payload = {
            "base_tree": base_tree_sha,
            "tree": [
                {"path": path, "mode": "100644", "type": "blob", "sha": sha}
                for path, sha in blobs.items()
            ],
        }
        tree = await self._request("POST", f"/repos/{repo}/git/trees", json=tree_payload)
        tree_sha = tree["sha"]

        commit = await self._request(
            "POST", f"/repos/{repo}/git/commits",
            json={
                "message": message,
                "tree": tree_sha,
                "parents": [base_commit_sha],
            },
        )
        commit_sha = commit["sha"]
        await self._request(
            "PATCH", f"/repos/{repo}/git/refs/heads/{branch}",
            json={"sha": commit_sha, "force": False},
        )
        return commit_sha

    async def create_pull_request(
        self, head: str, title: str, body: str, base: str | None = None
    ) -> dict:
        payload = {
            "title": title,
            "head": head,
            "base": base or self.default_branch,
            "body": body,
            "maintainer_can_modify": True,
        }
        data = await self._request(
            "POST", f"/repos/{self.owner}/{self.repo}/pulls", json=payload
        )
        return data  # type: ignore[return-value]

    async def get_pull_request(self, number: int) -> dict:
        data = await self._request("GET", f"/repos/{self.owner}/{self.repo}/pulls/{number}")
        return data  # type: ignore[return-value]

    async def list_pull_requests(self, head: str, state: str = "open") -> list[dict]:
        data = await self._request(
            "GET",
            f"/repos/{self.owner}/{self.repo}/pulls?state={state}&head={self.owner}:{head}",
        )
        return data  # type: ignore[return-value]

    async def get_commit_checks(self, sha: str) -> dict[str, Any]:
        try:
            data = await self._request(
                "GET", f"/repos/{self.owner}/{self.repo}/commits/{sha}/check-runs"
            )
            runs = data.get("check_runs", [])
        except GitHubError:
            runs = []
        return {"total": len(runs), "success": sum(1 for r in runs if r.get("conclusion") == "success"), "runs": runs}
