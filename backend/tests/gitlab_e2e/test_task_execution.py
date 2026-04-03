#!/usr/bin/env python3
"""
Integration tests for manual task creation and execution.

These tests require:
  - A running backend at BACKEND_URL
  - A running scheduler (will execute tasks via Docker)
  - A real GitLab instance at GITLAB_URL
  - Valid ANTHROPIC_* credentials (Claude CLI will run inside worker containers)

Run with:
    cd backend && python3 -m pytest tests/gitlab_e2e/test_task_execution.py -v -s
    # or individually:
    cd backend && python3 -m pytest tests/gitlab_e2e/test_task_execution.py::TestManualTaskExecution::test_with_mr -v -s

All tests are skipped when the backend or GitLab is unreachable.
"""

import os
import time
import uuid
import logging
from datetime import datetime, timedelta, UTC
from typing import Optional

import pytest
import requests

# ─── Configuration ────────────────────────────────────────────────────────────

# Load optional .env file from backend root (or deploy/.env.test if present)
for _env_file in [
    os.path.join(os.path.dirname(__file__), ".env"),
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "deploy", ".env.test"),
]:
    if os.path.exists(_env_file):
        with open(_env_file) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _key, _val = _line.split("=", 1)
                    os.environ.setdefault(_key, _val)

