"""GitHub REST client (httpx).

Wraps the GitHub API for repository/branch/file/commit/PR/checks operations.
Never modifies ``main`` directly — repair work happens on a dedicated branch.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

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
    ) -> None:
        self.base_url = (base_url or settings.GITHUB_API_BASE_URL).rstrip("/")
        self.token = token if token is not None else settings.GITHUB_TOKEN
        self.owner = settings.GITHUB_OWNER
        self.repo = settings.GITHUB_REPO
        self.default_branch = settings.GITHUB_DEFAULT_BRANCH

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(self, method: str, path: str, **kwargs) -> dict | list:
        if not self.token:
            raise GitHubError("GITHUB_TOKEN is not configured")
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.request(method, url, headers=self._headers, **kwargs)
        if resp.status_code >= 400:
            raise GitHubError(
                f"GitHub API {method} {path} -> {resp.status_code}: {resp.text[:400]}"
            )
        return resp.json()

    def _repo_path(self, *parts: str) -> str:
        seg = "/".join(parts).strip("/")
        return f"/repos/{self.owner}/{self.repo}/{seg}"

    # ------------------------------------------------------------------
    async def get_repo(self) -> dict:
        return await self._request("GET", self._repo_path())  # type: ignore[return-value]

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
        await self._request("POST", "/repos/" + self.owner + "/" + self.repo + "/git/refs", json=payload)
        return branch

    async def create_commit(
        self, branch: str, message: str, changes: list[dict[str, str]]
    ) -> str:
        """Create a commit on ``branch`` from a list of ``{path, content}`` changes.

        Uses the low-level git data API so multiple files commit atomically.
        Returns the new commit sha.
        """
        base_sha = await self.get_branch_sha(branch)
        repo = self.owner + "/" + self.repo

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
            "base_tree": base_sha,
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
                "parents": [base_sha],
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
