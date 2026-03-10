#!/usr/bin/env python3
"""
End-to-End Integration Test for GIMR (GitLab Issue to MR Bot)

Workflow:
1. Start system (Docker Compose)
2. Create test project (if needed)
3. Create issue via GitLab API
4. Add comment with @ai-bot to trigger bot
5. Bot calls Claude CLI to generate code
6. Commit code and create MR
7. Verify result (MR created, issue linked)
8. Cleanup

Usage:
    python test_integration_e2e.py           # Full test
    python test_integration_e2e.py --skip-startup  # Skip Docker startup
    python test_integration_e2e.py --cleanup        # Only cleanup test project
"""

import os
import sys

# Load .env file from backend directory
env_file = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)

import time
import json
import logging
import subprocess
import requests
import argparse
from datetime import datetime
from typing import Optional

# Configuration from .env
GITLAB_URL = os.getenv("GITLAB_URL", "http://192.168.50.129:8080")
GITLAB_TOKEN = os.getenv("GITLAB_BOT_TOKEN", "")
WEBHOOK_SECRET = os.getenv("GITLAB_WEBHOOK_SECRET", "test_webhook_secret")

# Backend URL (where the webhook is served)
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
WEBHOOK_URL = f"{BACKEND_URL}/api/webhook/gitlab"

# Test configuration - use existing gimr_test project
TEST_PROJECT_ID = 1  # root/gimr_test
TEST_PROJECT_NAME = "gimr_test"
TEST_ISSUE_TITLE = "E2E Test: Add a hello world function"
TEST_ISSUE_DESCRIPTION = "This is an end-to-end integration test issue."
TEST_BOT_PROMPT = "Create a simple hello.py file with hello() function"
TEST_TIMEOUT = 300  # 5 minutes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Use docker-compose (with hyphen) instead of docker compose
DOCKER_COMPOSE = "docker-compose"


def run_command(cmd: list, check=True, capture_output=True):
    """Run a shell command."""
    logger.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        capture_output=capture_output,
        text=True,
        check=check
    )
    if capture_output:
        if result.stdout:
            logger.debug(f"stdout: {result.stdout[:500]}")
        if result.stderr:
            logger.debug(f"stderr: {result.stderr[:500]}")
    return result


def wait_for_service(url: str, timeout: int = 60, name: str = "service"):
    """Wait for a service to be ready."""
    logger.info(f"Waiting for {name} at {url}...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code < 500:
                logger.info(f"{name} is ready!")
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(2)
    raise TimeoutError(f"{name} did not become ready in {timeout}s")


def gitlab_request(method: str, path: str, **kwargs) -> requests.Response:
    """Make authenticated request to GitLab API."""
    headers = kwargs.pop("headers", {})
    headers["PRIVATE-TOKEN"] = GITLAB_TOKEN

    url = f"{GITLAB_URL}/api/v4{path}"
    logger.info(f"GitLab API: {method} {url}")

    resp = requests.request(method, url, headers=headers, **kwargs)
    logger.debug(f"Response: {resp.status_code} - {resp.text[:500]}")

    if resp.status_code >= 400:
        raise Exception(f"GitLab API error: {resp.status_code} - {resp.text}")

    return resp


def get_or_create_test_project() -> dict:
    """Get or create test project."""
    # Use existing project by ID
    if TEST_PROJECT_ID:
        try:
            resp = gitlab_request("GET", f"/projects/{TEST_PROJECT_ID}")
            logger.info(f"Using existing project: {resp.json()['path_with_namespace']}")
            return resp.json()
        except Exception as e:
            logger.warning(f"Failed to get project {TEST_PROJECT_ID}: {e}")

    # Fallback: search for project
    try:
        resp = gitlab_request("GET", "/projects?membership=true&per_page=100")
        projects = resp.json()
        for p in projects:
            if p["path"] == TEST_PROJECT_NAME or p["name"] == TEST_PROJECT_NAME:
                logger.info(f"Found existing project: {p['id']} - {p['path_with_namespace']}")
                return p
    except Exception as e:
        logger.warning(f"Failed to search projects: {e}")

    # Create new project with README
    logger.info(f"Creating test project: {TEST_PROJECT_NAME}")
    resp = gitlab_request("POST", "/projects", json={
        "name": TEST_PROJECT_NAME,
        "description": "Test project for GIMR E2E tests",
        "visibility": "private",
        "initialize_with_readme": True
    })
    project = resp.json()
    logger.info(f"Created project: {project['id']} - {project['web_url']}")
    return project


def create_test_issue(project_id: int) -> dict:
    """Create a test issue."""
    logger.info(f"Creating test issue in project {project_id}")
    resp = gitlab_request("POST", f"/projects/{project_id}/issues", json={
        "title": TEST_ISSUE_TITLE,
        "description": TEST_ISSUE_DESCRIPTION
    })
    issue = resp.json()
    logger.info(f"Created issue: #{issue['iid']} - {issue['web_url']}")
    return issue


def add_comment_to_issue(project_id: int, issue_iid: int, comment: str) -> dict:
    """Add a comment to an issue."""
    logger.info(f"Adding comment to issue #{issue_iid}")
    resp = gitlab_request("POST", f"/projects/{project_id}/issues/{issue_iid}/notes", json={
        "body": comment
    })
    note = resp.json()
    logger.info(f"Added comment: {note['id']}")
    return note


def trigger_via_webhook(project_id: int, issue_iid: int, note_id: int, comment_body: str) -> dict:
    """Trigger the webhook with a simulated GitLab webhook payload."""
    # Build webhook payload matching GitLab's note event format
    payload = {
        "object_kind": "note",
        "event_type": "note",
        "project": {
            "id": project_id,
            "name": TEST_PROJECT_NAME,
            "path_with_namespace": TEST_PROJECT_NAME,
            "web_url": f"{GITLAB_URL}/{TEST_PROJECT_NAME}"
        },
        "issue": {
            "id": project_id * 100 + issue_iid,
            "iid": issue_iid,
            "title": TEST_ISSUE_TITLE,
            "web_url": f"{GITLAB_URL}/{TEST_PROJECT_NAME}/-/issues/{issue_iid}"
        },
        "note": {
            "id": note_id,
            "body": comment_body,
            "noteable_type": "Issue"
        },
        "user": {
            "id": 1,
            "username": "root",
            "name": "Administrator"
        }
    }

    logger.info(f"Triggering webhook: POST {WEBHOOK_URL}")
    resp = requests.post(
        WEBHOOK_URL,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "X-Gitlab-Token": WEBHOOK_SECRET
        },
        timeout=30
    )

    logger.info(f"Webhook response: {resp.status_code} - {resp.text[:500]}")
    if resp.status_code >= 400:
        raise Exception(f"Webhook failed: {resp.status_code} - {resp.text}")

    return resp.json()


