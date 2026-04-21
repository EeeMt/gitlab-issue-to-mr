#!/usr/bin/env python3
"""
E2E Integration Tests for Slot Capacity Feature

Tests the slot_max_tasks / slot_max_tasks_enforce behaviour against a real
backend + GitLab instance.

Scenarios covered:
  1. Config round-trip (PATCH + GET)
  2. Enforce mode rejects the Nth webhook that exceeds the slot limit
  3. Soft mode (enforce=False) allows all webhooks
  4. Disabled mode (slot_max_tasks=0) allows unlimited webhooks
  5. Different 1-hour slots are counted independently
  6. GET /api/tasks/slot-capacity returns correct capacity info

Usage:
    cd backend && source .venv/bin/activate
    pytest tests/gitlab_e2e/test_slot_capacity_e2e.py -v
"""

import os
import sys
import time
import logging
import requests
import pytest
from datetime import UTC, datetime, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Load .env file (same pattern as test_scheduled_at.py)
# ---------------------------------------------------------------------------
env_file = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GITLAB_URL = os.getenv("GITLAB_URL", "http://192.168.50.129:8080")
GITLAB_TOKEN = os.getenv("GITLAB_BOT_TOKEN", "")
BACKEND_URL = os.getenv("E2E_BACKEND_URL", os.getenv("BACKEND_URL", "http://localhost:8000"))
WEBHOOK_URL = f"{BACKEND_URL}/api/webhook/gitlab"
WEBHOOK_SECRET = os.getenv("GITLAB_WEBHOOK_SECRET", "test_webhook_secret")

TEST_PROJECT_ID = 1  # root/codify_test
TEST_PROJECT_NAME = "codify_test"

_TEST_USERNAME = "test_admin_slot_e2e"
_TEST_PASSWORD = "SecurePass123!"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Monotonically increasing counters so every webhook gets unique IDs.
# Use modulo to stay within PostgreSQL int4 range (max 2_147_483_647).
_note_counter = int(time.time()) % 1_000_000_000
_issue_counter = int(time.time()) % 1_000_000_000


def _next_note_id() -> int:
    global _note_counter
    _note_counter += 1
    return _note_counter


def _next_issue_ids() -> tuple[int, int]:
    """Return a unique (issue_id, issue_iid) pair."""
    global _issue_counter
    _issue_counter += 1
    return _issue_counter, _issue_counter


# ---------------------------------------------------------------------------
# Availability probes
# ---------------------------------------------------------------------------

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


def _backend_available() -> bool:
    try:
        r = requests.get(f"{BACKEND_URL}/api/stats", timeout=5)
        return r.status_code in (200, 401)
    except Exception:
        return False


_gitlab_up = _gitlab_available()
_backend_up = _backend_available()

skip_if_unavailable = pytest.mark.skipif(
    not (_gitlab_up and _backend_up),
    reason="GitLab or backend not reachable — skipping slot-capacity E2E tests",
)


# ---------------------------------------------------------------------------
# Authenticated backend session (singleton)
# ---------------------------------------------------------------------------
_be_session: Optional[requests.Session] = None


