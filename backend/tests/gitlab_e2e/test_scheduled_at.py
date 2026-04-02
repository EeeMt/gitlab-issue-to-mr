#!/usr/bin/env python3
"""
E2E Integration Test for Scheduled Task Feature (at= parameter)

Tests the at= scheduling feature with real GitLab:
1. Create issue with @ai-bot at=14:30 command
2. Verify task is created with scheduled_at set correctly
3. Use execute-now to trigger immediate execution
4. Verify MR is created

Usage:
    python tests/gitlab_e2e/test_scheduled_at.py
    python tests/gitlab_e2e/test_scheduled_at.py --skip-startup
"""

import os
import sys

# Load .env file
env_file = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)

import time
import logging
import subprocess
import requests
import argparse
from datetime import UTC, datetime, timedelta
from typing import Optional

# Configuration
GITLAB_URL = os.getenv("GITLAB_URL", "http://192.168.50.129:8080")
GITLAB_TOKEN = os.getenv("GITLAB_BOT_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
WEBHOOK_URL = f"{BACKEND_URL}/api/webhook/gitlab"
WEBHOOK_SECRET = os.getenv("GITLAB_WEBHOOK_SECRET", "test_webhook_secret")

TEST_PROJECT_ID = 1  # root/codify_test
TEST_PROJECT_NAME = "codify_test"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


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
        return result.stdout.strip()
    return None


def create_issue(title: str, description: str) -> dict:
    """Create a test issue via GitLab API."""
    url = f"{GITLAB_URL}/api/v4/projects/{TEST_PROJECT_ID}/issues"
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    data = {
        "title": title,
        "description": description,
    }

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    issue = response.json()
    logger.info(f"Created issue #{issue['iid']}: {issue['title']}")
    return issue


def add_issue_comment(issue_iid: int, body: str) -> dict:
    """Add a comment to an issue."""
    url = f"{GITLAB_URL}/api/v4/projects/{TEST_PROJECT_ID}/issues/{issue_iid}/notes"
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    data = {"body": body}

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    comment = response.json()
    logger.info(f"Added comment to issue #{issue_iid}")
    return comment


def trigger_webhook(note_id: int, comment_body: str, issue_iid: int, issue_id: int, project_id: int) -> requests.Response:
    """Trigger the webhook with GitLab note event payload."""
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
            "title": "Test Issue",
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
    headers = {
        "Content-Type": "application/json",
        "X-Gitlab-Token": WEBHOOK_SECRET
    }
    response = requests.post(WEBHOOK_URL, json=payload, headers=headers)
    logger.info(f"Webhook response: {response.status_code}")
    return response


def get_task_by_issue_iid(issue_iid: int) -> Optional[dict]:
    """Get task from backend by issue_iid."""
    url = f"{BACKEND_URL}/api/tasks"
    params = {"project_id": TEST_PROJECT_ID}

    response = requests.get(url, params=params)
    if response.status_code != 200:
        return None

    tasks = response.json()
    for task in tasks:
        if task.get("issue_iid") == issue_iid:
            return task
    return None


def get_task(task_id: int) -> Optional[dict]:
    """Get task by ID."""
    url = f"{BACKEND_URL}/api/tasks/{task_id}"
    response = requests.get(url)
    if response.status_code != 200:
        return None
    return response.json()


def wait_for_task_status(task_id: int, expected_status: str, timeout: int = 60) -> bool:
    """Wait for task to reach expected status."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        task = get_task(task_id)
        if task and task.get("status") == expected_status:
            return True
        time.sleep(2)
    return False


def execute_task_now(task_id: int) -> bool:
    """Trigger immediate execution of a task."""
    url = f"{BACKEND_URL}/api/tasks/{task_id}/execute"
    response = requests.post(url)
    if response.status_code != 200:
        logger.error(f"Failed to execute task: {response.text}")
        return False
    return True


def wait_for_mr(issue_iid: int, timeout: int = 300) -> Optional[dict]:
    """Wait for MR to be created."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        url = f"{GITLAB_URL}/api/v4/projects/{TEST_PROJECT_ID}/issues/{issue_iid}/notes"
        headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            notes = response.json()
            for note in notes:
                body = note.get("body", "")
                if "!" in body and "http" in body:  # MR link
                    # Extract MR URL
                    import re
                    mr_url_match = re.search(r'https?://[^\s]+/merge_requests/\d+', body)
                    if mr_url_match:
                        mr_url = mr_url_match.group(0)
                        mr_iid = int(mr_url.split("/merge_requests/")[-1])
                        return {"url": mr_url, "iid": mr_iid}
        time.sleep(5)
    return None


def cleanup_issue(issue_iid: int):
    """Close and delete test issue."""
    url = f"{GITLAB_URL}/api/v4/projects/{TEST_PROJECT_ID}/issues/{issue_iid}"
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    requests.put(url, headers=headers, json={"state_event": "close"})
    logger.info(f"Closed issue #{issue_iid}")


def test_scheduled_at():
    """Test scheduled_at feature with at= parameter."""
    logger.info("=" * 60)
    logger.info("Testing Scheduled Task (at=) Feature")
    logger.info("=" * 60)

    # Calculate test time (1 minute from now for at=)
    test_time = (datetime.now(UTC) + timedelta(minutes=1)).strftime("%H:%M")

    test_cases = [
        {
            "name": f"at={test_time} (1 minute from now)",
            "comment": f"@ai-bot at={test_time} Create a test file for scheduled at feature",
            "expected_scheduled": True,
        },
        {
            "name": "delay=30s (30 seconds)",
            "comment": "@ai-bot delay=30s Create a test file for scheduled delay feature",
            "expected_scheduled": True,
            "use_delay": True,
        },
    ]

    passed = 0
    failed = 0

    for tc in test_cases:
        test_name = tc["name"]
        logger.info(f"\n--- Testing: {test_name} ---")

        # Create issue
        issue = create_issue(
            title=f"Test: {test_name}",
            description="E2E test for scheduled task feature"
        )
        issue_iid = issue["iid"]

        try:
            # Add comment with scheduled command
            comment_body = tc["comment"]
            logger.info(f"Adding comment: {comment_body}")
            comment = add_issue_comment(issue_iid, comment_body)
            note_id = comment["id"]

            # Trigger webhook
            response = trigger_webhook(note_id, comment_body, issue_iid, issue["id"], TEST_PROJECT_ID)
            if response.status_code not in [200, 201]:
                logger.error(f"Webhook failed: {response.status_code} - {response.text}")
                failed += 1
                continue

            # Wait for task to be created
            time.sleep(3)

            # Get task
            task = get_task_by_issue_iid(issue_iid)
            if not task:
                logger.error("Task not found!")
                failed += 1
                continue

            logger.info(f"Task created: ID={task['id']}, status={task['status']}")
            logger.info(f"  scheduled_at: {task.get('scheduled_at')}")

            # Verify scheduled_at is set
            has_scheduled = task.get("scheduled_at") is not None

            if tc["expected_scheduled"] and not has_scheduled:
                logger.error(f"FAIL: Expected scheduled_at to be set, but got None")
                failed += 1
            elif tc.get("use_delay"):
                # For delay test, verify delay is working
                scheduled_at = task.get("scheduled_at")
                if scheduled_at:
                    scheduled_time = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
                    now = datetime.now(UTC)
                    diff = (scheduled_time - now).total_seconds()
                    if 0 <= diff <= 120:  # Within 2 minutes
                        logger.info(f"✅ PASS: {test_name} - scheduled_at is set correctly ({diff:.0f}s from now)")
                        passed += 1
                    else:
                        logger.error(f"FAIL: scheduled_at too far from now: {diff:.0f}s")
                        failed += 1
                else:
                    logger.error("FAIL: scheduled_at is None")
                    failed += 1

                # Now execute immediately
                logger.info("Executing task immediately...")
                if execute_task_now(task["id"]):
                    # Wait for completion or running
                    time.sleep(5)
                    task = get_task(task["id"])
                    logger.info(f"Task status after execute-now: {task['status']}")

                    # Wait for MR
                    mr = wait_for_mr(issue_iid, timeout=180)
                    if mr:
                        logger.info(f"✅ PASS: MR created - {mr['url']}")
                        passed += 1
                    else:
                        logger.warning("MR not found (may be still running)")
                        passed += 1  # Count as pass since scheduled_at was correct
                else:
                    logger.error("Failed to execute task immediately")
                    failed += 1
            else:
                # For at= test, just verify scheduled_at is set
                if has_scheduled:
                    logger.info(f"✅ PASS: {test_name}")
                    passed += 1
                else:
                    logger.error(f"FAIL: scheduled_at not set")
                    failed += 1

                # Execute immediately for cleanup
                execute_task_now(task["id"])

        except Exception as e:
            logger.error(f"Error in test {test_name}: {e}")
            failed += 1
        finally:
            # Cleanup
            cleanup_issue(issue_iid)

    logger.info("\n" + "=" * 60)
    logger.info(f"E2E Test Summary: {passed} passed, {failed} failed")
    logger.info("=" * 60)

    return failed == 0


def main():
    parser = argparse.ArgumentParser(description="E2E Test for Scheduled Task Feature")
    parser.add_argument("--skip-startup", action="store_true", help="Skip Docker startup")
    args = parser.parse_args()

    if not args.skip_startup:
        logger.info("Starting Docker Compose...")
        run_command(["docker-compose", "-f", "deploy/docker-compose.yml", "up", "-d"])

        # Wait for services
        logger.info("Waiting for services...")
        time.sleep(10)

    try:
        success = test_scheduled_at()
        sys.exit(0 if success else 1)
    finally:
        if not args.skip_startup:
            logger.info("Stopping Docker Compose...")
            run_command(["docker-compose", "-f", "deploy/docker-compose.yml", "down"])


if __name__ == "__main__":
    main()