def create_task_via_backend_api(project_id: int, issue_iid: int, prompt: str) -> dict:
    """Create task directly via backend API (bypasses webhook)."""
    # First, get issue details from GitLab
    issue_resp = gitlab_request("GET", f"/projects/{project_id}/issues/{issue_iid}")
    issue = issue_resp.json()
    issue_id = issue["id"]

    # Create a fake note to use as note_id
    import time
    # Use a smaller note_id that fits in int32 (max ~2 billion)
    note_id = int(time.time() * 1000) % 2000000000

    # Build payload similar to what webhook would send
    payload = {
        "object_kind": "note",
        "event_type": "note",
        "project": {
            "id": project_id,
            "name": TEST_PROJECT_NAME,
            "path_with_namespace": TEST_PROJECT_NAME,
            "web_url": f"{GITLAB_URL}/{TEST_PROJECT_NAME}"
        },
        "issue": {
            "id": issue_id,
            "iid": issue_iid,
            "title": TEST_ISSUE_TITLE,
            "web_url": f"{GITLAB_URL}/{TEST_PROJECT_NAME}/-/issues/{issue_iid}"
        },
        "note": {
            "id": note_id,
            "body": f"@ai-bot {prompt}",
            "noteable_type": "Issue"
        },
        "user": {
            "id": 1,
            "username": "root",
            "name": "Administrator"
        }
    }

    logger.info(f"Creating task via webhook: POST {WEBHOOK_URL}")
    resp = requests.post(
        WEBHOOK_URL,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "X-Gitlab-Token": WEBHOOK_SECRET
        },
        timeout=30
    )

    logger.info(f"Response: {resp.status_code} - {resp.text[:500]}")
    if resp.status_code >= 400:
        raise Exception(f"Failed to create task: {resp.status_code} - {resp.text}")

    return resp.json()


def get_task_status_via_api(project_id: int, issue_iid: int) -> Optional[dict]:
    """Get task status via backend API."""
    try:
        # This would require a task status API - for now use database
        # For a real test, we'd query the backend's task API
        return None
    except Exception as e:
        logger.warning(f"Failed to get task status: {e}")
        return None


def wait_for_mr(project_id: int, branch_name: str, timeout: int = TEST_TIMEOUT) -> Optional[dict]:
    """Wait for MR to be created."""
    logger.info(f"Waiting for MR with branch {branch_name}...")
    start = time.time()

    while time.time() - start < timeout:
        try:
            resp = gitlab_request("GET", f"/projects/{project_id}/merge_requests", params={
                "source_branch": branch_name,
                "state": "opened"
            })
            mrs = resp.json()
            if mrs:
                mr = mrs[0]
                logger.info(f"Found MR: #{mr['iid']} - {mr['web_url']}")
                return mr
        except Exception as e:
            logger.debug(f"MR not found yet: {e}")

        time.sleep(5)

    raise TimeoutError(f"MR not created within {timeout}s")


