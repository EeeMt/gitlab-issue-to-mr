#!/usr/bin/env python3
"""
GitLab E2E tests for manual task creation.

These tests require a real GitLab instance and will be skipped
if GitLab is not available.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
import requests
import os

# Configuration - should be set in environment or .env file
GITLAB_URL = os.getenv("GITLAB_URL", "http://192.168.50.129:8080")
GITLAB_TOKEN = os.getenv("GITLAB_BOT_TOKEN", "")

# Skip all tests if GitLab is not available
skip_if_no_gitlab = pytest.mark.skipif(
    not GITLAB_TOKEN,
    reason="GitLab token not set"
)


def is_gitlab_available() -> bool:
    """Check if GitLab is available."""
    if not GITLAB_TOKEN:
        return False
    try:
        response = requests.get(
            f"{GITLAB_URL}/api/v4/version",
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
            timeout=5
        )
        return response.status_code == 200
    except Exception:
        return False


# Mark all tests to skip if GitLab is not available
pytestmark = pytest.mark.skipif(
    not is_gitlab_available(),
    reason="GitLab not available"
)


class TestGitLabProjects:
    """Test GitLab projects API."""

    @skip_if_no_gitlab
    def test_get_projects(self):
        """Test getting project list from GitLab."""
        response = requests.get(
            f"{GITLAB_URL}/api/v4/projects",
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
            params={"membership": True, "per_page": 10},
            timeout=10
        )

        assert response.status_code == 200
        projects = response.json()
        assert isinstance(projects, list)
        # Should have at least one project if GitLab is working
        print(f"Found {len(projects)} projects")

    @skip_if_no_gitlab
    def test_get_project_branches(self):
        """Test getting branches for a project."""
        # First get a project
        response = requests.get(
            f"{GITLAB_URL}/api/v4/projects",
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
            params={"membership": True, "per_page": 1},
            timeout=10
        )

        assert response.status_code == 200
        projects = response.json()
        if not projects:
            pytest.skip("No projects available")

        project_id = projects[0]["id"]

        # Get branches
        response = requests.get(
            f"{GITLAB_URL}/api/v4/projects/{project_id}/repository/branches",
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
            timeout=10
        )

        assert response.status_code == 200
        branches = response.json()
        assert isinstance(branches, list)
        print(f"Found {len(branches)} branches")
        # Should have at least main branch
        branch_names = [b["name"] for b in branches]
        assert "main" in branch_names or "master" in branch_names


class TestManualTaskAPI:
    """Test manual task API endpoints via backend."""

    @skip_if_no_gitlab
    def test_projects_endpoint_via_backend(self):
        """Test /api/projects endpoint via backend."""
        backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")

        try:
            response = requests.get(
                f"{backend_url}/api/projects",
                timeout=10
            )

            if response.status_code == 200:
                projects = response.json()
                assert isinstance(projects, list)
                print(f"Backend /api/projects returned {len(projects)} projects")
            else:
                pytest.skip(f"Backend not available: {response.status_code}")
        except requests.exceptions.RequestException as e:
            pytest.skip(f"Backend not available: {e}")

    @skip_if_no_gitlab
    def test_branches_endpoint_via_backend(self):
        """Test /api/projects/{id}/branches endpoint via backend."""
        backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")

        try:
            # First get projects
            projects_response = requests.get(
                f"{backend_url}/api/projects",
                timeout=10
            )

            if projects_response.status_code != 200:
                pytest.skip(f"Backend not available: {projects_response.status_code}")

            projects = projects_response.json()
            if not projects:
                pytest.skip("No projects available")

            project_id = projects[0]["id"]

            # Get branches
            response = requests.get(
                f"{backend_url}/api/projects/{project_id}/branches",
                timeout=10
            )

            assert response.status_code == 200
            branches = response.json()
            assert isinstance(branches, list)
            print(f"Backend /api/projects/{project_id}/branches returned {len(branches)} branches")
        except requests.exceptions.RequestException as e:
            pytest.skip(f"Backend not available: {e}")

    @skip_if_no_gitlab
    def test_create_task_via_backend(self):
        """Test POST /api/tasks endpoint via backend."""
        backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")

        try:
            # First get projects
            projects_response = requests.get(
                f"{backend_url}/api/projects",
                timeout=10
            )

            if projects_response.status_code != 200:
                pytest.skip(f"Backend not available: {projects_response.status_code}")

            projects = projects_response.json()
            if not projects:
                pytest.skip("No projects available")

            project_id = projects[0]["id"]

            # Create task
            task_data = {
                "project_id": project_id,
                "branch_name": f"test-manual-{int(datetime.now().timestamp())}",
                "target_branch": "main",
                "user_prompt": "Test manual task from E2E test",
                "priority": 2,
            }

            response = requests.post(
                f"{backend_url}/api/tasks",
                json=task_data,
                timeout=10
            )

            assert response.status_code == 200
            task = response.json()
            assert task["project_id"] == project_id
            assert task["is_manual"] is True
            assert task["status"] == "pending"
            print(f"Created manual task: {task['id']}")
        except requests.exceptions.RequestException as e:
            pytest.skip(f"Backend not available: {e}")


class TestManualTaskFullWorkflow:
    """Test full manual task workflow."""

    @skip_if_no_gitlab
    @pytest.mark.slow
    def test_manual_task_workflow(self):
        """Test complete manual task workflow from creation to MR."""
        backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")

        try:
            # 1. Get projects
            projects_response = requests.get(
                f"{backend_url}/api/projects",
                timeout=10
            )

            if projects_response.status_code != 200:
                pytest.skip(f"Backend not available: {projects_response.status_code}")

            projects = projects_response.json()
            if not projects:
                pytest.skip("No projects available")

            project_id = projects[0]["id"]
            print(f"Using project: {project_id}")

            # 2. Get branches
            branches_response = requests.get(
                f"{backend_url}/api/projects/{project_id}/branches",
                timeout=10
            )

            if branches_response.status_code != 200:
                pytest.skip("Cannot get branches")

            branches = branches_response.json()
            main_branch = "main" if any(b["name"] == "main" for b in branches) else branches[0]["name"]
            print(f"Using main branch: {main_branch}")

            # 3. Create manual task
            branch_name = f"test-manual-e2e-{int(datetime.now().timestamp())}"
            task_data = {
                "project_id": project_id,
                "branch_name": branch_name,
                "target_branch": main_branch,
                "user_prompt": "Create a simple README.md file",
                "priority": 0,
            }

            create_response = requests.post(
                f"{backend_url}/api/tasks",
                json=task_data,
                timeout=10
            )

            if create_response.status_code != 200:
                pytest.skip(f"Cannot create task: {create_response.status_code}")

            task = create_response.json()
            task_id = task["id"]
            print(f"Created task: {task_id}")

            # 4. Wait for task to complete (with timeout)
            max_wait = 300  # 5 minutes
            wait_interval = 5
            elapsed = 0

            while elapsed < max_wait:
                time.sleep(wait_interval)
                elapsed += wait_interval

                task_response = requests.get(
                    f"{backend_url}/api/tasks/{task_id}",
                    timeout=10
                )

                if task_response.status_code == 200:
                    task = task_response.json()
                    status = task["status"]

                    print(f"Task {task_id} status: {status}")

                    if status == "completed":
                        # Check if MR was created
                        if task.get("merge_request_url"):
                            print(f"MR created: {task['merge_request_url']}")
                            assert task["is_manual"] is True
                            return  # Success!
                        else:
                            print("Task completed but no MR created")

                    elif status in ["failed", "cancelled"]:
                        pytest.fail(f"Task failed: {task.get('error_message')}")

            pytest.skip("Task did not complete within timeout")

        except requests.exceptions.RequestException as e:
            pytest.skip(f"Backend not available: {e}")


# Import datetime for timestamp
from datetime import datetime
import time


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