GITLAB_URL = os.getenv("GITLAB_URL", "http://192.168.50.129:8080")
GITLAB_TOKEN = os.getenv("GITLAB_BOT_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# Credentials for Codify backend local-auth login.
# Default "SecurePass123!" matches the E2E Docker environment's auto-bootstrapped admin.
# Override with INT_TEST_USERNAME / INT_TEST_PASSWORD for other deployments.
INT_TEST_USERNAME = os.getenv("INT_TEST_USERNAME", "admin")
INT_TEST_PASSWORD = os.getenv("INT_TEST_PASSWORD", "SecurePass123!")

# Project used for all tests — must exist in GitLab and be accessible to the bot token.
TEST_PROJECT_ID = int(os.getenv("TEST_PROJECT_ID", "1"))

# How long to wait for a task to reach COMPLETED / FAILED status.
TASK_EXECUTION_TIMEOUT = int(os.getenv("TASK_EXECUTION_TIMEOUT", "360"))  # seconds
POLL_INTERVAL = 5  # seconds between status polls

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─── Availability helpers ──────────────────────────────────────────────────────


def _backend_available() -> bool:
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _gitlab_available() -> bool:
    if not GITLAB_TOKEN:
        return False
    try:
        r = requests.get(
            f"{GITLAB_URL}/api/v4/version",
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
            timeout=5,
        )
        return r.status_code == 200
    except Exception:
        return False


_backend_up = _backend_available()
_gitlab_up = _gitlab_available()

skip_if_unavailable = pytest.mark.skipif(
    not (_backend_up and _gitlab_up),
    reason="Backend or GitLab not reachable — skipping execution tests",
)

# ─── Low-level helpers ─────────────────────────────────────────────────────────

_be_session: Optional[requests.Session] = None


def _get_be_session() -> requests.Session:
    """Return a persistent requests.Session authenticated with the Codify backend.

    If the system is not yet initialized, registers the test user first.
    Skips the test if login fails (wrong credentials or auth not configured).
    """
    global _be_session
    if _be_session is not None:
        return _be_session

    session = requests.Session()

    # Try to register first (succeeds only when system is uninitialized)
    try:
        bootstrap = requests.get(f"{BACKEND_URL}/api/auth/bootstrap-status", timeout=10).json()
        if not bootstrap.get("initialized"):
            session.post(
                f"{BACKEND_URL}/api/auth/local/register",
                json={
                    "username": INT_TEST_USERNAME,
                    "display_name": "Integration Test Admin",
                    "email": f"{INT_TEST_USERNAME}@test.example.com",
                    "password": INT_TEST_PASSWORD,
                },
                timeout=10,
            )
    except Exception as exc:
        pytest.skip(f"Cannot reach backend: {exc}")

    # Login
    try:
        resp = session.post(
            f"{BACKEND_URL}/api/auth/local/login",
            json={"username": INT_TEST_USERNAME, "password": INT_TEST_PASSWORD},
            timeout=10,
        )
    except Exception as exc:
        pytest.skip(f"Cannot reach backend for login: {exc}")

    if resp.status_code != 200:
        pytest.skip(
            f"Backend login failed ({resp.status_code}) — "
            f"set INT_TEST_USERNAME / INT_TEST_PASSWORD to valid local-auth credentials. "
            f"Response: {resp.text[:200]}"
        )

    log.info(f"Authenticated as {INT_TEST_USERNAME!r} at {BACKEND_URL}")
    _be_session = session
    return session


def _gl(method: str, path: str, **kwargs) -> requests.Response:
    """Execute a GitLab API call."""
    headers = kwargs.pop("headers", {})
    headers["PRIVATE-TOKEN"] = GITLAB_TOKEN
    return requests.request(
        method,
        f"{GITLAB_URL}/api/v4{path}",
        headers=headers,
        timeout=30,
        **kwargs,
    )


def _be(method: str, path: str, **kwargs) -> requests.Response:
    """Execute a backend API call with session auth."""
    return _get_be_session().request(
        method,
        f"{BACKEND_URL}{path}",
        timeout=30,
        **kwargs,
    )


def _unique_branch(prefix: str = "integration-test") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _create_task(
    project_id: int,
    branch_name: str,
    user_prompt: str,
    target_branch: Optional[str] = "main",
    base_branch: Optional[str] = None,
    priority: int = 0,
) -> dict:
    """Create a manual task via the backend API and return the task dict."""
    payload: dict = {
        "project_id": project_id,
        "branch_name": branch_name,
        "user_prompt": user_prompt,
        "priority": priority,
    }
    if target_branch is not None:
        payload["target_branch"] = target_branch
    if base_branch:
        payload["base_branch"] = base_branch

    r = _be("POST", "/api/tasks", json=payload)
    assert r.status_code == 200, f"Task creation failed {r.status_code}: {r.text}"
    return r.json()


def _wait_for_terminal(task_id: int, timeout: int = TASK_EXECUTION_TIMEOUT) -> dict:
    """Poll GET /api/tasks/{id} until status is completed, failed, or cancelled."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = _be("GET", f"/api/tasks/{task_id}")
        assert r.status_code == 200, f"Cannot fetch task {task_id}: {r.status_code}"
        task = r.json()
        status = task["status"]
        log.info(f"Task {task_id} status: {status}")
        if status in ("completed", "failed", "cancelled"):
            return task
        time.sleep(POLL_INTERVAL)
    pytest.fail(f"Task {task_id} did not reach terminal status within {timeout}s")


def _delete_branch(project_id: int, branch_name: str) -> None:
    """Best-effort delete a GitLab branch (cleanup)."""
    try:
        r = _gl(
            "DELETE",
            f"/projects/{project_id}/repository/branches/{branch_name}",
        )
        if r.status_code in (200, 204):
            log.info(f"Deleted branch {branch_name}")
        else:
            log.warning(f"Could not delete branch {branch_name}: {r.status_code}")
    except Exception as e:
        log.warning(f"Branch cleanup error: {e}")


def _delete_mr(project_id: int, mr_iid: int) -> None:
    """Best-effort close a GitLab MR (cleanup)."""
    try:
        _gl("PUT", f"/projects/{project_id}/merge_requests/{mr_iid}", json={"state_event": "close"})
    except Exception as e:
        log.warning(f"MR close error: {e}")


def _get_project_default_branch(project_id: int) -> str:
    r = _gl("GET", f"/projects/{project_id}")
    r.raise_for_status()
    return r.json().get("default_branch", "main")


# ─── Test classes ──────────────────────────────────────────────────────────────


@skip_if_unavailable
class TestManualTaskExecution:
    """Full execution tests — run a real worker container, verify results."""

    def test_with_mr(self):
        """Task with target_branch set: worker should push + create MR."""
        branch = _unique_branch("e2e-with-mr")
        default_branch = _get_project_default_branch(TEST_PROJECT_ID)

        task = _create_task(
            project_id=TEST_PROJECT_ID,
            branch_name=branch,
            user_prompt=(
                "Create a file named integration_test_hello.txt "
                "with the single line: Hello from Codify integration test"
            ),
            target_branch=default_branch,
        )
        task_id = task["id"]
        log.info(f"Created task {task_id} (with-MR), branch={branch}")

        assert task["is_manual"] is True
        assert task["target_branch"] == default_branch

        try:
            result = _wait_for_terminal(task_id)

            assert result["status"] == "completed", (
                f"Task failed: {result.get('error_message', '')[:500]}"
            )
            assert result["commit_sha"], "Expected commit_sha to be set on completion"
            assert result["merge_request_iid"], "Expected MR to be created when target_branch is set"
            assert result["merge_request_url"], "Expected merge_request_url to be set"

            log.info(
                f"✅ with-MR test passed — "
                f"MR !{result['merge_request_iid']} at {result['merge_request_url']}"
            )

            # Verify MR exists on GitLab
            mr_r = _gl(
                "GET",
                f"/projects/{TEST_PROJECT_ID}/merge_requests/{result['merge_request_iid']}",
            )
            assert mr_r.status_code == 200, "MR not found on GitLab"
            mr = mr_r.json()
            assert mr["source_branch"] == branch
            assert mr["target_branch"] == default_branch
            assert mr["sha"], "MR has no commit SHA on GitLab"

        finally:
            _delete_mr(TEST_PROJECT_ID, result.get("merge_request_iid") if "result" in dir() else 0)
            _delete_branch(TEST_PROJECT_ID, branch)

    def test_without_mr(self):
        """Task without target_branch (no-MR mode): worker should push branch, no MR created."""
        branch = _unique_branch("e2e-no-mr")
        default_branch = _get_project_default_branch(TEST_PROJECT_ID)

        task = _create_task(
            project_id=TEST_PROJECT_ID,
            branch_name=branch,
            user_prompt=(
                "Create a file named no_mr_test.txt "
                "with the content: No MR mode integration test"
            ),
            target_branch=None,          # ← no-MR mode
            base_branch=default_branch,  # need explicit base when no target
        )
        task_id = task["id"]
        log.info(f"Created task {task_id} (no-MR), branch={branch}")

        assert task["is_manual"] is True
        assert task["target_branch"] is None

        try:
            result = _wait_for_terminal(task_id)

            assert result["status"] == "completed", (
                f"Task failed: {result.get('error_message', '')[:500]}"
            )
            assert result["commit_sha"], "Expected commit_sha to be set on completion"
            assert result["merge_request_iid"] is None, (
                "Expected NO MR when target_branch is None"
            )
            assert result["merge_request_url"] is None, (
                "Expected no merge_request_url in no-MR mode"
            )

            # Verify the branch actually exists on GitLab
            branch_r = _gl(
                "GET",
                f"/projects/{TEST_PROJECT_ID}/repository/branches/{branch}",
            )
            assert branch_r.status_code == 200, f"Branch {branch} not found on GitLab after task"
            assert branch_r.json()["commit"]["id"] == result["commit_sha"]

            log.info(f"✅ no-MR test passed — branch {branch} pushed, commit {result['commit_sha']}")

        finally:
            _delete_branch(TEST_PROJECT_ID, branch)

    def test_task_cancel_and_retry(self):
        """Create a task, cancel it immediately (before RUNNING), then retry it."""
        branch = _unique_branch("e2e-cancel-retry")
        default_branch = _get_project_default_branch(TEST_PROJECT_ID)

        task = _create_task(
            project_id=TEST_PROJECT_ID,
            branch_name=branch,
            user_prompt="Create a file named cancel_retry_test.txt with content: retry test",
            target_branch=default_branch,
            priority=2,  # low priority to reduce race with scheduler
        )
        task_id = task["id"]
        log.info(f"Created task {task_id} for cancel/retry test")

        # Cancel while still pending/queued (best-effort)
        cancel_r = _be("POST", f"/api/tasks/{task_id}/cancel")
        if cancel_r.status_code == 200:
            log.info(f"Cancelled task {task_id}")
            # Retry it
            retry_r = _be("POST", f"/api/tasks/{task_id}/retry")
            assert retry_r.status_code == 200, f"Retry failed: {retry_r.text}"
            task_id = retry_r.json()["id"]
            log.info(f"Retried as task {task_id}")
        else:
            # Already moved to RUNNING — can't cancel; just wait for original
            log.info(f"Task already past pending, continuing with original task_id={task_id}")

        try:
            result = _wait_for_terminal(task_id)
            assert result["status"] == "completed", (
                f"Task did not complete after retry: {result.get('error_message', '')[:500]}"
            )
            log.info(f"✅ cancel/retry test passed")
        finally:
            _delete_mr(TEST_PROJECT_ID, result.get("merge_request_iid") if "result" in dir() else 0)
            _delete_branch(TEST_PROJECT_ID, branch)


@skip_if_unavailable
class TestScheduledTaskExecution:
    """Integration tests for scheduled / delayed task execution."""

    def test_delayed_task_not_immediate(self):
        """A task with delay_seconds should stay PENDING until the delay elapses."""
        branch = _unique_branch("e2e-delayed")
        default_branch = _get_project_default_branch(TEST_PROJECT_ID)

        # Short delay (30s) — enough to verify it doesn't execute immediately
        delay = 30
        payload = {
            "project_id": TEST_PROJECT_ID,
            "branch_name": branch,
            "target_branch": default_branch,
            "user_prompt": "Create a file named delayed_test.txt with content: delayed",
            "priority": 0,
            "delay_seconds": delay,
        }
        r = _be("POST", "/api/tasks", json=payload)
        assert r.status_code == 200, f"Task creation failed: {r.text}"
        task = r.json()
        task_id = task["id"]
        log.info(f"Created delayed task {task_id} (delay={delay}s)")

        assert task["scheduled_at"] is not None, "Delayed task should have scheduled_at set"

        # Immediately after creation it must not be RUNNING yet
        time.sleep(3)
        status_r = _be("GET", f"/api/tasks/{task_id}")
        immediate_status = status_r.json()["status"]
        assert immediate_status in ("pending", "queued"), (
            f"Delayed task should not be running immediately, got: {immediate_status}"
        )
        log.info(f"Task {task_id} is still {immediate_status} after 3s — good")

        # Wait for it to execute after the delay
        try:
            result = _wait_for_terminal(task_id, timeout=delay + TASK_EXECUTION_TIMEOUT)
            assert result["status"] == "completed", (
                f"Delayed task did not complete: {result.get('error_message', '')[:500]}"
            )
            log.info(f"✅ delayed task test passed")
        finally:
            _delete_mr(TEST_PROJECT_ID, result.get("merge_request_iid") if "result" in dir() else 0)
            _delete_branch(TEST_PROJECT_ID, branch)

    def test_scheduled_datetime_task(self):
        """A task with scheduled_datetime ~20s in the future should execute after that time."""
        branch = _unique_branch("e2e-scheduled")
        default_branch = _get_project_default_branch(TEST_PROJECT_ID)

        # Schedule 20 seconds in the future
        run_at = (datetime.now(UTC) + timedelta(seconds=20)).isoformat()

        payload = {
            "project_id": TEST_PROJECT_ID,
            "branch_name": branch,
            "target_branch": default_branch,
            "user_prompt": "Create a file named scheduled_test.txt with content: scheduled",
            "priority": 0,
            "scheduled_datetime": run_at,
        }
        r = _be("POST", "/api/tasks", json=payload)
        assert r.status_code == 200, f"Task creation failed: {r.text}"
        task = r.json()
        task_id = task["id"]
        log.info(f"Created scheduled task {task_id} (at={run_at})")

        # Verify still pending right after creation
        time.sleep(3)
        status_r = _be("GET", f"/api/tasks/{task_id}")
        assert status_r.json()["status"] in ("pending", "queued"), (
            "Scheduled task should not run before its scheduled time"
        )

        try:
            result = _wait_for_terminal(task_id, timeout=20 + TASK_EXECUTION_TIMEOUT)
            assert result["status"] == "completed"
            log.info(f"✅ scheduled datetime task test passed")
        finally:
            _delete_mr(TEST_PROJECT_ID, result.get("merge_request_iid") if "result" in dir() else 0)
            _delete_branch(TEST_PROJECT_ID, branch)


@skip_if_unavailable
class TestTaskAPIIntegrity:
    """Fast API-level checks that don't require full worker execution."""

    def test_create_task_returns_expected_fields(self):
        """POST /api/tasks should return a task with all required fields."""
        branch = _unique_branch("e2e-api-check")
        task = _create_task(
            project_id=TEST_PROJECT_ID,
            branch_name=branch,
            user_prompt="API integrity check",
            target_branch="main",
        )

        required = ["id", "project_id", "status", "branch_name", "target_branch",
                    "user_prompt", "is_manual", "priority", "created_at"]
        for field in required:
            assert field in task, f"Missing field: {field}"

        assert task["is_manual"] is True
        assert task["status"] == "pending"
        assert task["branch_name"] == branch
        assert task["target_branch"] == "main"

        # Cancel it so it doesn't actually execute
        _be("POST", f"/api/tasks/{task['id']}/cancel")

    def test_create_no_mr_task_has_null_target_branch(self):
        """POST /api/tasks with no target_branch should return task with null target_branch."""
        branch = _unique_branch("e2e-no-mr-api")
        default_branch = _get_project_default_branch(TEST_PROJECT_ID)
        task = _create_task(
            project_id=TEST_PROJECT_ID,
            branch_name=branch,
            user_prompt="No-MR API integrity check",
            target_branch=None,
            base_branch=default_branch,
        )

        assert task["target_branch"] is None, (
            f"Expected target_branch=None for no-MR task, got: {task['target_branch']!r}"
        )
        assert task["is_manual"] is True

        _be("POST", f"/api/tasks/{task['id']}/cancel")

    def test_same_source_target_branch_rejected(self):
        """API should return 422 when source == target branch."""
        payload = {
            "project_id": TEST_PROJECT_ID,
            "branch_name": "main",
            "target_branch": "main",
            "user_prompt": "Should fail validation",
        }
        r = _be("POST", "/api/tasks", json=payload)
        assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"

    def test_cancel_nonexistent_task_returns_404(self):
        r = _be("POST", "/api/tasks/999999/cancel")
        assert r.status_code == 404

    def test_get_task_logs(self):
        """GET /api/tasks/{id}/logs should return a list."""
        branch = _unique_branch("e2e-logs-check")
        task = _create_task(
            project_id=TEST_PROJECT_ID,
            branch_name=branch,
            user_prompt="Log endpoint check",
            target_branch="main",
        )
        task_id = task["id"]

        r = _be("GET", f"/api/tasks/{task_id}/logs")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

        _be("POST", f"/api/tasks/{task_id}/cancel")

    def test_list_tasks_includes_created_task(self):
        """GET /api/tasks should include tasks we just created."""
        branch = _unique_branch("e2e-list-check")
        task = _create_task(
            project_id=TEST_PROJECT_ID,
            branch_name=branch,
            user_prompt="List endpoint check",
            target_branch="main",
        )
        task_id = task["id"]

        r = _be("GET", "/api/tasks", params={"project_id": TEST_PROJECT_ID, "limit": 50})
        assert r.status_code == 200
        task_ids = [t["id"] for t in r.json()]
        assert task_id in task_ids, f"Newly created task {task_id} not in task list"

        _be("POST", f"/api/tasks/{task_id}/cancel")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
