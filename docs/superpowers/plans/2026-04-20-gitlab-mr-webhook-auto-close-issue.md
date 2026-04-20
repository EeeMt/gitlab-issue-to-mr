# GitLab MR Webhook Auto-Close Issue — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a GitLab MR is merged, automatically close the corresponding Codify issue via webhook.

**Architecture:** New `webhook_handler.py` module receives GitLab webhook events at `POST /api/webhook/gitlab`, verifies the `X-Gitlab-Token` header against per-project or global secrets, matches MR merge events to issues by `project_id + merge_request_iid`, and closes them. All events are logged to a new `webhook_events` table, viewable in a new Config tab.

**Tech Stack:** FastAPI, SQLAlchemy (async), Alembic, Vue 3 + Naive UI + vue-i18n

**Spec:** `docs/superpowers/specs/2026-04-20-gitlab-mr-webhook-auto-close-issue-design.md`

---

### Task 1: Database — WebhookEvent model and migration

**Files:**
- Modify: `backend/app/models.py:437` (append after `SystemBootstrap`)
- Create: `backend/alembic/versions/028_add_webhook_events.py`

- [ ] **Step 1: Add the `WebhookEvent` model to `models.py`**

Append at the very end of `backend/app/models.py` (after the `SystemBootstrap` class, line 437):

```python


class WebhookEvent(Base):
    """Log entry for a received GitLab webhook event."""

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_action: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    merge_request_iid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    issue_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("issues.id", ondelete="SET NULL"), nullable=True
    )
    source_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    result: Mapped[str] = mapped_column(String(50), nullable=False)
    result_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    issue: Mapped[Optional["Issue"]] = relationship("Issue")

    __table_args__ = (
        Index("ix_webhook_events_project_created", "project_id", "created_at"),
    )
```

- [ ] **Step 2: Create the Alembic migration**

Create `backend/alembic/versions/028_add_webhook_events.py`:

```python
"""add webhook_events table

Revision ID: 028_add_webhook_events
Revises: 027_add_ai_providers
Create Date: 2026-04-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "028_add_webhook_events"
down_revision: Union[str, None] = "027_add_ai_providers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("event_action", sa.String(50), nullable=True),
        sa.Column("project_id", sa.Integer, nullable=False),
        sa.Column("merge_request_iid", sa.Integer, nullable=True),
        sa.Column(
            "issue_id",
            sa.Integer,
            sa.ForeignKey("issues.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_ip", sa.String(45), nullable=True),
        sa.Column("result", sa.String(50), nullable=False),
        sa.Column("result_detail", sa.Text, nullable=True),
        sa.Column("payload_summary", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_webhook_events_project_id", "webhook_events", ["project_id"])
    op.create_index(
        "ix_webhook_events_project_created",
        "webhook_events",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_events_project_created", table_name="webhook_events")
    op.drop_index("ix_webhook_events_project_id", table_name="webhook_events")
    op.drop_table("webhook_events")
```

- [ ] **Step 3: Verify the model imports work**

Run: `cd backend && python -c "from app.models import WebhookEvent; print('OK:', WebhookEvent.__tablename__)"`
Expected: `OK: webhook_events`

- [ ] **Step 4: Commit**

```bash
cd /Users/AI/Projects/codify_pure
git add backend/app/models.py backend/alembic/versions/028_add_webhook_events.py
git commit -m "feat: add WebhookEvent model and migration 028"
```

---

### Task 2: Webhook handler — receiver endpoint with tests

**Files:**
- Create: `backend/app/api/webhook_handler.py`
- Create: `backend/tests/unit/test_webhook_handler.py`

- [ ] **Step 1: Write the failing tests for the webhook receiver**

Create `backend/tests/unit/test_webhook_handler.py`:

