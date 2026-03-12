"""GitLab API client wrapper."""

import logging
from typing import Optional

import gitlab
from gitlab import Gitlab
from gitlab.exceptions import GitlabGetError
from gitlab.v4.objects import MergeRequest, Project

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class GitLabClient:
    """Wrapper around python-gitlab for GitLab API operations."""

    def __init__(self) -> None:
        """Initialize GitLab client."""
        self.gl: Gitlab = gitlab.Gitlab(
            settings.gitlab_url,
            private_token=settings.gitlab_bot_token,
        )
        logger.info(f"GitLab client initialized: {settings.gitlab_url}")

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
        logger.info(f"MR created: {mr.web_url}")

        return mr

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
        project = self.get_project(project_id)

        try:
            # Get the merge request with changes
            mr = project.mergerequests.get(mr_iid, include_diverged_commits_count=True)

            # Try to get stats directly from MR object (GitLab 15.2+)
            logger.info(f"MR {mr_iid} has changes_count: {hasattr(mr, 'changes_count')}")
            if hasattr(mr, 'changes_count') and mr.changes_count:
                # Format: "1" (simple count) or "10 files, +100 -50"
                changes_count = mr.changes_count
                logger.info(f"MR {mr_iid} changes_count: {changes_count}")
                # Parse additions/deletions from changes_count string
                # Example: "10 files, +100 -50"
                import re
                match = re.search(r'\+(\d+)\s+-(\d+)', changes_count)
                if match:
                    return {
                        "additions": int(match.group(1)),
                        "deletions": int(match.group(2)),
                        "total": int(match.group(1)) + int(match.group(2))
                    }
                # If changes_count is just a number (e.g., "1"), we need to get details from diff
                logger.info(f"MR {mr_iid} changes_count is simple number, getting diff for details")

            # Fallback: calculate from diff
            additions = 0
            deletions = 0

            try:
                # Get MR changes
                mr_with_changes = project.mergerequests.get(mr_iid, lazy=False)
                if hasattr(mr_with_changes, 'changes') and mr_with_changes.changes:
                    for change in mr_with_changes.changes.get('changes', []):
                        diff = change.get('diff', '')
                        # Count lines starting with + (additions) and - (deletions)
                        for line in diff.split('\n'):
                            if line.startswith('+') and not line.startswith('+++'):
                                additions += 1
                            elif line.startswith('-') and not line.startswith('---'):
                                deletions += 1
            except Exception as e:
                logger.warning(f"Could not get MR changes from diff: {e}")

            return {
                "additions": additions,
                "deletions": deletions,
                "total": additions + deletions
            }
        except GitlabGetError:
            logger.warning(f"Failed to get MR stats: {project_id}/{mr_iid}")
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

    def close(self) -> None:
        """Close GitLab client."""
        # No explicit close needed for python-gitlab
        logger.info("GitLab client closed")


# Singleton instance
_gitlab_client: Optional[GitLabClient] = None


def get_gitlab_client() -> GitLabClient:
    """Get singleton GitLab client instance."""
    global _gitlab_client
    if _gitlab_client is None:
        _gitlab_client = GitLabClient()
    return _gitlab_client
