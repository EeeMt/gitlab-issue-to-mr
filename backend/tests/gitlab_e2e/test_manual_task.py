#!/usr/bin/env python3
"""
GitLab E2E tests for manual task creation.

These tests require a real GitLab instance and will be skipped
if GitLab is not available.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import logging
import time
from datetime import datetime
from typing import Optional

import pytest
import requests

# Configuration - should be set in environment or .env file
GITLAB_URL = os.getenv("GITLAB_URL", "http://192.168.50.129:8080")
GITLAB_TOKEN = os.getenv("GITLAB_BOT_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

_TEST_USERNAME = "test_admin_manual_e2e"
_TEST_PASSWORD = "SecurePass123!"

log = logging.getLogger(__name__)

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


# ─── Authenticated backend session ─────────────────────────────────────────────

_be_session: Optional[requests.Session] = None


def _get_be_session() -> requests.Session:
    """Return a persistent requests.Session authenticated with the Codify backend."""
    global _be_session
    if _be_session is not None:
        return _be_session

    session = requests.Session()
    try:
        bootstrap = requests.get(f"{BACKEND_URL}/api/auth/bootstrap-status", timeout=10).json()
        if not bootstrap.get("initialized"):
            session.post(
                f"{BACKEND_URL}/api/auth/local/register",
                json={
                    "username": _TEST_USERNAME,
                    "display_name": "Manual Task E2E Admin",
                    "email": f"{_TEST_USERNAME}@test.example.com",
                    "password": _TEST_PASSWORD,
                },
                timeout=10,
            )
    except Exception as exc:
        pytest.skip(f"Cannot reach backend: {exc}")

    try:
        resp = session.post(
            f"{BACKEND_URL}/api/auth/local/login",
            json={"username": _TEST_USERNAME, "password": _TEST_PASSWORD},
            timeout=10,
        )
    except Exception as exc:
        pytest.skip(f"Cannot reach backend for login: {exc}")

    if resp.status_code != 200:
        pytest.skip(f"Backend login failed ({resp.status_code})")

    log.info(f"Authenticated as {_TEST_USERNAME!r} at {BACKEND_URL}")
    _be_session = session
    return session


def _be(method: str, path: str, **kwargs) -> requests.Response:
    """Execute a backend API call with session auth."""
    return _get_be_session().request(method, f"{BACKEND_URL}{path}", timeout=30, **kwargs)


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
        # Should have at least one branch
        assert len(branches) > 0, "Expected at least one branch in the project"


class TestManualTaskAPI:
    """Test manual task API endpoints via backend."""

    @skip_if_no_gitlab
    def test_projects_endpoint_via_backend(self):
        """Test /api/projects endpoint via backend."""
        response = _be("GET", "/api/projects")
        assert response.status_code == 200
        projects = response.json()
        assert isinstance(projects, list)
        print(f"Backend /api/projects returned {len(projects)} projects")

    @skip_if_no_gitlab
    def test_branches_endpoint_via_backend(self):
        """Test /api/projects/{id}/branches endpoint via backend."""
        projects_response = _be("GET", "/api/projects")
        assert projects_response.status_code == 200

        projects = projects_response.json()
        if not projects:
            pytest.skip("No projects available")

        project_id = projects[0]["id"]
        response = _be("GET", f"/api/projects/{project_id}/branches")
        assert response.status_code == 200
        branches = response.json()
        assert isinstance(branches, list)
        print(f"Backend /api/projects/{project_id}/branches returned {len(branches)} branches")

    @skip_if_no_gitlab
    def test_create_task_via_backend(self):
        """Test POST /api/tasks endpoint via backend."""
        projects_response = _be("GET", "/api/projects")
        assert projects_response.status_code == 200

        projects = projects_response.json()
        if not projects:
            pytest.skip("No projects available")

        project_id = projects[0]["id"]
        task_data = {
            "project_id": project_id,
            "branch_name": f"test-manual-{int(datetime.now().timestamp())}",
            "target_branch": "main",
            "user_prompt": "Test manual task from E2E test",
            "priority": 2,
        }

        response = _be("POST", "/api/tasks", json=task_data)
        assert response.status_code == 200
        task = response.json()
        assert task["project_id"] == project_id
        assert task["is_manual"] is True
        assert task["status"] == "pending"
        print(f"Created manual task: {task['id']}")


class TestManualTaskFullWorkflow:
    """Test full manual task workflow."""

    @skip_if_no_gitlab
    @pytest.mark.slow
    def test_manual_task_workflow(self):
        """Test complete manual task workflow from creation to MR."""
        # 1. Get projects
        projects_response = _be("GET", "/api/projects")
        assert projects_response.status_code == 200

        projects = projects_response.json()
        if not projects:
            pytest.skip("No projects available")

        project_id = projects[0]["id"]
        print(f"Using project: {project_id}")

        # 2. Get branches
        branches_response = _be("GET", f"/api/projects/{project_id}/branches")
        assert branches_response.status_code == 200

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

        create_response = _be("POST", "/api/tasks", json=task_data)
        assert create_response.status_code == 200

        task = create_response.json()
        task_id = task["id"]
        print(f"Created task: {task_id}")

        # 4. Wait for task to complete (with timeout)
        max_wait = 300
        wait_interval = 5
        elapsed = 0

        while elapsed < max_wait:
            time.sleep(wait_interval)
            elapsed += wait_interval

            task_response = _be("GET", f"/api/tasks/{task_id}")
            if task_response.status_code == 200:
                task = task_response.json()
                status = task["status"]
                print(f"Task {task_id} status: {status}")

                if status == "completed":
                    if task.get("merge_request_url"):
                        print(f"MR created: {task['merge_request_url']}")
                        assert task["is_manual"] is True
                        return
                    else:
                        print("Task completed but no MR created")
                elif status in ["failed", "cancelled"]:
                    pytest.fail(f"Task failed: {task.get('error_message')}")

        pytest.skip("Task did not complete within timeout")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
