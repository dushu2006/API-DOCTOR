"""Higher-level GitHub workflow (branch -> commit -> PR)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.github.client import GitHubClient
from app.projects.models import Project
from app.projects.store import project_store
from app.sandbox.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)


class GitHubService:
    def __init__(self, client: GitHubClient) -> None:
        """Use an explicitly configured, project-scoped GitHub client."""
        self.client = client

    def _branch_name(self, incident_id: str) -> str:
        return f"api-doctor/fix/{incident_id}"

    def sync_project_workspace(self, project: Project) -> Path:
        """Synchronize the configured GitHub repository into a local working workspace."""
        wm = WorkspaceManager()
        github = project_store.resolve_github(project.id)
        owner = project.github_owner or github.get("owner") or self.client.owner
        repo = project.github_repo or github.get("repo") or self.client.repo
        branch = project.github_branch or github.get("branch") or self.client.default_branch
        token = github.get("token") or self.client.token

        if not owner or not repo:
            raise ValueError("Project must have GitHub repository configuration")

        ws_path = wm.sync_repository(
            owner=owner,
            repo=repo,
            branch=branch,
            token=token,
            base_url=self.client.base_url,
        )
        return ws_path

    async def repair(
        self,
        incident_id: str,
        changes: list[dict[str, str]],
        message: str,
        title: str,
        body: str,
        project: Project | None = None,
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
        base = (project.github_branch if project else None) or self.client.default_branch
        branches = await self.client.list_branches()
        if branch not in branches:
            await self.client.create_branch(branch, base)

        await self.client.create_commit(branch, message, changes)
        pr = await self.client.create_pull_request(head=branch, title=title, body=body, base=base)
        logger.info("Created PR #%s for incident %s", pr["number"], incident_id)
        return self._pr_payload(pr, branch)

    async def pr_status(self, incident_id: str, pr_info: dict | None) -> dict[str, Any]:
        number = (pr_info or {}).get("pr_number") or (pr_info or {}).get("number")
        if not number:
            return {"present": False}
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