```python
#!/usr/bin/env python3
"""Unit tests for the GitLab webhook handler.

Tests cover:
- Token verification (per-project secret, global fallback, missing, mismatch)
- MR merge event → issue closed
- MR non-merge event → ignored
- Non-merge_request event → unsupported
- Already closed issue → idempotent
- No matching issue → no_match
- Multiple matching issues → all closed
- Invalid payload (missing project.id, bad JSON handled by FastAPI)
- WebhookEvent records created for each scenario
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient


def _make_mock_settings(gitlab_webhook_secret="global-secret"):
    settings = MagicMock()
    settings.gitlab_webhook_secret = gitlab_webhook_secret
    return settings


def _build_mr_merge_payload(project_id=42, mr_iid=7):
    """Build a minimal GitLab MR merge webhook payload."""
    return {
        "object_kind": "merge_request",
        "project": {"id": project_id, "path_with_namespace": "group/project"},
        "object_attributes": {
            "iid": mr_iid,
            "action": "merge",
            "title": "Fix bug",
            "state": "merged",
            "source_branch": "codify/issue-1",
            "target_branch": "main",
        },
    }


def _build_mr_close_payload(project_id=42, mr_iid=7):
    payload = _build_mr_merge_payload(project_id, mr_iid)
    payload["object_attributes"]["action"] = "close"
    payload["object_attributes"]["state"] = "closed"
    return payload


def _build_note_payload(project_id=42):
    return {
        "object_kind": "note",
        "project": {"id": project_id},
        "object_attributes": {"note": "some comment"},
    }


class TestWebhookReceiver(unittest.IsolatedAsyncioTestCase):
    """Tests for POST /api/webhook/gitlab."""

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock()
        self.mock_db.commit = AsyncMock()
        self.mock_db.add = MagicMock()
        self.mock_db.flush = AsyncMock()
        self.mock_db.get = AsyncMock(return_value=None)

        async def override_db():
            yield self.mock_db

        # Patch settings
        self.settings_patcher = patch(
            "app.api.webhook_handler.get_effective_settings",
            return_value=_make_mock_settings(),
        )
        self.mock_settings = self.settings_patcher.start()

        # Patch load_runtime_config_from_db
        self.runtime_patcher = patch(
            "app.api.webhook_handler.load_runtime_config_from_db",
            new_callable=AsyncMock,
        )
        self.runtime_patcher.start()

        # Patch project webhook secret lookup
        self.secret_patcher = patch(
            "app.api.webhook_handler.get_project_webhook_secret",
            new_callable=AsyncMock,
            return_value=None,  # No per-project secret by default → use global
        )
        self.mock_get_secret = self.secret_patcher.start()

        from app.main import app
        from app.database import get_db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.settings_patcher.stop()
        self.runtime_patcher.stop()
        self.secret_patcher.stop()
        from app.main import app
        from app.database import get_db
        app.dependency_overrides.pop(get_db, None)

    def test_missing_token_returns_401(self):
        payload = _build_mr_merge_payload()
        resp = self.client.post("/api/webhook/gitlab", json=payload)
        self.assertEqual(resp.status_code, 401)

    def test_wrong_token_returns_401(self):
        payload = _build_mr_merge_payload()
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "wrong-secret"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_correct_global_token_accepted(self):
        # Mock no matching issues
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        payload = _build_mr_merge_payload()
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "global-secret"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_per_project_secret_takes_priority(self):
        self.mock_get_secret.return_value = "project-secret"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        payload = _build_mr_merge_payload()
        # Global secret should fail when per-project secret is set
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "global-secret"},
        )
        self.assertEqual(resp.status_code, 401)

        # Per-project secret should succeed
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "project-secret"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_mr_merge_closes_matching_issue(self):
        mock_issue = MagicMock()
        mock_issue.id = 1
        mock_issue.status = "in_review"
        mock_issue.project_id = 42
        mock_issue.merge_request_iid = 7

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_issue]
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        payload = _build_mr_merge_payload(project_id=42, mr_iid=7)
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "global-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_issue.status, "closed")
        self.mock_db.commit.assert_awaited()

    def test_mr_merge_already_closed_is_idempotent(self):
        mock_issue = MagicMock()
        mock_issue.id = 1
        mock_issue.status = "closed"
        mock_issue.project_id = 42
        mock_issue.merge_request_iid = 7

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_issue]
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        payload = _build_mr_merge_payload(project_id=42, mr_iid=7)
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "global-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        # Status should still be closed — not changed
        self.assertEqual(mock_issue.status, "closed")
        data = resp.json()
        self.assertIn("ignored_already_closed", str(data.get("results", [])))

    def test_mr_non_merge_action_ignored(self):
        payload = _build_mr_close_payload()
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "global-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["result"], "ignored_action")

    def test_non_mr_event_returns_unsupported(self):
        payload = _build_note_payload()
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "global-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["result"], "unsupported_event")

    def test_missing_project_id_returns_400(self):
        payload = {"object_kind": "merge_request", "object_attributes": {"action": "merge", "iid": 1}}
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "global-secret"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_no_secrets_configured_returns_401(self):
        self.mock_settings.return_value = _make_mock_settings(gitlab_webhook_secret="")
        payload = _build_mr_merge_payload()
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "some-token"},
        )
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_webhook_handler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.webhook_handler'`

- [ ] **Step 3: Implement the webhook handler**

Create `backend/app/api/webhook_handler.py`:

