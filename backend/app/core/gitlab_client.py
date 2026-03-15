"""GitLab API client wrapper."""

import logging
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import gitlab
import httpx
from gitlab import Gitlab
from gitlab.exceptions import GitlabGetError
from gitlab.v4.objects import MergeRequest, Project

from app.config import Settings, get_effective_settings

logger = logging.getLogger(__name__)


class GitLabClient:
    """Wrapper around python-gitlab for GitLab API operations."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        """Initialize GitLab client."""
        self.settings = settings or get_effective_settings()
        self.base_url = self.settings.gitlab_url.rstrip("/")
        self.private_token = self.settings.gitlab_bot_token
        self.gl: Gitlab = gitlab.Gitlab(
            self.base_url,
            private_token=self.private_token,
        )
        logger.info(f"GitLab client initialized: {self.base_url}")

    def get_project(self, project_id: int) -> Project:
        """Get a project by ID.

        Args:
            project_id: GitLab project ID

        Returns:
            Project object
        """
        logger.info(f"Fetching project: {project_id}")
        return self.gl.projects.get(project_id)

    def get_or_create_branch(
        self, project_id: int, branch_name: str, ref: str = "main"
    ) -> dict:
        """Get or create a branch.

        Args:
            project_id: GitLab project ID
            branch_name: Name of the branch to create
            ref: Source branch/commit to create from

        Returns:
            Branch object dict

        Raises:
            GitlabGetError: If branch already exists
        """
        project = self.get_project(project_id)

        try:
            # Try to get existing branch
            branch = project.branches.get(branch_name)
            logger.info(f"Branch already exists: {branch_name}")
            return branch.__dict__["_attrs"]
        except GitlabGetError:
            # Branch doesn't exist, create it
            logger.info(f"Creating branch: {branch_name} from {ref}")
            branch = project.branches.create({
                "name": branch_name,
                "ref": ref,
            })
            return branch.__dict__["_attrs"]

    def create_merge_request(
        self,
        project_id: int,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        issue_iid: Optional[int] = None,
    ) -> MergeRequest:
        """Create a merge request.

        Args:
            project_id: GitLab project ID
            source_branch: Source branch name
            target_branch: Target branch name
            title: MR title
            description: MR description
            issue_iid: Related Issue IID (for auto-closing)

        Returns:
            MergeRequest object
        """
        project = self.get_project(project_id)

        mr_data = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
            "remove_source_branch": True,
        }

        if issue_iid:
            # Add issue reference
            mr_data["description"] += f"\n\nCloses #{issue_iid}"

        logger.info(f"Creating MR: {source_branch} -> {target_branch}")
        mr = project.mergerequests.create(mr_data)
        logger.info(f"MR created: {self.normalize_web_url(mr.web_url)}")

        return mr

    def normalize_web_url(self, url: Optional[str]) -> Optional[str]:
        """Normalize GitLab web URLs to the configured GitLab base URL."""
        if not url:
            return url

        configured = urlsplit(self.base_url)
        parsed = urlsplit(url)

        if not configured.scheme or not configured.netloc or not parsed.path:
            return url

        return urlunsplit((
            configured.scheme,
            configured.netloc,
            parsed.path,
            parsed.query,
            parsed.fragment,
        ))

    def get_merge_request(
        self, project_id: int, mr_iid: int
    ) -> Optional[MergeRequest]:
        """Get a merge request by IID.

        Args:
            project_id: GitLab project ID
            mr_iid: Merge request IID

        Returns:
            MergeRequest object or None
        """
        project = self.get_project(project_id)

        try:
            mr = project.mergerequests.get(mr_iid)
            return mr
        except GitlabGetError:
            logger.warning(f"MR not found: {project_id}/{mr_iid}")
            return None

    def get_mr_by_iid(self, project_id: int, mr_iid: int) -> Optional[dict]:
        """Get MR details by IID.

        Args:
            project_id: GitLab project ID
            mr_iid: Merge request IID

        Returns:
            Dict with MR details (source_branch, target_branch, issue_iid, title, state) or None
        """
        mr = self.get_merge_request(project_id, mr_iid)
        if not mr:
            return None

        return {
            "source_branch": mr.source_branch,
            "target_branch": mr.target_branch,
            "title": mr.title,
            "state": mr.state,
            # Get related issue from description or references
            "issue_iid": getattr(mr, 'issue_iid', None),
        }

    def get_merge_request_stats(
        self, project_id: int, mr_iid: int
    ) -> Optional[dict]:
        """Get merge request change statistics.

        Args:
            project_id: GitLab project ID
            mr_iid: Merge request IID

        Returns:
            Dict with additions, deletions, and total changes, or None
        """
        try:
            additions = 0
            deletions = 0

            # Use GitLab API directly via HTTP request
            import requests
            url = f"{self.base_url}/api/v4/projects/{project_id}/merge_requests/{mr_iid}/changes"
            response = requests.get(
                url,
                headers={"PRIVATE-TOKEN": self.private_token},
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            changes_list = data.get('changes', [])
            for change in changes_list:
                diff = change.get('diff', '')
                # Count lines starting with + (additions) and - (deletions)
                for line in diff.split('\n'):
                    if line.startswith('+') and not line.startswith('+++'):
                        additions += 1
                    elif line.startswith('-') and not line.startswith('---'):
                        deletions += 1

            logger.info(f"MR {mr_iid} stats: +{additions} -{deletions}")
            return {
                "additions": additions,
                "deletions": deletions,
                "total": additions + deletions
            }
        except Exception as e:
            logger.warning(f"Failed to get MR stats: {project_id}/{mr_iid}: {e}")
            return None

    def create_note(
        self, project_id: int, issue_iid: int, body: str
    ) -> dict:
        """Create a note (comment) on an issue.

        Args:
            project_id: GitLab project ID
            issue_iid: Issue IID
            body: Comment body

        Returns:
            Note object dict
        """
        project = self.get_project(project_id)
        issue = project.issues.get(issue_iid)

        note = issue.notes.create({
            "body": body,
        })

        logger.info(f"Comment created on issue {issue_iid}")
        return note.__dict__["_attrs"]

    def create_mr_note(
        self, project_id: int, mr_iid: int, body: str
    ) -> dict:
        """Create a note (comment) on a merge request.

        Args:
            project_id: GitLab project ID
            mr_iid: Merge request IID Comment body

        Returns:
            Note
            body: object dict
        """
        project = self.get_project(project_id)
        mr = project.mergerequests.get(mr_iid)

        note = mr.notes.create({
            "body": body,
        })

        logger.info(f"Comment created on MR !{mr_iid}")
        return note.__dict__["_attrs"]

    def update_note(
        self, project_id: int, issue_iid: int, note_id: int, body: str
    ) -> dict:
        """Update a note (comment) on an issue.

        Args:
            project_id: GitLab project ID
            issue_iid: Issue IID
            note_id: Note ID to update
            body: New comment body

        Returns:
            Updated note object dict
        """
        project = self.get_project(project_id)
        issue = project.issues.get(issue_iid)
        note = issue.notes.get(note_id)
        note.body = body
        note.save()

        logger.info(f"Comment updated on issue {issue_iid}")
        return note.__dict__["_attrs"]

    def get_file_content(
        self, project_id: int, file_path: str, ref: str = "main"
    ) -> str:
        """Get file content from repository.

        Args:
            project_id: GitLab project ID
            file_path: Path to file in repository
            ref: Branch/tag/commit reference

        Returns:
            File content as string
        """
        project = self.get_project(project_id)
        try:
            file = project.files.raw(file_path, ref=ref)
            return file.decode("utf-8")
        except GitlabGetError:
            logger.warning(f"File not found: {file_path}@{ref}")
            return ""

    def get_issue(self, project_id: int, issue_iid: int) -> Optional[dict]:
        """Get issue details.

        Args:
            project_id: GitLab project ID
            issue_iid: Issue IID

        Returns:
            Dict with issue title and description, or None
        """
        project = self.get_project(project_id)
        try:
            issue = project.issues.get(issue_iid)
            return {
                "title": issue.title,
                "description": issue.description,
            }
        except GitlabGetError:
            logger.warning(f"Issue not found: {project_id}/{issue_iid}")
            return None

    def get_projects(self, per_page: int = 100) -> list:
        """Get list of accessible projects.

        Args:
            per_page: Number of projects per page

        Returns:
            List of project dicts with id, name, path_with_namespace
        """
        logger.info("Fetching accessible projects")
        projects = self.gl.projects.list(per_page=per_page, membership=True)
        return [
            {
                "id": p.id,
                "name": p.name,
                "path_with_namespace": p.path_with_namespace,
            }
            for p in projects
        ]

    def get_branches(self, project_id: int) -> list:
        """Get list of branches for a project.

        Args:
            project_id: GitLab project ID

        Returns:
            List of branch dicts with name
        """
        logger.info(f"Fetching branches for project: {project_id}")
        # Use http_list with iterator to get all branches
        # The correct endpoint is /projects/:id/repository/branches
        all_branches = list(self.gl.http_list(
            f"/projects/{project_id}/repository/branches",
            per_page=100
        ))
        return [{"name": b["name"]} for b in all_branches]

    def close(self) -> None:
        """Close GitLab client."""
        # No explicit close needed for python-gitlab
        logger.info("GitLab client closed")


# Singleton instance
_gitlab_client: Optional[GitLabClient] = None
_gitlab_client_config: Optional[tuple[str, str]] = None


def _build_gitlab_client_config_snapshot(settings: Optional[Settings] = None) -> tuple[str, str]:
    active_settings = settings or get_effective_settings()
    return (
        active_settings.gitlab_url.strip(),
        active_settings.gitlab_bot_token,
    )


def reset_gitlab_client() -> None:
    """Drop any cached GitLab client so it will be recreated on next use."""
    global _gitlab_client, _gitlab_client_config
    if _gitlab_client is not None:
        _gitlab_client.close()
    _gitlab_client = None
    _gitlab_client_config = None


def get_gitlab_client() -> GitLabClient:
    """Get singleton GitLab client instance for the current effective config."""
    global _gitlab_client, _gitlab_client_config
    settings = get_effective_settings()
    current_config = _build_gitlab_client_config_snapshot(settings)
    if _gitlab_client is None or _gitlab_client_config != current_config:
        if _gitlab_client is not None:
            _gitlab_client.close()
        _gitlab_client = GitLabClient(settings=settings)
        _gitlab_client_config = current_config
    return _gitlab_client


async def get_accessible_projects_for_oauth_token(
    access_token: str,
    *,
    per_page: int = 100,
) -> list[dict]:
    """List GitLab projects accessible to the current OAuth user.

    This includes projects where the user is a member plus public/internal
    projects visible to the signed-in user.
    """
    if not access_token:
        return []

    base_url = get_effective_settings().gitlab_url.rstrip("/")
    projects_by_id: dict[int, dict] = {}

    async with httpx.AsyncClient(timeout=15.0) as client:
        async def collect_projects(query: dict[str, str]) -> None:
            page = 1
            while True:
                response = await client.get(
                    f"{base_url}/api/v4/projects",
                    params={
                        **query,
                        "simple": "true",
                        "per_page": per_page,
                        "page": page,
                        "order_by": "id",
                        "sort": "asc",
                    },
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                response.raise_for_status()
                payload = response.json()
                for project in payload:
                    projects_by_id[int(project["id"])] = {
                        "id": project["id"],
                        "name": project["name"],
                        "path_with_namespace": project["path_with_namespace"],
                    }
                next_page = response.headers.get("X-Next-Page")
                if not next_page:
                    break
                page = int(next_page)

        await collect_projects({"membership": "true"})
        await collect_projects({"visibility": "public"})
        await collect_projects({"visibility": "internal"})

    return list(projects_by_id.values())