def _get_be_session() -> requests.Session:
    """Return a persistent requests.Session authenticated with the backend."""
    global _be_session
    if _be_session is not None:
        return _be_session

    session = requests.Session()
    try:
        bootstrap = requests.get(
            f"{BACKEND_URL}/api/auth/bootstrap-status", timeout=10,
        ).json()
        if not bootstrap.get("initialized"):
            session.post(
                f"{BACKEND_URL}/api/auth/local/register",
                json={
                    "username": _TEST_USERNAME,
                    "display_name": "Slot Capacity E2E Admin",
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
        pytest.skip(f"Backend login failed ({resp.status_code}) — run against E2E environment")

    _be_session = session
    return session


def _be(method: str, path: str, **kwargs) -> requests.Response:
    """Execute a backend API call with session auth."""
    return _get_be_session().request(method, f"{BACKEND_URL}{path}", timeout=30, **kwargs)


# ---------------------------------------------------------------------------
# GitLab helpers
# ---------------------------------------------------------------------------

def create_issue(title: str, description: str = "Slot-capacity E2E test") -> dict:
    """Create a test issue on GitLab and return its JSON."""
    url = f"{GITLAB_URL}/api/v4/projects/{TEST_PROJECT_ID}/issues"
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    resp = requests.post(url, headers=headers, json={"title": title, "description": description})
    resp.raise_for_status()
    issue = resp.json()
    logger.info("Created GitLab issue #%s: %s", issue["iid"], issue["title"])
    return issue


def get_issue_notes(issue_iid: int) -> list[dict]:
    """Return all notes/comments on a GitLab issue."""
    url = f"{GITLAB_URL}/api/v4/projects/{TEST_PROJECT_ID}/issues/{issue_iid}/notes"
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    resp = requests.get(url, headers=headers, params={"per_page": 100})
    resp.raise_for_status()
    return resp.json()


def cleanup_issue(issue_iid: int) -> None:
    """Close a test issue (best-effort)."""
    url = f"{GITLAB_URL}/api/v4/projects/{TEST_PROJECT_ID}/issues/{issue_iid}"
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    try:
        requests.put(url, headers=headers, json={"state_event": "close"}, timeout=10)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Webhook helper
# ---------------------------------------------------------------------------

def trigger_webhook(
    note_id: int,
    comment_body: str,
    issue_iid: int,
    issue_id: int,
    project_id: int = TEST_PROJECT_ID,
) -> requests.Response:
    """Send a GitLab note-event webhook to the backend."""
    payload = {
        "object_kind": "note",
        "event_type": "note",
        "project": {
            "id": project_id,
            "name": TEST_PROJECT_NAME,
            "path_with_namespace": TEST_PROJECT_NAME,
            "web_url": f"{GITLAB_URL}/{TEST_PROJECT_NAME}",
        },
        "object_attributes": {
            "id": note_id,
            "note": comment_body,
            "noteable_type": "Issue",
            "action": "create",
        },
        "issue": {
            "id": issue_id,
            "iid": issue_iid,
            "title": "Slot Capacity Test Issue",
            "web_url": f"{GITLAB_URL}/{TEST_PROJECT_NAME}/-/issues/{issue_iid}",
        },
        "user": {"id": 1, "username": "root", "name": "Administrator"},
    }
    headers = {
        "Content-Type": "application/json",
        "X-Gitlab-Token": WEBHOOK_SECRET,
    }
    resp = requests.post(WEBHOOK_URL, json=payload, headers=headers, timeout=30)
    logger.info(
        "Webhook for issue #%s  note=%s  → %s %s",
        issue_iid, note_id, resp.status_code, resp.text[:200],
    )
    return resp


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def set_slot_config(max_tasks: int, enforce: bool) -> None:
    """PATCH slot capacity settings on the backend and verify they took effect."""
    resp = _be("PATCH", "/api/config/runtime", json={
        "slot_max_tasks": max_tasks,
        "slot_max_tasks_enforce": enforce,
    })
    assert resp.status_code == 200, f"Failed to set slot config: {resp.status_code} {resp.text}"

    # Verify the config was applied (guards against multi-worker race)
    for attempt in range(3):
        verify = _be("GET", "/api/config/runtime")
        body = verify.json()
        if body.get("slot_max_tasks") == max_tasks and body.get("slot_max_tasks_enforce") == enforce:
            break
        time.sleep(0.5)
    else:
        actual = (body.get("slot_max_tasks"), body.get("slot_max_tasks_enforce"))
        raise AssertionError(
            f"Config verification failed after PATCH: expected ({max_tasks}, {enforce}), "
            f"got {actual}"
        )
    logger.info("Set slot config → max_tasks=%s, enforce=%s (verified)", max_tasks, enforce)


def reset_slot_config() -> None:
    """Reset slot capacity to defaults (disabled)."""
    try:
        set_slot_config(max_tasks=0, enforce=False)
    except Exception:
        logger.warning("Failed to reset slot config — tests may leak state")


def _future_hour_str(offset_hours: int = 0) -> str:
    """Return an 'HH:00' string for a future hour (offset from now + 2 days)."""
    base = datetime.now(UTC) + timedelta(days=2) + timedelta(hours=offset_hours)
    return base.strftime("%H:00")


def _future_iso(offset_hours: int = 0) -> str:
    """Return a full ISO datetime string for a future time (2 days out)."""
    base = datetime.now(UTC) + timedelta(days=2) + timedelta(hours=offset_hours)
    normalised = base.replace(minute=30, second=0, microsecond=0)
    return normalised.isoformat()


def _cleanup_slot_tasks(target_hour_str: str) -> None:
    """Cancel any existing PENDING/QUEUED/RUNNING tasks in the given hour slot.

    This prevents cross-run contamination where tasks from previous test runs
    (which share the same HH:00 hour) inflate slot counts.
    """
    # Extract just the hour (e.g., "08" from "08:00")
    target_hh = target_hour_str[:2]
    try:
        resp = _be("GET", "/api/tasks", params={
            "status": "pending,queued,running",
            "page": 1,
            "page_size": 100,
        })
        if resp.status_code != 200:
            logger.warning("Could not list tasks for cleanup: %s", resp.status_code)
            return

        body = resp.json()
        tasks = body.get("items", body) if isinstance(body, dict) else body

        cancelled = 0
        for task in tasks:
            sa = task.get("scheduled_at", "")
            if not sa:
                continue
            # Match by hour — scheduled_at looks like "2026-04-07T08:31:00"
            # Position 11:13 gives "HH"
            task_hh = sa[11:13] if len(sa) >= 13 else ""
            if task_hh == target_hh:
                cancel_resp = _be("POST", f"/api/tasks/{task['id']}/cancel")
                if cancel_resp.status_code == 200:
                    cancelled += 1

        if cancelled:
            logger.info("Cleaned up %d stale tasks in slot %s", cancelled, target_hour_str)
    except Exception as exc:
        logger.warning("Slot cleanup failed (non-fatal): %s", exc)


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════

@skip_if_unavailable
@pytest.mark.timeout(60)
def test_slot_capacity_config_round_trip():
    """Verify slot_max_tasks and slot_max_tasks_enforce persist through PATCH → GET."""
    try:
        # Set non-default values
        set_slot_config(max_tasks=3, enforce=True)

        # Read them back
        resp = _be("GET", "/api/config/runtime")
        assert resp.status_code == 200, f"GET config failed: {resp.status_code}"
        body = resp.json()
        assert body["slot_max_tasks"] == 3, f"Expected 3, got {body['slot_max_tasks']}"
        assert body["slot_max_tasks_enforce"] is True, "Expected enforce=True"

        # Flip enforce to False
        set_slot_config(max_tasks=3, enforce=False)
        resp = _be("GET", "/api/config/runtime")
        body = resp.json()
        assert body["slot_max_tasks_enforce"] is False, "Expected enforce=False"
    finally:
        reset_slot_config()


@skip_if_unavailable
@pytest.mark.timeout(120)
def test_slot_capacity_enforce_rejects_webhook():
    """With enforce=True and slot_max_tasks=2, the 3rd webhook to the same hour is rejected."""
    created_issue_iids: list[int] = []
    target_hour = _future_hour_str(offset_hours=0)

    try:
        set_slot_config(max_tasks=2, enforce=True)
        _cleanup_slot_tasks(target_hour)

        # --- First two webhooks should succeed ---
        for i in range(2):
            issue = create_issue(f"Slot enforce test #{i + 1}")
            created_issue_iids.append(issue["iid"])
            note_id = _next_note_id()
            comment = f"@ai-bot at={target_hour} slot enforcement task {i + 1}"
            resp = trigger_webhook(note_id, comment, issue["iid"], issue["id"])
            assert resp.status_code == 200, (
                f"Webhook #{i + 1} failed unexpectedly: {resp.status_code} {resp.text}"
            )
            body = resp.json()
            assert body.get("status") != "rejected", (
                f"Webhook #{i + 1} was rejected prematurely: {body}"
            )
            # Small pause to let the backend persist the task
            time.sleep(1)

        # --- Third webhook should be rejected ---
        issue3 = create_issue("Slot enforce test #3 (should reject)")
        created_issue_iids.append(issue3["iid"])
        note_id3 = _next_note_id()
        comment3 = f"@ai-bot at={target_hour} this should be rejected"
        resp3 = trigger_webhook(note_id3, comment3, issue3["iid"], issue3["id"])

        body3 = resp3.json()
        assert body3.get("status") == "rejected", (
            f"Expected rejection, but got: {body3}"
        )
        assert "Slot at full capacity" in body3.get("message", ""), (
            f"Missing 'Slot at full capacity' in message: {body3}"
        )
        assert "full capacity" in body3.get("detail", ""), (
            f"Missing capacity detail: {body3}"
        )
        logger.info("✅ 3rd webhook correctly rejected: %s", body3["message"])

        # --- Best-effort check: rejection comment on the GitLab issue ---
        # The backend may not be able to reach GitLab from inside Docker,
        # so treat this as a soft check (warning, not failure).
        time.sleep(2)
        try:
            notes = get_issue_notes(issue3["iid"])
            rejection_notes = [n for n in notes if "full capacity" in n.get("body", "")]
            if rejection_notes:
                logger.info("✅ Rejection comment found on GitLab issue #%s", issue3["iid"])
            else:
                logger.warning(
                    "⚠️  No rejection comment found on issue #%s (%d notes) — "
                    "backend may not have GitLab connectivity",
                    issue3["iid"], len(notes),
                )
        except Exception as exc:
            logger.warning("⚠️  Could not verify GitLab comment: %s", exc)

    finally:
        reset_slot_config()
        for iid in created_issue_iids:
            cleanup_issue(iid)


@skip_if_unavailable
@pytest.mark.timeout(90)
def test_slot_capacity_soft_mode_allows_webhook():
    """With enforce=False (soft mode), webhooks are never rejected even when the slot is full."""
    created_issue_iids: list[int] = []
    target_hour = _future_hour_str(offset_hours=1)

    try:
        set_slot_config(max_tasks=1, enforce=False)
        _cleanup_slot_tasks(target_hour)

        for i in range(2):
            issue = create_issue(f"Slot soft-mode test #{i + 1}")
            created_issue_iids.append(issue["iid"])
            note_id = _next_note_id()
            comment = f"@ai-bot at={target_hour} soft mode task {i + 1}"
            resp = trigger_webhook(note_id, comment, issue["iid"], issue["id"])
            assert resp.status_code == 200, (
                f"Webhook #{i + 1} failed: {resp.status_code} {resp.text}"
            )
            body = resp.json()
            assert body.get("status") != "rejected", (
                f"Webhook #{i + 1} was rejected in soft mode: {body}"
            )
            time.sleep(1)

        # Verify no rejection comments were posted on any issue
        time.sleep(2)
        for iid in created_issue_iids:
            notes = get_issue_notes(iid)
            rejection_notes = [n for n in notes if "full capacity" in n.get("body", "")]
            assert len(rejection_notes) == 0, (
                f"Unexpected rejection comment on issue #{iid} in soft mode"
            )
        logger.info("✅ Both webhooks accepted in soft mode, no rejection comments")

    finally:
        reset_slot_config()
        for iid in created_issue_iids:
            cleanup_issue(iid)


@skip_if_unavailable
@pytest.mark.timeout(90)
def test_slot_capacity_disabled_allows_unlimited():
    """With slot_max_tasks=0, any number of webhooks are accepted."""
    created_issue_iids: list[int] = []
    target_hour = _future_hour_str(offset_hours=2)

    try:
        set_slot_config(max_tasks=0, enforce=True)
        _cleanup_slot_tasks(target_hour)

        for i in range(3):
            issue = create_issue(f"Slot disabled test #{i + 1}")
            created_issue_iids.append(issue["iid"])
            note_id = _next_note_id()
            comment = f"@ai-bot at={target_hour} unlimited task {i + 1}"
            resp = trigger_webhook(note_id, comment, issue["iid"], issue["id"])
            assert resp.status_code == 200, (
                f"Webhook #{i + 1} failed: {resp.status_code} {resp.text}"
            )
            body = resp.json()
            assert body.get("status") != "rejected", (
                f"Webhook #{i + 1} was rejected with slot_max_tasks=0: {body}"
            )
            time.sleep(1)

        logger.info("✅ All 3 webhooks accepted with slot_max_tasks=0 (disabled)")

    finally:
        reset_slot_config()
        for iid in created_issue_iids:
            cleanup_issue(iid)


@skip_if_unavailable
@pytest.mark.timeout(90)
def test_slot_capacity_different_slots_independent():
    """Tasks in different 1-hour slots do not interfere with each other."""
    created_issue_iids: list[int] = []
    hour_a = _future_hour_str(offset_hours=3)
    hour_b = _future_hour_str(offset_hours=4)

    try:
        set_slot_config(max_tasks=1, enforce=True)
        _cleanup_slot_tasks(hour_a)
        _cleanup_slot_tasks(hour_b)

        # Webhook to slot A
        issue_a = create_issue("Slot independence test - hour A")
        created_issue_iids.append(issue_a["iid"])
        resp_a = trigger_webhook(
            _next_note_id(),
            f"@ai-bot at={hour_a} task in hour A",
            issue_a["iid"],
            issue_a["id"],
        )
        assert resp_a.status_code == 200
        assert resp_a.json().get("status") != "rejected", (
            f"Hour-A webhook rejected unexpectedly: {resp_a.json()}"
        )
        time.sleep(1)

        # Webhook to slot B (different hour) — should also succeed
        issue_b = create_issue("Slot independence test - hour B")
        created_issue_iids.append(issue_b["iid"])
        resp_b = trigger_webhook(
            _next_note_id(),
            f"@ai-bot at={hour_b} task in hour B",
            issue_b["iid"],
            issue_b["id"],
        )
        assert resp_b.status_code == 200
        body_b = resp_b.json()
        assert body_b.get("status") != "rejected", (
            f"Hour-B webhook was rejected even though it's a different slot: {body_b}"
        )
        logger.info("✅ Independent slots accepted without cross-interference")

    finally:
        reset_slot_config()
        for iid in created_issue_iids:
            cleanup_issue(iid)


@skip_if_unavailable
@pytest.mark.timeout(60)
def test_slot_capacity_api_endpoint():
    """GET /api/tasks/slot-capacity returns correct capacity info."""
    try:
        set_slot_config(max_tasks=5, enforce=True)

        future_time = _future_iso(offset_hours=10)
        resp = _be("GET", "/api/tasks/slot-capacity", params={"scheduled_at": future_time})
        assert resp.status_code == 200, (
            f"Slot-capacity endpoint failed: {resp.status_code} {resp.text}"
        )

        body = resp.json()
        assert "hour_start" in body, f"Missing hour_start: {body}"
        assert "hour_end" in body, f"Missing hour_end: {body}"
        assert "count" in body, f"Missing count: {body}"
        assert "max" in body, f"Missing max: {body}"
        assert "is_full" in body, f"Missing is_full: {body}"
        assert "enforce" in body, f"Missing enforce: {body}"

        assert body["max"] == 5, f"Expected max=5, got {body['max']}"
        assert body["enforce"] is True, f"Expected enforce=True, got {body['enforce']}"
        # Slot far in the future should have 0 existing tasks
        assert body["count"] == 0, f"Expected count=0, got {body['count']}"
        assert body["is_full"] is False, f"Expected is_full=False, got {body['is_full']}"

        logger.info("✅ Slot capacity API returned correct data: %s", body)

    finally:
        reset_slot_config()