```python
"""GitLab webhook receiver and event log query API."""

from __future__ import annotations

import hmac
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings
from app.database import get_db
from app.models import Issue, IssueStatus, WebhookEvent
from app.project_webhook_config import get_project_webhook_secret
from app.runtime_config import load_runtime_config_from_db

logger = logging.getLogger(__name__)

# Router for the unauthenticated webhook receiver
webhook_router = APIRouter()

# Router for the authenticated event query endpoint
events_router = APIRouter()


class WebhookResponse(BaseModel):
    result: str
    detail: Optional[str] = None
    results: Optional[list[dict[str, Any]]] = None


class WebhookEventOut(BaseModel):
    id: int
    event_type: str
    event_action: Optional[str]
    project_id: int
    merge_request_iid: Optional[int]
    issue_id: Optional[int]
    source_ip: Optional[str]
    result: str
    result_detail: Optional[str]
    payload_summary: Optional[dict[str, Any]]
    created_at: str


class WebhookEventsResponse(BaseModel):
    items: list[WebhookEventOut]
    total: int
    page: int
    page_size: int


def _extract_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract key fields from the webhook payload for storage."""
    summary: dict[str, Any] = {"object_kind": payload.get("object_kind")}
    project = payload.get("project")
    if isinstance(project, dict):
        summary["project_id"] = project.get("id")
        summary["project_path"] = project.get("path_with_namespace")
    attrs = payload.get("object_attributes")
    if isinstance(attrs, dict):
        summary["action"] = attrs.get("action")
        summary["iid"] = attrs.get("iid")
        summary["title"] = attrs.get("title")
        summary["state"] = attrs.get("state")
        summary["source_branch"] = attrs.get("source_branch")
        summary["target_branch"] = attrs.get("target_branch")
    return summary


async def _log_event(
    db: AsyncSession,
    *,
    event_type: str,
    event_action: Optional[str],
    project_id: int,
    merge_request_iid: Optional[int],
    issue_id: Optional[int],
    source_ip: Optional[str],
    result: str,
    result_detail: Optional[str] = None,
    payload_summary: Optional[dict[str, Any]] = None,
) -> None:
    """Persist a webhook event record."""
    event = WebhookEvent(
        event_type=event_type,
        event_action=event_action,
        project_id=project_id,
        merge_request_iid=merge_request_iid,
        issue_id=issue_id,
        source_ip=source_ip,
        result=result,
        result_detail=result_detail,
        payload_summary=payload_summary,
    )
    db.add(event)
    await db.flush()


@webhook_router.post("/webhook/gitlab", response_model=WebhookResponse)
async def receive_gitlab_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive and process GitLab webhook events."""
    # Parse body
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Extract project ID
    project_data = payload.get("project")
    if not isinstance(project_data, dict) or "id" not in project_data:
        raise HTTPException(status_code=400, detail="Missing project.id in payload")
    project_id = int(project_data["id"])

    source_ip = request.client.host if request.client else None
    event_type = str(payload.get("object_kind", "unknown"))
    attrs = payload.get("object_attributes") or {}
    event_action = attrs.get("action") if isinstance(attrs, dict) else None
    mr_iid = attrs.get("iid") if isinstance(attrs, dict) else None
    summary = _extract_payload_summary(payload)

    # --- Token verification ---
    token = request.headers.get("X-Gitlab-Token", "")
    await load_runtime_config_from_db(db)
    settings = get_effective_settings()

    expected_secret = await get_project_webhook_secret(db, project_id)
    if not expected_secret:
        expected_secret = settings.gitlab_webhook_secret.strip() if settings.gitlab_webhook_secret else ""

    if not expected_secret or not hmac.compare_digest(token, expected_secret):
        await _log_event(
            db,
            event_type=event_type,
            event_action=event_action,
            project_id=project_id,
            merge_request_iid=mr_iid,
            issue_id=None,
            source_ip=source_ip,
            result="auth_failed",
            result_detail="Token mismatch or no secret configured",
            payload_summary=summary,
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    # --- Event routing ---
    if event_type != "merge_request":
        await _log_event(
            db,
            event_type=event_type,
            event_action=event_action,
            project_id=project_id,
            merge_request_iid=mr_iid,
            issue_id=None,
            source_ip=source_ip,
            result="unsupported_event",
            result_detail=f"Event type '{event_type}' is not handled",
            payload_summary=summary,
        )
        await db.commit()
        return WebhookResponse(result="unsupported_event", detail=f"Event type '{event_type}' not handled")

    if event_action != "merge":
        await _log_event(
            db,
            event_type=event_type,
            event_action=event_action,
            project_id=project_id,
            merge_request_iid=mr_iid,
            issue_id=None,
            source_ip=source_ip,
            result="ignored_action",
            result_detail=f"MR action '{event_action}' is not 'merge'",
            payload_summary=summary,
        )
        await db.commit()
        return WebhookResponse(result="ignored_action", detail=f"Action '{event_action}' ignored")

    # --- MR merged: find and close matching issues ---
    if mr_iid is None:
        await _log_event(
            db,
            event_type=event_type,
            event_action=event_action,
            project_id=project_id,
            merge_request_iid=None,
            issue_id=None,
            source_ip=source_ip,
            result="no_match",
            result_detail="MR IID missing from payload",
            payload_summary=summary,
        )
        await db.commit()
        return WebhookResponse(result="no_match", detail="MR IID missing")

    result = await db.execute(
        select(Issue).where(
            Issue.project_id == project_id,
            Issue.merge_request_iid == int(mr_iid),
        )
    )
    issues = result.scalars().all()

    if not issues:
        await _log_event(
            db,
            event_type=event_type,
            event_action=event_action,
            project_id=project_id,
            merge_request_iid=int(mr_iid),
            issue_id=None,
            source_ip=source_ip,
            result="no_match",
            result_detail=f"No Codify issue for project {project_id} MR !{mr_iid}",
            payload_summary=summary,
        )
        await db.commit()
        return WebhookResponse(result="no_match", detail=f"No issue for MR !{mr_iid}")

    results: list[dict[str, Any]] = []
    for issue in issues:
        if issue.status == IssueStatus.CLOSED.value:
            await _log_event(
                db,
                event_type=event_type,
                event_action=event_action,
                project_id=project_id,
                merge_request_iid=int(mr_iid),
                issue_id=issue.id,
                source_ip=source_ip,
                result="ignored_already_closed",
                payload_summary=summary,
            )
            results.append({"issue_id": issue.id, "result": "ignored_already_closed"})
        else:
            prev_status = issue.status
            issue.status = IssueStatus.CLOSED.value
            await _log_event(
                db,
                event_type=event_type,
                event_action=event_action,
                project_id=project_id,
                merge_request_iid=int(mr_iid),
                issue_id=issue.id,
                source_ip=source_ip,
                result="issue_closed",
                result_detail=f"Closed issue #{issue.id} (was '{prev_status}')",
                payload_summary=summary,
            )
            results.append({"issue_id": issue.id, "result": "issue_closed"})

    await db.commit()

    overall = "issue_closed" if any(r["result"] == "issue_closed" for r in results) else "ignored_already_closed"
    return WebhookResponse(result=overall, results=results)


@events_router.get("/webhook/events", response_model=WebhookEventsResponse)
async def list_webhook_events(
    page: int = 1,
    page_size: int = 20,
    event_type: Optional[str] = None,
    result: Optional[str] = None,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """Query paginated webhook event log."""
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 1
    elif page_size > 100:
        page_size = 100

    query = select(WebhookEvent)
    count_query = select(func.count(WebhookEvent.id))

    if event_type:
        query = query.where(WebhookEvent.event_type == event_type)
        count_query = count_query.where(WebhookEvent.event_type == event_type)
    if result:
        query = query.where(WebhookEvent.result == result)
        count_query = count_query.where(WebhookEvent.result == result)
    if project_id is not None:
        query = query.where(WebhookEvent.project_id == project_id)
        count_query = count_query.where(WebhookEvent.project_id == project_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(WebhookEvent.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = await db.execute(query)
    events = rows.scalars().all()

    items = [
        WebhookEventOut(
            id=e.id,
            event_type=e.event_type,
            event_action=e.event_action,
            project_id=e.project_id,
            merge_request_iid=e.merge_request_iid,
            issue_id=e.issue_id,
            source_ip=e.source_ip,
            result=e.result,
            result_detail=e.result_detail,
            payload_summary=e.payload_summary,
            created_at=e.created_at.isoformat() if e.created_at else "",
        )
        for e in events
    ]

    return WebhookEventsResponse(items=items, total=total, page=page, page_size=page_size)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_webhook_handler.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/AI/Projects/codify_pure
git add backend/app/api/webhook_handler.py backend/tests/unit/test_webhook_handler.py
git commit -m "feat: add webhook handler with receiver and event query endpoints"
```

