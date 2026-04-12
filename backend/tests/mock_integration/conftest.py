"""Shared fixtures for mock integration tests.

These tests run against real Docker containers orchestrated by docker-compose.
External services (GitLab, Claude) are mocked by the mock-services container.
"""

import asyncio
import json
import logging
import os
import subprocess
import time
from typing import Any

import httpx
import pytest

logger = logging.getLogger(__name__)


def _detect_docker_host_ip() -> str:
    """Detect the Docker host IP from the active Docker context.

    When using a remote Docker context (ssh://root@host), we need to connect
    to that host's IP for port-mapped services, not localhost.
    """
    try:
        result = subprocess.run(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            capture_output=True, text=True, timeout=5,
        )
        host_url = result.stdout.strip()
        if host_url.startswith("ssh://"):
            # ssh://root@192.168.50.129 → 192.168.50.129
            return host_url.split("@")[-1]
        if host_url.startswith("tcp://"):
            # tcp://192.168.50.129:2376 → 192.168.50.129
            return host_url.replace("tcp://", "").split(":")[0]
    except Exception:
        pass
    return "localhost"


DOCKER_HOST_IP = os.environ.get("DOCKER_HOST_IP", _detect_docker_host_ip())

# Service URLs — use docker host IP with mapped ports
BACKEND_URL = os.environ.get("MOCK_TEST_BACKEND_URL", f"http://{DOCKER_HOST_IP}:18000")
MOCK_SERVICES_URL = os.environ.get("MOCK_TEST_MOCK_URL", f"http://{DOCKER_HOST_IP}:19000")

# Webhook secret matching docker-compose.mock-test.yml
WEBHOOK_SECRET = "mock-webhook-secret"
GITLAB_BOT_TOKEN = "mock-token-12345"


@pytest.fixture(scope="session")
def backend_url() -> str:
    return BACKEND_URL


@pytest.fixture(scope="session")
def mock_url() -> str:
    return MOCK_SERVICES_URL


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop for async fixtures."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def http_client():
    """Per-test HTTP client (avoids event loop closed issues)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        yield client


@pytest.fixture(autouse=True)
async def reset_mock_state(mock_url: str):
    """Reset mock server state before each test: clear call logs, reset config, reinit git."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.delete(f"{mock_url}/mock/calls")
        assert resp.status_code == 200, f"Failed to reset mock calls: {resp.status_code}"
        resp = await client.patch(
            f"{mock_url}/mock/config",
            json={
                "claude_exit_code": 0,
                "claude_delay_seconds": 0,
                "claude_skip_files": False,
                "fail_git_push": False,
                "fail_git_clone": False,
                "fail_mr_update": False,
                "fail_mr_creation": False,
                "fail_project_lookup": False,
                "fail_issue_notes": False,
            },
        )
        assert resp.status_code == 200, f"Failed to reset mock config: {resp.status_code}"
        resp = await client.post(f"{mock_url}/mock/reset-git")
        assert resp.status_code == 200, f"Failed to reset git repos: {resp.status_code}"
    yield


@pytest.fixture
async def admin_auth_headers(backend_url: str) -> dict:
    """Get authentication headers by logging in as admin.

    The backend requires initial registration via /auth/local/register when
    system is not yet initialized. After that, login via /auth/local/login.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Try to login first (system may already be initialized from previous test)
        resp = await client.post(
            f"{backend_url}/api/auth/local/login",
            json={"username": "admin", "password": "admin123"},
        )
        if resp.status_code == 200:
            cookies = dict(resp.cookies)
            if cookies:
                return {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}
            token = resp.json().get("access_token")
            if token:
                return {"Authorization": f"Bearer {token}"}

        # Register first admin user (system not yet initialized)
        resp = await client.post(
            f"{backend_url}/api/auth/local/register",
            json={"username": "admin", "password": "admin123"},
        )
        if resp.status_code in (200, 201):
            cookies = dict(resp.cookies)
            if cookies:
                return {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}
            token = resp.json().get("access_token")
            if token:
                return {"Authorization": f"Bearer {token}"}

    pytest.skip(f"Could not authenticate: register={resp.status_code} {resp.text}")


def build_webhook_payload(
    project_id: int = 1,
    issue_iid: int = 1,
    prompt: str = "Create a hello.py file",
    action: str = "comment",
    object_kind: str = "note",
    noteable_type: str = "Issue",
) -> dict:
    """Build a GitLab webhook payload for issue comment."""
    return {
        "object_kind": object_kind,
        "event_type": "note",
        "user": {
            "id": 42,
            "name": "Test User",
            "username": "testuser",
            "avatar_url": "",
        },
        "project": {
            "id": project_id,
            "name": "test-project",
            "path_with_namespace": "test-group/test-project",
            "web_url": "http://mock-services:9000/test-group/test-project",
            "default_branch": "main",
        },
        "object_attributes": {
            "id": int(time.time()),
            "note": f"@ai-bot {prompt}",
            "noteable_type": noteable_type,
            "action": action,
        },
        "issue": {
            "id": issue_iid * 1000,
            "iid": issue_iid,
            "title": f"Test Issue #{issue_iid}",
            "state": "opened",
            "action": "open",
        },
    }


async def send_webhook(
    client: httpx.AsyncClient,
    backend_url: str,
    payload: dict,
    secret: str = WEBHOOK_SECRET,
) -> httpx.Response:
    """Send a signed webhook to the backend."""
    body = json.dumps(payload, separators=(",", ":"))
    return await client.post(
        f"{backend_url}/api/webhook/gitlab",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Gitlab-Token": secret,
            "X-Gitlab-Event": "Note Hook",
        },
    )


async def wait_for_task_status(
    client: httpx.AsyncClient,
    backend_url: str,
    task_id: int,
    target_statuses: list[str],
    auth_headers: dict,
    timeout: float = 120.0,
    poll_interval: float = 2.0,
) -> dict:
    """Poll task status until it reaches one of the target statuses."""
    start = time.time()
    last_status = None
    while time.time() - start < timeout:
        resp = await client.get(
            f"{backend_url}/api/tasks/{task_id}",
            headers=auth_headers,
        )
        if resp.status_code == 200:
            task = resp.json()
            status = task.get("status")
            if status != last_status:
                logger.info(f"Task {task_id} status: {status}")
                last_status = status
            if status in target_statuses:
                return task
        await asyncio.sleep(poll_interval)

    pytest.fail(
        f"Task {task_id} did not reach {target_statuses} within {timeout}s. "
        f"Last status: {last_status}"
    )


async def get_mock_calls(
    client: httpx.AsyncClient,
    mock_url: str,
    service: str | None = None,
) -> list[dict]:
    """Get recorded calls from mock server."""
    params = {}
    if service:
        params["service"] = service
    resp = await client.get(f"{mock_url}/mock/calls", params=params)
    return resp.json()
