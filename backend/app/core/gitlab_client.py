"""GitLab API client wrapper."""

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import gitlab
import httpx
from gitlab import Gitlab
from gitlab.exceptions import GitlabCreateError, GitlabDeleteError, GitlabError, GitlabGetError
from gitlab.v4.objects import MergeRequest, Project

from app.config import Settings, get_effective_settings
from app.core.ssl_utils import get_ssl_verify

logger = logging.getLogger(__name__)

# Project list cache
_PROJECT_LIST_CACHE_TTL_SECONDS = 300  # 5-minute freshness window
_project_list_cache: list[dict[str, Any]] = []
_project_list_cache_expires_at = 0.0
_project_list_refresh_task: asyncio.Task | None = None


class GitLabClient:
    """Wrapper around python-gitlab for GitLab API operations."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        private_token: str | None = None,
    ) -> None:
        """Initialize GitLab client."""
        self.settings = settings or get_effective_settings()
        self.base_url = self.settings.gitlab_url.rstrip("/")
        self.private_token = private_token if private_token is not None else self.settings.gitlab_bot_token
        self.gl: Gitlab = gitlab.Gitlab(
            self.base_url,
            private_token=self.private_token,
            ssl_verify=get_ssl_verify(self.settings),
            keep_base_url=True,
            timeout=30,
        )
        logger.info(f"GitLab client initialized: {self.base_url}")

    def create_sudo_gl(self, gitlab_user_id: int) -> Gitlab:
        """Create a Gitlab instance with admin token + sudo for impersonation.

        Args:
            gitlab_user_id: The GitLab user ID to impersonate.

        Returns:
            A Gitlab instance configured with sudo.

        Raises:
            ValueError: If gitlab_admin_token is not configured.
        """
        admin_token = self.settings.gitlab_admin_token.strip() if self.settings.gitlab_admin_token else ""
        if not admin_token:
            raise ValueError("gitlab_admin_token is required for sudo operations")
        gl = gitlab.Gitlab(
            self.base_url,
            private_token=admin_token,
            ssl_verify=get_ssl_verify(self.settings),
            keep_base_url=True,
            timeout=30,
        )
        gl.headers["Sudo"] = str(gitlab_user_id)
        return gl

    def ensure_project_label(self, project_id: int, label_name: str, color: str) -> None:
        """Ensure a label exists in the project, creating it if necessary.

        Uses the bot token (not sudo) to ensure label exists regardless of
        impersonated user's permissions.

        Args:
            project_id: GitLab project ID
            label_name: Label name (e.g., "Codify")
            color: Label color hex (e.g., "#6699cc")
        """
        project = self.get_project(project_id)
        try:
            project.labels.get(label_name)
        except GitlabGetError:
            try:
                project.labels.create({"name": label_name, "color": color})
                logger.info(f"Created label '{label_name}' in project {project_id}")
            except GitlabCreateError:
                # Race condition: another task created the label between our check and create
                logger.debug(f"Label '{label_name}' was created concurrently in project {project_id}")
            except Exception as e:
                logger.warning(f"Failed to create label '{label_name}' in project {project_id}: {e}")

    @staticmethod
    def _normalize_hook_url(url: str) -> str:
        return url.strip().rstrip("/")

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

    def delete_branch(self, project_id: int, branch_name: str) -> bool:
        """Delete a branch. Returns True if deleted or already gone. Returns False on other errors."""
        project = self.get_project(project_id)
        try:
            branch = project.branches.get(branch_name)
            branch.delete()
            logger.info(f"Deleted branch: {branch_name} in project {project_id}")
            return True
        except (GitlabGetError, GitlabDeleteError) as e:
            if e.response_code == 404:
                logger.info(f"Branch already gone: {branch_name} in project {project_id}")
                return True
            logger.warning(f"GitLab error deleting branch {branch_name} in project {project_id}: {e}")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error deleting branch {branch_name} in project {project_id}: {e}")
            return False

    def create_merge_request(
        self,
        project_id: int,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        issue_iid: int | None = None,
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

    def normalize_web_url(self, url: str | None) -> str | None:
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
    ) -> MergeRequest | None:
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

    def get_mr_by_iid(self, project_id: int, mr_iid: int) -> dict | None:
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

    async def get_merge_request_stats(
        self, project_id: int, mr_iid: int
    ) -> dict | None:
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
            url = f"{self.base_url}/api/v4/projects/{project_id}/merge_requests/{mr_iid}/changes"
            async with httpx.AsyncClient(timeout=30.0, verify=get_ssl_verify()) as client:
                response = await client.get(
                    url,
                    headers={"PRIVATE-TOKEN": self.private_token},
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

    def get_issue(self, project_id: int, issue_iid: int) -> dict | None:
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

        Fetches member projects plus public/internal projects visible to the bot
        user, mirroring the behaviour of the OAuth user path.  Results are
        deduplicated by project ID.

        Args:
            per_page: Number of projects per page for each query

        Returns:
            List of project dicts with id, name, path_with_namespace
        """
        logger.info("Fetching accessible projects")
        projects_by_id: dict[int, Any] = {}
        successful_queries = 0
        first_error: Exception | None = None

        for query_kwargs in [
            {"membership": True},
            {"visibility": "internal"},
            {"visibility": "public"},
        ]:
            try:
                page_results = self.gl.projects.list(per_page=per_page, all=True, **query_kwargs)
                successful_queries += 1
                for p in page_results:
                    if getattr(p, "marked_for_deletion_at", None):
                        logger.debug("Skipping project pending deletion: %s", p.path_with_namespace)
                        continue
                    projects_by_id[p.id] = p
            except Exception as exc:
                if first_error is None:
                    first_error = exc
                logger.warning("Failed to fetch projects with kwargs %s: %s", query_kwargs, exc)

        if successful_queries == 0 and first_error is not None:
            if isinstance(first_error, (GitlabError, httpx.HTTPError)):
                raise first_error
            raise GitlabError(f"Failed to fetch GitLab projects: {first_error}") from first_error

        result = []
        for p in projects_by_id.values():
            result.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "path_with_namespace": p.path_with_namespace,
                    "default_branch": getattr(p, "default_branch", None),
                    "web_url": getattr(p, "web_url", None),
                    "description": getattr(p, "description", None) or "",
                }
            )
        return result

    def get_branches(self, project_id: int) -> list:
        """Get list of branches for a project.

        Args:
            project_id: GitLab project ID

        Returns:
            List of branch dicts with name
        """
        logger.info(f"Fetching branches for project: {project_id}")
        # Use http_list with get_all=True to ensure all pages are fetched
        all_branches = self.gl.http_list(
            f"/projects/{project_id}/repository/branches",
            per_page=100,
            get_all=True,
        )
        return [{"name": b["name"]} for b in all_branches]

    def get_project_hooks(self, project_id: int) -> list[dict[str, Any]]:
        """Get all project hooks via the GitLab API."""
        logger.info("Fetching hooks for project: %s", project_id)
        return list(self.gl.http_list(f"/projects/{project_id}/hooks", per_page=100))

    def ensure_project_webhook(
        self,
        project_id: int,
        webhook_url: str,
        secret_token: str,
    ) -> dict[str, Any]:
        """Create or update the GitLab project webhook for this system."""
        normalized_target = self._normalize_hook_url(webhook_url)
        hook_payload = {
            "url": webhook_url,
            "token": secret_token,
            "enable_ssl_verification": True,
            "note_events": False,
            "issues_events": False,
            "merge_requests_events": True,
            "push_events": False,
            "tag_push_events": False,
            "job_events": False,
            "pipeline_events": True,
            "wiki_page_events": False,
        }

        existing_hook = next(
            (
                hook for hook in self.get_project_hooks(project_id)
                if self._normalize_hook_url(str(hook.get("url", ""))) == normalized_target
            ),
            None,
        )

        if existing_hook:
            hook_id = int(existing_hook["id"])
            logger.info("Updating existing webhook %s for project %s", hook_id, project_id)
            updated_hook = self.gl.http_put(
                f"/projects/{project_id}/hooks/{hook_id}",
                post_data=hook_payload,
            )
            return {
                "action": "updated",
                "hook": updated_hook,
            }

        logger.info("Creating webhook for project %s", project_id)
        created_hook = self.gl.http_post(
            f"/projects/{project_id}/hooks",
            post_data=hook_payload,
        )
        return {
            "action": "created",
            "hook": created_hook,
        }

    def get_merge_request_details(self, project_id: int, mr_iid: int) -> dict[str, Any] | None:
        """Get merge request branch and head SHA details used by CI repair gates."""
        mr = self.get_merge_request(project_id, mr_iid)
        if not mr:
            return None
        diff_refs = getattr(mr, "diff_refs", None) or {}
        sha = getattr(mr, "sha", None) or diff_refs.get("head_sha")
        return {
            "source_branch": getattr(mr, "source_branch", None),
            "target_branch": getattr(mr, "target_branch", None),
            "sha": sha,
            "web_url": self.normalize_web_url(getattr(mr, "web_url", None)),
            "state": getattr(mr, "state", None),
        }

    def get_pipeline_jobs(self, project_id: int, pipeline_id: int) -> list[dict[str, Any]]:
        """List GitLab jobs for one pipeline."""
        return list(
            self.gl.http_list(
                f"/projects/{project_id}/pipelines/{pipeline_id}/jobs",
                per_page=100,
                get_all=True,
            )
        )

    def get_job_trace(self, project_id: int, job_id: int) -> str:
        """Fetch raw GitLab CI job trace text."""
        return str(self.gl.http_get(f"/projects/{project_id}/jobs/{job_id}/trace"))

    def close(self) -> None:
        """Close GitLab client."""
        # No explicit close needed for python-gitlab
        logger.info("GitLab client closed")