---

### Task 3: Register routers in main.py

**Files:**
- Modify: `backend/app/main.py:202` (import line) and after line 288 (router registration)

- [ ] **Step 1: Add the import**

In `backend/app/main.py`, line 202, change:

```python
from app.api import admin_users, auth, issues, tasks, containers, stats, config, config_integration, config_runtime, mattermost, oidc, project_webhooks, prompt_templates, projects, providers
```

to:

```python
from app.api import admin_users, auth, issues, tasks, containers, stats, config, config_integration, config_runtime, mattermost, oidc, project_webhooks, prompt_templates, projects, providers, webhook_handler
```

- [ ] **Step 2: Register the webhook receiver router (no auth)**

Add after the last `app.include_router(...)` block (after providers router, line 288):

```python
# Webhook receiver — no auth (verified via X-Gitlab-Token header)
app.include_router(webhook_handler.webhook_router, prefix="/api", tags=["webhook"])
# Webhook event log — requires authentication
app.include_router(
    webhook_handler.events_router,
    prefix="/api",
    tags=["webhook"],
    dependencies=[Depends(require_authenticated_user)],
)
```

- [ ] **Step 3: Verify the app starts without errors**

Run: `cd backend && python -c "from app.main import app; print('App loaded OK')"`
Expected: `App loaded OK`

