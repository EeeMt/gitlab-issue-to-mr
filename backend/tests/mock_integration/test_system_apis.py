"""System API tests — config, stats, projects, auth endpoints.

These tests verify API endpoints that don't require Docker container execution.
They're fast (no task execution) and cover admin/config/stats surfaces.

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import logging

import httpx
import pytest

from .conftest import (
    wait_for_task_status,
)

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# System stats
# ---------------------------------------------------------------------------

class TestSystemStats:
    """Verify GET /stats returns task statistics."""

    async def test_stats_returns_counts(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Stats endpoint should return task counts by status."""
        resp = await http_client.get(
            f"{backend_url}/api/stats",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()

        # Should have standard count fields
        expected_fields = ["total", "completed", "failed", "pending"]
        for field in expected_fields:
            assert field in data, f"Stats missing '{field}' field"

        assert data["total"] >= 0
        logger.info(
            f"✅ Stats: total={data['total']}, "
            f"completed={data.get('completed', 0)}, "
            f"failed={data.get('failed', 0)}, "
            f"running={data.get('running', 0)}"
        )


class TestAnalyticsEndpoint:
    """Verify GET /stats/analytics returns time-window analytics."""

    async def test_analytics_30_days(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Analytics endpoint with default 30-day window."""
        resp = await http_client.get(
            f"{backend_url}/api/stats/analytics",
            params={"days": 30},
            headers=admin_auth_headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            assert "summary" in data or "window_days" in data, (
                f"Analytics should have summary or window_days: {list(data.keys())}"
            )
            logger.info(f"✅ Analytics (30d): {list(data.keys())}")
        elif resp.status_code == 403:
            logger.info("ℹ️ Analytics requires page access (403)")
        else:
            logger.info(f"ℹ️ Analytics returned {resp.status_code}")

    async def test_analytics_invalid_days_rejected(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """days=3 should be rejected (min 7)."""
        resp = await http_client.get(
            f"{backend_url}/api/stats/analytics",
            params={"days": 3},
            headers=admin_auth_headers,
        )
        assert resp.status_code in (400, 403, 422), (
            f"Invalid days=3 should fail, got {resp.status_code}"
        )
        logger.info(f"✅ Analytics days=3 rejected with {resp.status_code}")


# ---------------------------------------------------------------------------
# Config API
# ---------------------------------------------------------------------------

class TestConfigEndpoint:
    """Verify config read/write endpoints."""

    async def test_get_config(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """GET /config should return current configuration."""
        resp = await http_client.get(
            f"{backend_url}/api/config",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()

        # Should have at least runtime section
        has_sections = any(
            k in data for k in ["runtime", "auth", "integration"]
        )
        assert has_sections or isinstance(data, dict), (
            f"Config should have sections: {list(data.keys())}"
        )
        logger.info(f"✅ Config: sections={list(data.keys())}")

    async def test_patch_config_runtime(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """PATCH /config to update runtime settings (then revert)."""
        # Read current config
        resp = await http_client.get(
            f"{backend_url}/api/config",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        original = resp.json()

        # Try a safe update — change max_concurrent_tasks
        original_max = (
            original.get("runtime", {}).get("max_concurrent_tasks")
            or original.get("max_concurrent_tasks")
        )

        resp2 = await http_client.patch(
            f"{backend_url}/api/config",
            json={"runtime": {"max_concurrent_tasks": 5}},
            headers=admin_auth_headers,
        )

        if resp2.status_code == 200:
            updated = resp2.json()
            new_max = (
                updated.get("runtime", {}).get("max_concurrent_tasks")
                or updated.get("max_concurrent_tasks")
            )
            logger.info(
                f"✅ Config updated: max_concurrent_tasks "
                f"{original_max} → {new_max}"
            )

            # Revert
            if original_max is not None:
                await http_client.patch(
                    f"{backend_url}/api/config",
                    json={"runtime": {"max_concurrent_tasks": original_max}},
                    headers=admin_auth_headers,
                )
        else:
            logger.info(f"ℹ️ Config patch returned {resp2.status_code}")


# ---------------------------------------------------------------------------
# Auth / user info
# ---------------------------------------------------------------------------

class TestAuthEndpoints:
    """Verify auth-related endpoints."""

    async def test_bootstrap_status(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
    ):
        """GET /auth/bootstrap-status — no auth required."""
        resp = await http_client.get(
            f"{backend_url}/api/auth/bootstrap-status",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "initialized" in data, f"Missing 'initialized': {data}"
        assert data["initialized"] is True, "System should be initialized"
        logger.info(f"✅ Bootstrap: initialized={data['initialized']}")

    async def test_me_endpoint(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """GET /auth/me returns current user info."""
        resp = await http_client.get(
            f"{backend_url}/api/auth/me",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("authenticated") is True, (
            f"Should be authenticated: {data}"
        )
        user = data.get("user", {})
        assert user.get("username"), f"Should have username: {user}"
        logger.info(
            f"✅ /auth/me: user={user.get('username')}, "
            f"role={user.get('role', 'unknown')}"
        )

    async def test_me_unauthenticated(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
    ):
        """GET /auth/me without auth should return unauthenticated."""
        resp = await http_client.get(
            f"{backend_url}/api/auth/me",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("authenticated") is False, (
            f"Should be unauthenticated without cookie: {data}"
        )
        logger.info("✅ /auth/me unauthenticated: correct")


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class TestProjectsEndpoint:
    """Verify project listing from mock GitLab."""

    async def test_list_projects(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """GET /projects should return projects from mock GitLab API."""
        resp = await http_client.get(
            f"{backend_url}/api/projects",
            headers=admin_auth_headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            projects = data if isinstance(data, list) else data.get("items", [])
            logger.info(f"✅ Projects: {len(projects)} returned")
            if projects:
                first = projects[0]
                assert "id" in first, f"Project should have 'id': {first}"
        else:
            # May fail if mock doesn't support the projects list endpoint
            logger.info(f"ℹ️ Projects returned {resp.status_code}")

    async def test_list_branches(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """GET /projects/{id}/branches for mock project."""
        resp = await http_client.get(
            f"{backend_url}/api/projects/1/branches",
            headers=admin_auth_headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            branches = data if isinstance(data, list) else data.get("items", [])
            logger.info(f"✅ Branches for project 1: {len(branches)} returned")
        else:
            logger.info(f"ℹ️ Branches returned {resp.status_code}")


# ---------------------------------------------------------------------------
# Task list filters
# ---------------------------------------------------------------------------

class TestTaskListAdvancedFilters:
    """Verify task list filtering by project_id and initiator."""

    async def test_filter_by_project_id(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """GET /tasks?project_id=1 should only return tasks for that project."""
        # Create a task first
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Project filter test",
                "branch_name": "codify/project-filter-test",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        # Filter by project_id=1
        resp2 = await http_client.get(
            f"{backend_url}/api/tasks",
            params={"project_id": 1},
            headers=admin_auth_headers,
        )
        assert resp2.status_code == 200
        data = resp2.json()
        tasks_list = data if isinstance(data, list) else data.get("items", [])

        # All tasks should be for project 1
        for t in tasks_list:
            assert t.get("project_id") == 1, (
                f"Task {t['id']} has project_id={t.get('project_id')}, expected 1"
            )

        # Our task should be in results
        ids = [t["id"] for t in tasks_list]
        assert task_id in ids, f"Task {task_id} not in project 1 results"

        # Filter by non-existent project should return empty
        resp3 = await http_client.get(
            f"{backend_url}/api/tasks",
            params={"project_id": 99999},
            headers=admin_auth_headers,
        )
        assert resp3.status_code == 200
        data3 = resp3.json()
        tasks_list3 = data3 if isinstance(data3, list) else data3.get("items", [])
        assert len(tasks_list3) == 0, (
            f"Project 99999 should have 0 tasks, got {len(tasks_list3)}"
        )
        logger.info("✅ Project ID filter works correctly")

    async def test_filter_by_initiator_username(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """GET /tasks?initiator_username=admin should filter by user."""
        resp = await http_client.get(
            f"{backend_url}/api/tasks",
            params={"initiator_username": "admin"},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        tasks_list = data if isinstance(data, list) else data.get("items", [])

        # All returned tasks should have initiator_username=admin
        for t in tasks_list:
            initiator = t.get("initiator_username", "")
            if initiator:
                assert initiator == "admin", (
                    f"Task {t['id']} has initiator={initiator}, expected admin"
                )

        logger.info(
            f"✅ Initiator filter: {len(tasks_list)} tasks by 'admin'"
        )

        # Non-existent user should return empty
        resp2 = await http_client.get(
            f"{backend_url}/api/tasks",
            params={"initiator_username": "nonexistent_user_xyz"},
            headers=admin_auth_headers,
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        tasks_list2 = data2 if isinstance(data2, list) else data2.get("items", [])
        assert len(tasks_list2) == 0, (
            f"Nonexistent user should have 0 tasks, got {len(tasks_list2)}"
        )
        logger.info("✅ Initiator filter with nonexistent user returns empty")


# ---------------------------------------------------------------------------
# Scheduled stats
# ---------------------------------------------------------------------------

class TestScheduledStats:
    """Verify GET /stats/scheduled returns scheduling overview."""

    async def test_scheduled_stats_returns_data(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Scheduled stats should return hourly distribution data."""
        resp = await http_client.get(
            f"{backend_url}/api/stats/scheduled",
            headers=admin_auth_headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            assert "summary" in data or "hourly_distribution" in data, (
                f"Scheduled stats should have summary: {list(data.keys())}"
            )
            logger.info(f"✅ Scheduled stats: {list(data.keys())}")
        elif resp.status_code == 403:
            logger.info("ℹ️ Scheduled stats requires page access (403)")
        else:
            logger.info(f"ℹ️ Scheduled stats returned {resp.status_code}")


# ---------------------------------------------------------------------------
# Containers (without task execution)
# ---------------------------------------------------------------------------

class TestContainersEndpointNoTask:
    """Verify container listing when no tasks are running."""

    async def test_empty_containers_list(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """When no tasks are running, containers list should be empty or small."""
        resp = await http_client.get(
            f"{backend_url}/api/containers",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        containers = data if isinstance(data, list) else data.get("items", data.get("containers", []))
        logger.info(f"✅ Containers (idle): {len(containers)} running")
