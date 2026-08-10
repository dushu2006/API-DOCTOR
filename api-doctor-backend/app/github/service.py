"""Higher-level GitHub workflow (branch -> commit -> PR)."""

from __future__ import annotations

import logging
from typing import Any

from app.github.client import GitHubClient
from app.projects.models import Project

logger = logging.getLogger(__name__)


class GitHubService:
    def __init__(self, client: GitHubClient | None = None) -> None:
        self.client = client or GitHubClient()

    def _branch_name(self, incident_id: str) -> str:
        return f"api-doctor/fix/{incident_id}"

    async def repair(
        self,
        incident_id: str,
        changes: list[dict[str, str]],
        message: str,
        title: str,
        body: str,
        project: Project,
    ) -> dict[str, Any]:
        """Create a repair branch off the project's default branch, commit the
        changed files and open a pull request. ``main`` is never modified."""
        branch = self._branch_name(incident_id)

        # Idempotent: reuse existing PR/branch if present.
        existing = await self.client.list_pull_requests(head=branch, state="open")
        if existing:
            pr = existing[0]
            logger.info("Reusing existing PR #%s for incident %s", pr["number"], incident_id)
            return self._pr_payload(pr, branch)

        # Ensure the base branch exists; branch off the project default branch.
        base = project.github_branch or self.client.default_branch
        branches = await self.client.list_branches()
        if branch not in branches:
            await self.client.create_branch(branch, base)

        await self.client.create_commit(branch, message, changes)
        pr = await self.client.create_pull_request(head=branch, title=title, body=body, base=base)
        logger.info("Created PR #%s for incident %s", pr["number"], incident_id)
        return self._pr_payload(pr, branch)

    async def pr_status(self, incident_id: str, pr_info: dict | None) -> dict[str, Any]:
        if not pr_info or not pr_info.get("number"):
            return {"present": False}
        number = pr_info["number"]
        pr = await self.client.get_pull_request(number)
        head_sha = pr["head"]["sha"]
        checks = await self.client.get_commit_checks(head_sha)
        return {
            "present": True,
            "pr_number": number,
            "pr_url": pr.get("html_url"),
            "branch": pr.get("head", {}).get("ref"),
            "status": pr.get("state"),
            "merged": pr.get("merged"),
            "checks": checks,
        }

    @staticmethod
    def _pr_payload(pr: dict, branch: str) -> dict[str, Any]:
        return {
            "present": True,
            "pr_number": pr.get("number"),
            "pr_url": pr.get("html_url"),
            "branch": branch,
            "status": pr.get("state"),
            "merged": pr.get("merged", False),
            "head_sha": pr.get("head", {}).get("sha"),
        }