- [ ] **Step 4: Run existing tests to check for regressions**

Run: `cd backend && python -m pytest tests/unit/test_webhook_handler.py tests/unit/test_project_webhooks_api.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/AI/Projects/codify_pure
git add backend/app/main.py
git commit -m "feat: register webhook handler routers in main app"
```

---

### Task 4: Enable merge_requests_events in GitLab client

**Files:**
- Modify: `backend/app/core/gitlab_client.py:416`

- [ ] **Step 1: Change the webhook event flag**

In `backend/app/core/gitlab_client.py`, inside `ensure_project_webhook()`, change line 416:

```python
            "merge_requests_events": False,
```

to:

```python
            "merge_requests_events": True,
```

- [ ] **Step 2: Run existing GitLab client tests**

Run: `cd backend && python -m pytest tests/unit/test_gitlab_client_coverage.py tests/unit/test_gitlab_client_access.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
cd /Users/AI/Projects/codify_pure
git add backend/app/core/gitlab_client.py
git commit -m "feat: enable merge_requests_events in webhook config"
```

---

### Task 5: Add merge_requests_events to webhook status response

**Files:**
- Modify: `backend/app/api/project_webhooks.py:46-60` (response model) and `:87-136` (builder function)

- [ ] **Step 1: Add field to response model**

In `backend/app/api/project_webhooks.py`, add `merge_requests_events` to `GitLabProjectWebhookStatusResponse` (after `enable_ssl_verification`, line 57):

```python
    merge_requests_events: Optional[bool] = None
```

- [ ] **Step 2: Update the builder function**

In `_build_gitlab_project_webhook_status_response()`, add extraction of `merge_requests_events` from the matched hook. After the `enable_ssl_verification` extraction line (line 101), add:

```python
    merge_requests_events = bool(matched_hook.get("merge_requests_events")) if matched_hook is not None else None
```

Then update the `needs_attention` check block. Replace the existing check (lines 109-119):

```python
    elif note_events and enable_ssl_verification:
        status_value = "configured"
        status_detail = None
    else:
        status_value = "needs_attention"
        issues: list[str] = []
        if not note_events:
            issues.append("note events disabled")
        if not enable_ssl_verification:
            issues.append("SSL verification disabled")
        status_detail = ", ".join(issues) if issues else "Webhook settings need attention"
```

with:

```python
    elif note_events and enable_ssl_verification and merge_requests_events:
        status_value = "configured"
        status_detail = None
    else:
        status_value = "needs_attention"
        issues: list[str] = []
        if not note_events:
            issues.append("note events disabled")
        if not enable_ssl_verification:
            issues.append("SSL verification disabled")
        if not merge_requests_events:
            issues.append("MR events disabled")
        status_detail = ", ".join(issues) if issues else "Webhook settings need attention"
```

Then add `merge_requests_events=merge_requests_events` to the return statement (after `enable_ssl_verification=enable_ssl_verification`).

- [ ] **Step 3: Update the frontend type**

In `frontend/src/api/index.ts`, add to `GitLabProjectWebhookStatusResult` (after `enable_ssl_verification`, line 576):

```typescript
  merge_requests_events: boolean | null
```

- [ ] **Step 4: Run webhook API tests**

Run: `cd backend && python -m pytest tests/unit/test_project_webhooks_api.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/AI/Projects/codify_pure
git add backend/app/api/project_webhooks.py frontend/src/api/index.ts
git commit -m "feat: add merge_requests_events to webhook status response"
```

---

### Task 6: Frontend — API client and i18n for webhook events

**Files:**
- Modify: `frontend/src/api/index.ts` (add types and function)
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Add WebhookEvent types and API function to `frontend/src/api/index.ts`**

Add these types after the existing `GitLabProjectWebhookStatusResult` interface (after line 580):

```typescript
export interface WebhookEvent {
  id: number
  event_type: string
  event_action: string | null
  project_id: number
  merge_request_iid: number | null
  issue_id: number | null
  source_ip: string | null
  result: string
  result_detail: string | null
  payload_summary: Record<string, unknown> | null
  created_at: string
}

export interface WebhookEventsResponse {
  items: WebhookEvent[]
  total: number
  page: number
  page_size: number
}
```

Add this function after `listGitLabProjectWebhookStatuses()` (after line 954):