# Singleton instance
_gitlab_client: GitLabClient | None = None
_gitlab_client_config: tuple[str, str, str] | None = None


def _build_gitlab_client_config_snapshot(settings: Settings | None = None) -> tuple[str, str, str]:
    active_settings = settings or get_effective_settings()
    return (
        active_settings.gitlab_url.strip(),
        active_settings.gitlab_bot_token,
        active_settings.gitlab_admin_token or "",
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


async def _refresh_project_list_cache() -> list[dict[str, Any]]:
    """Fetch fresh project list from GitLab and update the cache."""
    global _project_list_cache, _project_list_cache_expires_at, _project_list_refresh_task

    try:
        gitlab = get_gitlab_client()
        projects = await asyncio.to_thread(gitlab.get_projects)
        _project_list_cache = projects
        _project_list_cache_expires_at = time.time() + _PROJECT_LIST_CACHE_TTL_SECONDS
        logger.info("Project list cache refreshed, %d projects", len(projects))
    except Exception as exc:
        logger.warning("Failed to refresh project list cache: %s", exc)
    finally:
        _project_list_refresh_task = None
    return _project_list_cache


async def get_cached_projects() -> list[dict[str, Any]]:
    """Return cached GitLab project list using stale-while-revalidate.

    Returns stale data immediately when the cache has expired, and kicks off
    a background refresh so the next caller gets fresh data without blocking.
    Only blocks on the very first call (cold cache with no data at all).
    """
    global _project_list_refresh_task

    now = time.time()
    if _project_list_cache and _project_list_cache_expires_at > now:
        # Fresh — return without waiting.
        return _project_list_cache

    if _project_list_cache:
        # Stale but not empty — return immediately and refresh in background.
        if _project_list_refresh_task is None or _project_list_refresh_task.done():
            _project_list_refresh_task = asyncio.create_task(_refresh_project_list_cache())
        return _project_list_cache

    # Cold cache: must wait for the first fetch.
    return await _refresh_project_list_cache()


def invalidate_project_list_cache() -> None:
    """Manually invalidate the project list cache.

    This forces the next call to get_cached_projects() to fetch fresh data.
    """
    global _project_list_cache, _project_list_cache_expires_at, _project_list_refresh_task
    _project_list_cache = []
    _project_list_cache_expires_at = 0.0
    if _project_list_refresh_task is not None and not _project_list_refresh_task.done():
        _project_list_refresh_task.cancel()
    _project_list_refresh_task = None
    logger.info("Project list cache invalidated")


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

    async with httpx.AsyncClient(timeout=15.0, verify=get_ssl_verify()) as client:
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
                    if project.get("marked_for_deletion_at"):
                        continue
                    projects_by_id[int(project["id"])] = {
                        "id": project["id"],
                        "name": project["name"],
                        "path_with_namespace": project["path_with_namespace"],
                        "default_branch": project.get("default_branch"),
                        "web_url": project.get("web_url"),
                        "description": project.get("description") or "",
                    }
                next_page = response.headers.get("X-Next-Page")
                if not next_page:
                    break
                page = int(next_page)

        await asyncio.gather(
            collect_projects({"membership": "true"}),
            collect_projects({"visibility": "public"}),
            collect_projects({"visibility": "internal"}),
        )
    return list(projects_by_id.values())