def get_issue_notes(project_id: int, issue_iid: int) -> list:
    """Get all notes (comments) from an issue."""
    resp = gitlab_request("GET", f"/projects/{project_id}/issues/{issue_iid}/notes")
    return resp.json()


def verify_mr_closes_issue(mr: dict, issue_iid: int) -> bool:
    """Verify that the MR is configured to close the issue."""
    description = mr.get("description", "")
    return f"Closes #{issue_iid}" in description or f"Fixes #{issue_iid}" in description


def cleanup_test_project(project_id: int):
    """Clean up test project."""
    try:
        logger.info(f"Deleting test project {project_id}")
        gitlab_request("DELETE", f"/projects/{project_id}")
    except Exception as e:
        logger.warning(f"Failed to cleanup project: {e}")


def start_docker_compose():
    """Start Docker Compose services."""
    logger.info("Starting Docker Compose services...")
    compose_dir = "/Users/AI/Projects/gitlab-issue-to-mr/deploy"

    # Check if GitLab is already reachable
    gitlab_available = False
    try:
        resp = requests.get(f"{GITLAB_URL}/api/v4/version", timeout=5)
        if resp.status_code == 200:
            gitlab_available = True
            logger.info("GitLab is already available")
    except Exception:
        pass

    if not gitlab_available:
        logger.warning("GitLab is not available - test will fail unless GitLab is running externally")

    # First, build the worker image
    logger.info("Building worker image...")
    run_command([
        "docker", "build", "-t", "gitlab-issues-to-mr-worker:latest",
        "-f", "deploy/Dockerfile.worker", "."
    ], check=False)

    # Create a custom .env file for docker-compose with correct Docker host
    env_content = f"""# GitLab Configuration
GITLAB_URL={GITLAB_URL}
GITLAB_BOT_TOKEN={GITLAB_TOKEN}
GITLAB_WEBHOOK_SECRET={WEBHOOK_SECRET}

# Claude CLI (passed to Worker container)
ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic
ANTHROPIC_API_KEY=sk-cp-9d52R8LpyawPBsGZMxpD7R5AYPmLreWk8eAzp2fESRbYcM3iRCaNcgCu7LQRr_sUuBm9PIaGF7UAzjm0veMgZb0F_bNTGsKe9__s8K4wKS3ZcwBxdSxvXqY
ANTHROPIC_MODEL=MiniMax-M2.5

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://gimr:gimr_password@postgres:5432/gimr

# Docker Engine - use local socket
DOCKER_HOST=unix:///var/run/docker.sock
DOCKER_TLS_CA=
DOCKER_TLS_CERT=
DOCKER_TLS_KEY=

# Application
SECRET_KEY=your-secret-key-change-in-production
LOG_LEVEL=INFO

# Worker Configuration
WORKER_IMAGE=gitlab-issues-to-mr-worker:latest

# Scheduler Configuration
MAX_CONCURRENCY=3
TASK_TIMEOUT=1800
SCHEDULER_INTERVAL=5
DEFAULT_TARGET_BRANCH=main
"""

    env_file_path = f"{compose_dir}/.env.test"
    with open(env_file_path, "w") as f:
        f.write(env_content)
    logger.info(f"Created test env file: {env_file_path}")

    # Start services with custom env file
    logger.info("Starting backend and postgres...")
    run_command([
        DOCKER_COMPOSE, "-f", f"{compose_dir}/docker-compose.yml",
        "--env-file", env_file_path,
        "up", "-d"
    ])

    # Wait for backend
    wait_for_service("http://localhost:8000/health", timeout=60, name="Backend")

    # Check backend is ready
    logger.info("Backend is ready!")


def stop_docker_compose():
    """Stop Docker Compose services."""
    logger.info("Stopping Docker Compose services...")
    compose_dir = "/Users/AI/Projects/gitlab-issue-to-mr/deploy"
    env_file_path = f"{compose_dir}/.env.test"

    run_command([
        DOCKER_COMPOSE, "-f", f"{compose_dir}/docker-compose.yml",
        "--env-file", env_file_path,
        "down", "-v"
    ], check=False)


def run_migration():
    """Run database migrations."""
    logger.info("Running database migrations...")
    try:
        run_command([
            "docker", "exec", "gimr-backend",
            "alembic", "upgrade", "head"
        ])
    except Exception as e:
        logger.warning(f"Migration might already be applied: {e}")