```typescript
export async function getWebhookEvents(params: {
  page?: number
  page_size?: number
  event_type?: string
  result?: string
  project_id?: number
} = {}): Promise<WebhookEventsResponse> {
  const response = await api.get('/webhook/events', { params })
  return response.data
}
```

- [ ] **Step 2: Add English i18n keys**

In `frontend/src/i18n/messages/en.ts`, in the `config` section (after the existing webhook keys, around line 1211), add:

```typescript
      webhookEventsTab: 'Webhook Events',
      webhookEventsTitle: 'Webhook Event Log',
      webhookEventsSubtitle: 'History of received GitLab webhook events and their processing results.',
      webhookEventsEmpty: 'No webhook events recorded yet.',
      webhookEventsColTime: 'Time',
      webhookEventsColProjectId: 'Project ID',
      webhookEventsColEventType: 'Event Type',
      webhookEventsColAction: 'Action',
      webhookEventsColMrIid: 'MR IID',
      webhookEventsColIssue: 'Issue',
      webhookEventsColResult: 'Result',
      webhookEventsColDetail: 'Detail',
      webhookEventsFilterResult: 'Filter by result',
      webhookEventsFilterProjectId: 'Filter by project ID',
      webhookEventsRefresh: 'Refresh',
      webhookEventsResultIssueClosed: 'Issue closed',
      webhookEventsResultIgnoredAlreadyClosed: 'Already closed',
      webhookEventsResultNoMatch: 'No match',
      webhookEventsResultUnsupported: 'Unsupported event',
      webhookEventsResultIgnoredAction: 'Ignored action',
      webhookEventsResultAuthFailed: 'Auth failed',
      webhookMrEventsShort: 'MR events',
      webhookMrEventsDisabledWarning: 'MR events disabled — re-configure webhook to enable auto-close',
```

- [ ] **Step 3: Add Chinese i18n keys**

In `frontend/src/i18n/messages/zh-CN.ts`, add the corresponding Chinese keys in the same location:

```typescript
      webhookEventsTab: 'Webhook 事件',
      webhookEventsTitle: 'Webhook 事件日志',
      webhookEventsSubtitle: '已接收的 GitLab Webhook 事件及处理结果的历史记录。',
      webhookEventsEmpty: '暂无 Webhook 事件记录。',
      webhookEventsColTime: '时间',
      webhookEventsColProjectId: '项目 ID',
      webhookEventsColEventType: '事件类型',
      webhookEventsColAction: '操作',
      webhookEventsColMrIid: 'MR IID',
      webhookEventsColIssue: 'Issue',
      webhookEventsColResult: '结果',
      webhookEventsColDetail: '详情',
      webhookEventsFilterResult: '按结果筛选',
      webhookEventsFilterProjectId: '按项目 ID 筛选',
      webhookEventsRefresh: '刷新',
      webhookEventsResultIssueClosed: 'Issue 已关闭',
      webhookEventsResultIgnoredAlreadyClosed: '已是关闭状态',
      webhookEventsResultNoMatch: '未匹配',
      webhookEventsResultUnsupported: '不支持的事件',
      webhookEventsResultIgnoredAction: '已忽略的操作',
      webhookEventsResultAuthFailed: '认证失败',
      webhookMrEventsShort: 'MR 事件',
      webhookMrEventsDisabledWarning: 'MR 事件未启用 — 请重新配置 Webhook 以启用自动关闭',
```

- [ ] **Step 4: Verify frontend builds**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no type errors

- [ ] **Step 5: Commit**

```bash
cd /Users/AI/Projects/codify_pure
git add frontend/src/api/index.ts frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: add webhook events API client and i18n keys"
```

---

### Task 7: Frontend — WebhookEventsPanel component

**Files:**
- Create: `frontend/src/views/config/WebhookEventsPanel.vue`

- [ ] **Step 1: Create `WebhookEventsPanel.vue`**

Create `frontend/src/views/config/WebhookEventsPanel.vue`:

```vue
<template>
  <div class="config-layout__main">
    <n-card class="config-form-card" :bordered="false">
      <template #header>
        <div class="config-card-header config-card-header--stacked">
          <div>
            <div class="config-card-header__title">{{ t('config.webhookEventsTitle') }}</div>
            <div class="config-card-header__subtitle">{{ t('config.webhookEventsSubtitle') }}</div>
          </div>
          <n-button @click="fetchEvents" :loading="loading">
            {{ t('config.webhookEventsRefresh') }}
          </n-button>
        </div>
      </template>

      <n-space vertical :size="16">
        <n-grid :cols="isMobile ? 1 : 3" :x-gap="12" :y-gap="8">
          <n-gi>
            <n-select
              v-model:value="filterResult"
              :options="resultOptions"
              clearable
              :placeholder="t('config.webhookEventsFilterResult')"
              @update:value="fetchEvents"
            />
          </n-gi>
          <n-gi>
            <n-input-number
              v-model:value="filterProjectId"
              clearable
              :placeholder="t('config.webhookEventsFilterProjectId')"
              :show-button="false"
              @update:value="fetchEvents"
            />
          </n-gi>
        </n-grid>

        <n-data-table
          :columns="columns"
          :data="events"
          :loading="loading"
          :bordered="false"
          :scroll-x="1000"
          :row-key="(row: WebhookEvent) => row.id"
        />

        <n-space justify="end">
          <n-pagination
            v-model:page="currentPage"
            :page-size="pageSize"
            :item-count="total"
            :page-sizes="[10, 20, 50]"
            show-size-picker
            @update:page="fetchEvents"
            @update:page-size="handlePageSizeChange"
          />
        </n-space>
      </n-space>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NGi,
  NGrid,
  NInputNumber,
  NPagination,
  NSelect,
  NSpace,
  NTag,
  type DataTableColumns,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { getWebhookEvents, type WebhookEvent } from '../../api'

const props = defineProps<{
  isMobile?: boolean
}>()

const { t } = useI18n()

const loading = ref(false)
const events = ref<WebhookEvent[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const filterResult = ref<string | null>(null)
const filterProjectId = ref<number | null>(null)

const resultOptions = computed(() => [
  { label: t('config.webhookEventsResultIssueClosed'), value: 'issue_closed' },
  { label: t('config.webhookEventsResultIgnoredAlreadyClosed'), value: 'ignored_already_closed' },
  { label: t('config.webhookEventsResultNoMatch'), value: 'no_match' },
  { label: t('config.webhookEventsResultUnsupported'), value: 'unsupported_event' },
  { label: t('config.webhookEventsResultIgnoredAction'), value: 'ignored_action' },
  { label: t('config.webhookEventsResultAuthFailed'), value: 'auth_failed' },
])

function getResultTagType(result: string): 'success' | 'warning' | 'error' | 'default' {
  if (result === 'issue_closed') return 'success'
  if (result === 'no_match') return 'warning'
  if (result === 'auth_failed') return 'error'
  return 'default'
}

function getResultLabel(result: string): string {
  const map: Record<string, string> = {
    issue_closed: t('config.webhookEventsResultIssueClosed'),
    ignored_already_closed: t('config.webhookEventsResultIgnoredAlreadyClosed'),
    no_match: t('config.webhookEventsResultNoMatch'),
    unsupported_event: t('config.webhookEventsResultUnsupported'),
    ignored_action: t('config.webhookEventsResultIgnoredAction'),
    auth_failed: t('config.webhookEventsResultAuthFailed'),
  }
  return map[result] || result
}

const columns = computed<DataTableColumns<WebhookEvent>>(() => [
  {
    title: t('config.webhookEventsColTime'),
    key: 'created_at',
    width: 170,
    render: (row) => {
      const d = new Date(row.created_at)
      return d.toLocaleString()
    },
  },
  {
    title: t('config.webhookEventsColProjectId'),
    key: 'project_id',
    width: 100,
  },
  {
    title: t('config.webhookEventsColEventType'),
    key: 'event_type',
    width: 120,
  },
  {
    title: t('config.webhookEventsColAction'),
    key: 'event_action',
    width: 100,
    render: (row) => row.event_action || '-',
  },
  {
    title: t('config.webhookEventsColMrIid'),
    key: 'merge_request_iid',
    width: 80,
    render: (row) => (row.merge_request_iid != null ? `!${row.merge_request_iid}` : '-'),
  },
  {
    title: t('config.webhookEventsColIssue'),
    key: 'issue_id',
    width: 80,
    render: (row) => {
      if (row.issue_id == null) return '-'
      return h(RouterLink, { to: `/issues/${row.issue_id}` }, { default: () => `#${row.issue_id}` })
    },
  },
  {
    title: t('config.webhookEventsColResult'),
    key: 'result',
    width: 150,
    render: (row) =>
      h(NTag, { type: getResultTagType(row.result), size: 'small', round: true }, { default: () => getResultLabel(row.result) }),
  },
  {
    title: t('config.webhookEventsColDetail'),
    key: 'result_detail',
    minWidth: 200,
    render: (row) => row.result_detail || '-',
  },
])

