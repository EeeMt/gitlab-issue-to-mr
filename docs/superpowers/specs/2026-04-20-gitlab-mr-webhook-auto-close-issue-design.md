# GitLab MR Webhook → Auto-Close Codify Issue

## Problem

Codify issues can only be closed manually. When a GitLab Merge Request (MR) is merged — meaning the generated code has been accepted — the corresponding Codify issue should automatically close. The system already has webhook configuration infrastructure (secret management, setup endpoints, status checking) but lacks the webhook **receiver** endpoint.

## Approach

Create an independent webhook handler module that receives GitLab webhook events, verifies authenticity via existing per-project/global secrets, matches MR merge events to Codify issues by `project_id + merge_request_iid`, and closes matching issues. All events are logged to a new `webhook_events` table, viewable in the frontend Config page.

---

## 1. Webhook Receiver Endpoint

**File:** `backend/app/api/webhook_handler.py`

### `POST /api/webhook/gitlab`

This endpoint is **unauthenticated** (no session/JWT required). Security relies on GitLab's `X-Gitlab-Token` header verification.

**Request flow:**

1. Extract `X-Gitlab-Token` from request headers.
2. Parse the JSON body; extract `project.id` to identify the source project.
3. Look up the expected secret:
   - First: query `project_webhook_config` table for a per-project encrypted secret.
   - Fallback: use `settings.gitlab_webhook_secret` (global).
   - If neither is configured, or the token doesn't match → return 401 and log `auth_failed`.
4. Read `object_kind` from the payload:
   - If not `"merge_request"` → log as `unsupported_event`, return 200.
5. Read `object_attributes.action`:
   - If not `"merge"` → log as `ignored` (e.g., open, close, update), return 200.
6. Extract `object_attributes.iid` (the MR IID).
7. Query `issues` table: `WHERE project_id = :project_id AND merge_request_iid = :mr_iid`.
8. For each matched issue:
   - If already `CLOSED` → log `ignored_already_closed`, skip.
   - Otherwise → set `status = CLOSED`, log `issue_closed`.
9. If no issues match → log `no_match`.
10. Always return 200 OK to prevent GitLab retries.

**Token verification** uses constant-time comparison (`hmac.compare_digest`) to prevent timing attacks.

### `GET /api/webhook/events`

Authenticated endpoint (requires login) for querying the event log.

**Query parameters:**
- `page` (int, default 1)
- `page_size` (int, default 20, max 100)
- `event_type` (optional string filter)
- `result` (optional string filter)
- `project_id` (optional int filter)

**Response:** paginated list of `WebhookEvent` records with total count.

---

## 2. Database Schema

### New table: `webhook_events`

**Migration:** `backend/alembic/versions/028_add_webhook_events.py`

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer, PK, auto-increment | Event ID |
| `event_type` | String(50), NOT NULL | `"merge_request"`, `"note"`, `"push"`, etc. |
| `event_action` | String(50), nullable | `"merge"`, `"close"`, `"open"`, `"update"`, etc. |
| `project_id` | Integer, NOT NULL, indexed | GitLab project ID |
| `merge_request_iid` | Integer, nullable | GitLab MR IID |
| `issue_id` | Integer, FK(issues.id), nullable | Matched Codify issue ID (null if unmatched) |
| `source_ip` | String(45), nullable | Request IP for audit |
| `result` | String(50), NOT NULL | See result values below |
| `result_detail` | Text, nullable | Extra context |
| `payload_summary` | JSON, nullable | Key fields from payload (not full payload) |
| `created_at` | DateTime, NOT NULL, default utcnow | Event timestamp |

**Result values:**
- `issue_closed` — successfully closed a Codify issue
- `ignored_already_closed` — issue was already closed
- `no_match` — no Codify issue found for this MR
- `unsupported_event` — event type not handled (e.g., `note`, `push`)
- `ignored_action` — merge_request event but action is not `merge`
- `auth_failed` — token verification failed

**Index:** `ix_webhook_events_project_created` on `(project_id, created_at DESC)`.

### New model: `WebhookEvent`

**File:** `backend/app/models.py`