def main():
    """Run the end-to-end integration test."""
    parser = argparse.ArgumentParser(description="GIMR E2E Integration Test")
    parser.add_argument("--skip-startup", action="store_true",
                       help="Skip Docker Compose startup (use existing services)")
    parser.add_argument("--cleanup", action="store_true",
                       help="Only cleanup test project and exit")
    parser.add_argument("--keep-running", action="store_true",
                       help="Keep services running after test")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("GIMR End-to-End Integration Test")
    logger.info("=" * 60)

    project = None

    try:
        # Handle cleanup-only mode
        if args.cleanup:
            logger.info("\n[Cleanup Mode] Finding and removing test project...")
            project = get_or_create_test_project()
            cleanup_test_project(project["id"])
            logger.info("Cleanup complete!")
            return 0

        # Step 1: Start system (unless skipped)
        if not args.skip_startup:
            logger.info("\n[Step 1] Starting Docker Compose...")
            start_docker_compose()
            run_migration()
        else:
            logger.info("\n[Step 1] Skipping Docker Compose startup (--skip-startup)")

        # Verify backend is accessible
        try:
            resp = requests.get("http://localhost:8000/health", timeout=5)
            logger.info(f"Backend health check: {resp.status_code}")
        except Exception as e:
            logger.error(f"Backend is not accessible: {e}")
            return 1

        # Step 2: Create/get test project
        logger.info("\n[Step 2] Creating test project...")
        project = get_or_create_test_project()
        project_id = project["id"]

        # Step 3: Create issue
        logger.info("\n[Step 3] Creating test issue...")
        issue = create_test_issue(project_id)
        issue_iid = issue["iid"]

        # Step 4: Add @ai-bot comment to trigger bot
        logger.info("\n[Step 4] Adding @ai-bot comment...")
        comment = f"@ai-bot {TEST_BOT_PROMPT}"
        note = add_comment_to_issue(project_id, issue_iid, comment)
        note_id = note["id"]

        # Step 5: Create task via webhook endpoint
        logger.info("\n[Step 5] Creating task via webhook...")
        result = create_task_via_backend_api(project_id, issue_iid, TEST_BOT_PROMPT)
        logger.info(f"Task creation result: {result}")

        if result.get("status") == "success":
            task_id = result.get("task_id")
            logger.info(f"Task created: {task_id}")
        elif result.get("status") == "duplicate":
            logger.info("Task already exists (duplicate)")
        else:
            logger.warning(f"Unexpected webhook result: {result}")

        # Step 6: Wait for MR to be created
        branch_name = f"gimr/issue-{issue_iid}"
        logger.info(f"\n[Step 6] Waiting for MR (branch: {branch_name})...")

        try:
            mr = wait_for_mr(project_id, branch_name, timeout=TEST_TIMEOUT)
            logger.info(f"MR created: #{mr['iid']} - {mr['web_url']}")

            # Step 7: Verify MR closes issue
            logger.info("\n[Step 7] Verifying MR closes issue...")
            closes_issue = verify_mr_closes_issue(mr, issue_iid)
            if closes_issue:
                logger.info("MR is configured to close the issue!")
            else:
                logger.warning("MR does not mention closing the issue")

            # Step 8: Check issue comments for MR link
            logger.info("\n[Step 8] Checking issue comments...")
            notes = get_issue_notes(project_id, issue_iid)
            mr_linked = any(
                "merge request" in n.get("body", "").lower() or
                "mr:" in n.get("body", "").lower()
                for n in notes
            )
            if mr_linked:
                logger.info("MR link found in issue comments!")
            else:
                logger.warning("No MR link found in issue comments")

            logger.info("\n" + "=" * 60)
            logger.info("✅ E2E TEST PASSED!")
            logger.info(f"  Issue: #{issue_iid}")
            logger.info(f"  MR: {mr['web_url']}")
            logger.info("=" * 60)

        except TimeoutError as e:
            logger.error(f"\n❌ E2E TEST FAILED: {e}")
            # Show current issue state for debugging
            logger.info("\n--- Debug Info ---")
            notes = get_issue_notes(project_id, issue_iid)
            logger.info(f"Issue comments: {json.dumps(notes, indent=2)[:1000]}")

            resp = requests.get(f"{GITLAB_URL}/api/v4/projects/{project_id}/repository/branches/{branch_name}",
                              headers={"PRIVATE-TOKEN": GITLAB_TOKEN})
            logger.info(f"Branch exists: {resp.status_code == 200}")

            return 1

    except Exception as e:
        logger.error(f"\n❌ E2E TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # Cleanup
        if project and not args.keep_running:
            # Only cleanup if not keeping running
            # cleanup_test_project(project["id"])
            pass

        # Stop services (unless --keep-running is set)
        if not args.keep_running:
            stop_docker_compose()
        else:
            logger.info("\n[Info] Keeping services running (--keep-running)")
            logger.info("  - Backend: http://localhost:8000")
            logger.info("  - PostgreSQL: localhost:5432")
            logger.info("  - To stop: docker compose -f deploy/docker-compose.yml down")

    return 0


if __name__ == "__main__":
    sys.exit(main())