async function fetchEvents() {
  loading.value = true
  try {
    const resp = await getWebhookEvents({
      page: currentPage.value,
      page_size: pageSize.value,
      result: filterResult.value || undefined,
      project_id: filterProjectId.value || undefined,
    })
    events.value = resp.items
    total.value = resp.total
  } catch (err) {
    console.error('Failed to load webhook events:', err)
    events.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function handlePageSizeChange(size: number) {
  pageSize.value = size
  currentPage.value = 1
  fetchEvents()
}

onMounted(() => {
  fetchEvents()
})
</script>
```

- [ ] **Step 2: Verify frontend builds**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
cd /Users/AI/Projects/codify_pure
git add frontend/src/views/config/WebhookEventsPanel.vue
git commit -m "feat: add WebhookEventsPanel component"
```

---

### Task 8: Frontend — Add tab to Config.vue and enhance GitLabSettingsPanel

**Files:**
- Modify: `frontend/src/views/Config.vue:40-72` (add tab), `:97-108` (import), `:130-132` (tab types)
- Modify: `frontend/src/views/config/GitLabSettingsPanel.vue:469-477` (webhook checks column)

- [ ] **Step 1: Import WebhookEventsPanel in Config.vue**

In `frontend/src/views/Config.vue`, add the import after `PromptTemplatesPanel` (line 102):

```typescript
import WebhookEventsPanel from './config/WebhookEventsPanel.vue'
```

- [ ] **Step 2: Add the tab pane in the template**

After the `maintenance` tab pane (line 71), add:

```vue
            <n-tab-pane name="webhook-events" :tab="t('config.webhookEventsTab')">
              <WebhookEventsPanel :is-mobile="isMobile" />
            </n-tab-pane>
```

- [ ] **Step 3: Update the tab type**

On line 130, change:

```typescript
const activeConfigTab = ref<'runtime' | 'auth' | 'gitlab' | 'ai-providers' | 'prompt-templates' | 'worker' | 'notifications' | 'maintenance'>('runtime')
```

to:

```typescript
const activeConfigTab = ref<'runtime' | 'auth' | 'gitlab' | 'ai-providers' | 'prompt-templates' | 'worker' | 'notifications' | 'maintenance' | 'webhook-events'>('runtime')
```

On line 131, change:

```typescript
const configTabs = ['runtime', 'auth', 'gitlab', 'ai-providers', 'prompt-templates', 'worker', 'notifications', 'maintenance'] as const
```

to:

```typescript
const configTabs = ['runtime', 'auth', 'gitlab', 'ai-providers', 'prompt-templates', 'worker', 'notifications', 'maintenance', 'webhook-events'] as const
```

- [ ] **Step 4: Add MR events indicator to GitLabSettingsPanel webhook checks column**

In `frontend/src/views/config/GitLabSettingsPanel.vue`, in the `webhookColumns` computed (around line 469-477), update the `checks` column render to include `merge_requests_events`. Replace:

```typescript
    render: (row) =>
      h('div', { class: 'config-webhook-checks' }, [
        h('span', `${t('config.webhookHookIdShort')}: ${row.hook_id ?? '-'}`),
        h('span', `${t('config.webhookNoteEventsShort')}: ${row.note_events === null ? '-' : row.note_events ? t('common.enabled') : t('common.disabled')}`),
        h('span', `${t('config.webhookSslShort')}: ${row.enable_ssl_verification === null ? '-' : row.enable_ssl_verification ? t('common.enabled') : t('common.disabled')}`)
      ])
```

with:

```typescript
    render: (row) =>
      h('div', { class: 'config-webhook-checks' }, [
        h('span', `${t('config.webhookHookIdShort')}: ${row.hook_id ?? '-'}`),
        h('span', `${t('config.webhookNoteEventsShort')}: ${row.note_events === null ? '-' : row.note_events ? t('common.enabled') : t('common.disabled')}`),
        h('span', `${t('config.webhookMrEventsShort')}: ${row.merge_requests_events === null ? '-' : row.merge_requests_events ? t('common.enabled') : t('common.disabled')}`),
        h('span', `${t('config.webhookSslShort')}: ${row.enable_ssl_verification === null ? '-' : row.enable_ssl_verification ? t('common.enabled') : t('common.disabled')}`)
      ])
```

- [ ] **Step 5: Verify frontend builds**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no type errors

- [ ] **Step 6: Commit**

```bash
cd /Users/AI/Projects/codify_pure
git add frontend/src/views/Config.vue frontend/src/views/config/GitLabSettingsPanel.vue
git commit -m "feat: add Webhook Events tab and MR events status indicator"
```

---

### Task 9: Run full test suite and verify

**Files:** None (verification only)

- [ ] **Step 1: Run backend unit tests**

Run: `cd backend && python -m pytest tests/unit/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 2: Run frontend build (type check)**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Run frontend unit tests**

Run: `cd frontend && npx vitest run`
Expected: All tests PASS

- [ ] **Step 4: Final commit if any fixes needed**

If any test failures were found and fixed, commit the fixes.