```python
class WebhookEvent(Base):
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

---

## 3. GitLab Client Changes

**File:** `backend/app/core/gitlab_client.py`

In `ensure_project_webhook()`, change:
```python
"merge_requests_events": False,
```
to:
```python
"merge_requests_events": True,
```

This takes effect when a webhook is **created or re-configured** via the setup endpoint. Existing webhooks are updated when the admin clicks the "re-configure" button in the frontend (which calls `POST /api/config/gitlab/projects/{project_id}/webhook`).

---

## 4. Webhook Status Enhancement

**File:** `backend/app/api/project_webhooks.py`

Add `merge_requests_events` to `GitLabProjectWebhookStatusResponse`:
```python
merge_requests_events: Optional[bool] = None
```

Update `_build_gitlab_project_webhook_status_response()` to:
- Read `merge_requests_events` from the matched hook.
- If `merge_requests_events` is `False`, include it in the `needs_attention` issues list.

---

## 5. Frontend Changes

### 5.1 New: `WebhookEventsPanel.vue`

**File:** `frontend/src/views/config/WebhookEventsPanel.vue`

A new tab panel in the Config page showing webhook event history.

**Features:**
- NDataTable with columns: Time, Project ID, Event Type, Action, MR IID, Issue, Result, Detail
- Result column uses colored NTag:
  - `issue_closed` → green/success
  - `ignored_already_closed` → gray
  - `ignored_action` → gray
  - `no_match` → yellow/warning
  - `unsupported_event` → gray
  - `auth_failed` → red/error
- Issue column: clickable link to `/issues/{issue_id}` when present
- Filters: result type dropdown, project_id input
- Pagination with page size selector
- Auto-refresh button

### 5.2 Config.vue Tab Addition

**File:** `frontend/src/views/Config.vue`

Add a new tab entry (e.g., "Webhook Events" / "Webhook 事件") pointing to `WebhookEventsPanel`.

### 5.3 GitLabSettingsPanel Enhancement

**File:** `frontend/src/views/config/GitLabSettingsPanel.vue`

In the webhook status table, add a column or indicator for `merge_requests_events`:
- If `false` → show a warning tag: "MR events disabled — re-configure to enable"
- If `true` → show a green check

### 5.4 API Client

**File:** `frontend/src/api/index.ts`

New types:
```typescript
interface WebhookEvent {
  id: number
  event_type: string
  event_action: string | null
  project_id: number
  merge_request_iid: number | null
  issue_id: number | null
  source_ip: string | null
  result: string
  result_detail: string | null
  payload_summary: Record<string, any> | null
  created_at: string
}

interface WebhookEventsResponse {
  items: WebhookEvent[]
  total: number
  page: number
  page_size: number
}
```

New function:
```typescript
export async function getWebhookEvents(params: {
  page?: number
  page_size?: number
  event_type?: string
  result?: string
  project_id?: number
}): Promise<WebhookEventsResponse>
```

### 5.5 i18n

Add keys to both `en.ts` and `zh-CN.ts`:
- Tab label, column headers, result labels, filter labels, empty state text, warning messages.

---

## 6. Router Registration

**File:** `backend/app/main.py`

Register the webhook handler router in two ways:

1. **Webhook receiver** — no auth dependency:
   ```python
   app.include_router(webhook_handler.webhook_router, prefix="/api", tags=["webhook"])
   ```

2. **Event query** — with auth dependency:
   ```python
   app.include_router(
       webhook_handler.events_router,
       prefix="/api",
       tags=["webhook"],
       dependencies=[Depends(require_authenticated_user)],
   )
   ```

---

## 7. Edge Cases

| Scenario | Behavior |
|----------|----------|
| MR merged but no matching Codify issue | Log `no_match`, return 200 |
| Multiple issues share same `project_id + merge_request_iid` | Close all of them |
| Issue already CLOSED | Log `ignored_already_closed`, skip, return 200 |
| GitLab retries the same event | Idempotent — already-closed issues are ignored |
| No secret configured for the project or globally | Return 401, log `auth_failed` |
| Token mismatch | Return 401, log `auth_failed` |
| Non-merge_request event (note, push, etc.) | Log `unsupported_event`, return 200 |
| MR event but action is not "merge" (open, close, update) | Log `ignored_action`, return 200 |
| Request body is not valid JSON | Return 400 |
| `project.id` missing from payload | Return 400 |

---

## 8. File Change Summary

| Action | File | Description |
|--------|------|-------------|
| **New** | `backend/app/api/webhook_handler.py` | Webhook receiver + events query API |
| **New** | `backend/alembic/versions/028_add_webhook_events.py` | Migration for `webhook_events` table |
| **New** | `frontend/src/views/config/WebhookEventsPanel.vue` | Event history panel |
| **Modify** | `backend/app/models.py` | Add `WebhookEvent` model |
| **Modify** | `backend/app/main.py` | Register webhook routers |
| **Modify** | `backend/app/core/gitlab_client.py` | Enable `merge_requests_events` |
| **Modify** | `backend/app/api/project_webhooks.py` | Add `merge_requests_events` to status response |
| **Modify** | `frontend/src/views/Config.vue` | Add Webhook Events tab |
| **Modify** | `frontend/src/views/config/GitLabSettingsPanel.vue` | MR events status indicator |
| **Modify** | `frontend/src/api/index.ts` | New types and API function |
| **Modify** | `frontend/src/i18n/messages/en.ts` | English translations |
| **Modify** | `frontend/src/i18n/messages/zh-CN.ts` | Chinese translations |

---

## 9. Testing Strategy

- **Unit tests** for webhook handler: token verification, event matching, edge cases
- **Unit tests** for the events query endpoint: pagination, filtering
- **Frontend tests** for `WebhookEventsPanel.vue`: rendering, filtering, pagination
- Existing webhook configuration tests should continue to pass
