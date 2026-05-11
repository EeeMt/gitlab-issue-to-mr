"""Mattermost notification helpers for task lifecycle events."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

import httpx
from sqlalchemy import inspect, or_, select

from app.config import get_effective_settings
from app.core.ssl_utils import get_ssl_verify
from app.core.utcnow import utcnow
from app.database import AsyncSessionLocal
from app.models import (
    Issue,
    MattermostNotificationDelivery,
    MattermostNotificationProfile,
    MattermostUserMapping,
    Task,
)

logger = logging.getLogger(__name__)

MATTERMOST_TARGET_TYPE_CHANNEL = "channel"
MATTERMOST_TARGET_TYPE_INITIATOR_DM = "initiator_dm"
MATTERMOST_TARGET_TYPES = {
    MATTERMOST_TARGET_TYPE_CHANNEL,
    MATTERMOST_TARGET_TYPE_INITIATOR_DM,
}

MATTERMOST_EVENT_TASK_COMPLETED = "task_completed"
MATTERMOST_EVENT_TASK_FAILED = "task_failed"
MATTERMOST_EVENT_TASK_RESCHEDULED = "task_rescheduled"
MATTERMOST_EVENT_TASK_EXECUTE_NOW = "task_execute_now"
MATTERMOST_EVENT_TASK_RETRY_SCHEDULED = "task_retry_scheduled"
MATTERMOST_EVENT_TASK_CANCELLED = "task_cancelled"

MATTERMOST_EVENT_TYPES = (
    MATTERMOST_EVENT_TASK_COMPLETED,
    MATTERMOST_EVENT_TASK_FAILED,
    MATTERMOST_EVENT_TASK_RESCHEDULED,
    MATTERMOST_EVENT_TASK_EXECUTE_NOW,
    MATTERMOST_EVENT_TASK_RETRY_SCHEDULED,
    MATTERMOST_EVENT_TASK_CANCELLED,
)
MATTERMOST_EVENT_TYPE_SET = set(MATTERMOST_EVENT_TYPES)

MATTERMOST_FIELD_TASK_ID = "task_id"
MATTERMOST_FIELD_PROJECT = "project"
MATTERMOST_FIELD_ISSUE = "issue"
MATTERMOST_FIELD_MERGE_REQUEST = "merge_request"
MATTERMOST_FIELD_INITIATOR = "initiator"
MATTERMOST_FIELD_STATUS = "status"
MATTERMOST_FIELD_BRANCH = "branch"
MATTERMOST_FIELD_TARGET_BRANCH = "target_branch"
MATTERMOST_FIELD_SCHEDULED_AT = "scheduled_at"
MATTERMOST_FIELD_SCHEDULE_CHANGE = "schedule_change"
MATTERMOST_FIELD_ERROR = "error"
MATTERMOST_FIELD_TASK_LINK = "task_link"

MATTERMOST_FIELD_KEYS = (
    MATTERMOST_FIELD_TASK_ID,
    MATTERMOST_FIELD_PROJECT,
    MATTERMOST_FIELD_ISSUE,
    MATTERMOST_FIELD_MERGE_REQUEST,
    MATTERMOST_FIELD_INITIATOR,
    MATTERMOST_FIELD_STATUS,
    MATTERMOST_FIELD_BRANCH,
    MATTERMOST_FIELD_TARGET_BRANCH,
    MATTERMOST_FIELD_SCHEDULED_AT,
    MATTERMOST_FIELD_SCHEDULE_CHANGE,
    MATTERMOST_FIELD_ERROR,
    MATTERMOST_FIELD_TASK_LINK,
)
MATTERMOST_FIELD_KEY_SET = set(MATTERMOST_FIELD_KEYS)
_ISSUE_NOT_PROVIDED = object()


class MattermostNotificationError(RuntimeError):
    """Raised when the Mattermost API rejects a request."""


def deserialize_string_list(raw_value: str) -> list[str]:
    """Parse a persisted JSON list of strings."""
    if not raw_value:
        return []

    try:
        loaded = json.loads(raw_value)
    except (TypeError, ValueError):
        return []

    if not isinstance(loaded, list):
        return []

    values: list[str] = []
    for item in loaded:
        if isinstance(item, str):
            trimmed = item.strip()
            if trimmed:
                values.append(trimmed)
    return values


def serialize_string_list(values: list[str]) -> str:
    """Serialize a list of strings as stable JSON."""
    return json.dumps(values, ensure_ascii=True)


def normalize_string_list(values: list[str], allowed: set[str]) -> list[str]:
    """Trim, deduplicate, and filter a list of configurable keys."""
    normalized: list[str] = []
    seen: set[str] = set()

    for raw_value in values:
        value = raw_value.strip()
        if not value or value in seen or value not in allowed:
            continue
        seen.add(value)
        normalized.append(value)

    return normalized


def serialize_profile(profile: MattermostNotificationProfile) -> dict[str, Any]:
    """Convert a profile row into an API-friendly dictionary."""
    return {
        "id": profile.id,
        "name": profile.name,
        "enabled": profile.enabled,
        "target_type": profile.target_type,
        "channel_id": profile.channel_id,
        "mention_in_channel": profile.mention_in_channel,
        "event_types": deserialize_string_list(profile.event_types_json),
        "field_keys": deserialize_string_list(profile.field_keys_json),
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def _format_datetime(value: Optional[datetime]) -> str:
    if value is None:
        return "-"
    return value.isoformat(timespec="seconds")


def _event_label(event_type: str) -> str:
    return {
        MATTERMOST_EVENT_TASK_COMPLETED: "任务完成",
        MATTERMOST_EVENT_TASK_FAILED: "任务失败",
        MATTERMOST_EVENT_TASK_RESCHEDULED: "任务改期",
        MATTERMOST_EVENT_TASK_EXECUTE_NOW: "任务改为立即执行",
        MATTERMOST_EVENT_TASK_RETRY_SCHEDULED: "任务重试已安排",
        MATTERMOST_EVENT_TASK_CANCELLED: "任务已取消",
    }.get(event_type, "任务通知")


def _event_emoji(event_type: str) -> str:
    return {
        MATTERMOST_EVENT_TASK_COMPLETED: "✅",
        MATTERMOST_EVENT_TASK_FAILED: "❌",
        MATTERMOST_EVENT_TASK_RESCHEDULED: "🗓️",
        MATTERMOST_EVENT_TASK_EXECUTE_NOW: "⚡",
        MATTERMOST_EVENT_TASK_RETRY_SCHEDULED: "🔁",
        MATTERMOST_EVENT_TASK_CANCELLED: "🛑",
    }.get(event_type, "ℹ️")


def _event_color(event_type: str) -> str:
    return {
        MATTERMOST_EVENT_TASK_COMPLETED: "good",
        MATTERMOST_EVENT_TASK_FAILED: "danger",
        MATTERMOST_EVENT_TASK_RESCHEDULED: "#2080f0",
        MATTERMOST_EVENT_TASK_EXECUTE_NOW: "#f0a020",
        MATTERMOST_EVENT_TASK_RETRY_SCHEDULED: "#8a63d2",
        MATTERMOST_EVENT_TASK_CANCELLED: "#d03050",
    }.get(event_type, "#2080f0")


class MattermostClient:
    """Minimal async Mattermost API client."""

    def __init__(self, server_url: str, bot_token: str):
        self.server_url = server_url.rstrip("/")
        self.bot_token = bot_token.strip()
        self._client = httpx.AsyncClient(
            base_url=f"{self.server_url}/api/v4",
            headers={
                "Authorization": f"Bearer {self.bot_token}",
                "Content-Type": "application/json",
            },
            timeout=10,
            verify=get_ssl_verify(),
        )
        self._me: Optional[dict[str, Any]] = None

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, *, json_body: Any = None) -> Any:
        response = await self._client.request(method, path, json=json_body)
        if response.status_code >= 400:
            detail = response.text.strip() or response.reason_phrase
            raise MattermostNotificationError(f"{method} {path} failed: {response.status_code} {detail}")
        return response.json()

    async def get_me(self) -> dict[str, Any]:
        if self._me is None:
            self._me = await self._request("GET", "/users/me")
        return self._me

    async def get_user_by_username(self, username: str) -> dict[str, Any]:
        return await self._request("GET", f"/users/username/{username}")

    async def get_channel_by_name(self, team_name: str, channel_name: str) -> dict[str, Any]:
        team = await self._request("GET", f"/teams/name/{team_name}")
        return await self._request("GET", f"/teams/{team['id']}/channels/name/{channel_name}")

    async def get_channel(self, channel_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/channels/{channel_id}")

    async def get_team(self, team_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/teams/{team_id}")

    async def create_direct_channel(self, other_user_id: str) -> dict[str, Any]:
        me = await self.get_me()
        return await self._request("POST", "/channels/direct", json_body=[me["id"], other_user_id])

    async def create_post(self, channel_id: str, message: str, props: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/posts",
            json_body={
                "channel_id": channel_id,
                "message": message,
                "props": props,
            },
        )


async def test_mattermost_connection(
    *,
    server_url: Optional[str] = None,
    bot_token: Optional[str] = None,
) -> dict[str, str]:
    """Validate Mattermost connectivity using stored or preview integration values."""
    settings = get_effective_settings()
    resolved_server_url = (server_url if server_url is not None else settings.mattermost_server_url).strip()
    resolved_bot_token = (bot_token if bot_token is not None else settings.mattermost_bot_token).strip()

    if not resolved_server_url or not resolved_bot_token:
        raise MattermostNotificationError("Mattermost server URL and bot token must both be configured.")

    client = MattermostClient(resolved_server_url, resolved_bot_token)
    try:
        me = await client.get_me()
    finally:
        await client.close()

    return {
        "server_url": resolved_server_url,
        "username": str(me.get("username", "")),
    }


async def _resolve_mattermost_user_id(
    session,
    client: MattermostClient,
    task: Task,
) -> Optional[str]:
    filters = []
    if task.initiator_user_id is not None:
        filters.append(MattermostUserMapping.user_id == task.initiator_user_id)
    if task.initiator_gitlab_user_id is not None:
        filters.append(MattermostUserMapping.gitlab_user_id == task.initiator_gitlab_user_id)
    if task.initiator_username:
        filters.append(MattermostUserMapping.gitlab_username == task.initiator_username)

    existing_mapping = None
    if filters:
        user_mapping_query = select(MattermostUserMapping).where(or_(*filters))
        existing_mapping = (await session.execute(user_mapping_query)).scalars().first()
    if existing_mapping is not None:
        existing_mapping.last_verified_at = utcnow()
        return existing_mapping.mattermost_user_id

    username = (task.initiator_username or "").strip()
    if not username:
        return None

    mattermost_user = await client.get_user_by_username(username)
    mattermost_user_id = str(mattermost_user.get("id", "")).strip()
    if not mattermost_user_id:
        return None

    mapping = existing_mapping or MattermostUserMapping(
        user_id=task.initiator_user_id,
        gitlab_user_id=task.initiator_gitlab_user_id,
        gitlab_username=username,
        mattermost_user_id=mattermost_user_id,
        mattermost_username=str(mattermost_user.get("username", username)),
        source="username",
        last_verified_at=utcnow(),
    )
    if existing_mapping is None:
        session.add(mapping)
    else:
        mapping.mattermost_username = str(mattermost_user.get("username", username))
        mapping.source = "username"
        mapping.last_verified_at = utcnow()

    return mattermost_user_id


def _resolve_render_issue(task: Task, issue: Any = _ISSUE_NOT_PROVIDED) -> Any:
    if issue is not _ISSUE_NOT_PROVIDED:
        return issue
    return getattr(task, "issue", None)


def _build_attachment_fields(
    task: Task,
    event_type: str,
    field_keys: list[str],
    context: dict[str, Any],
    *,
    issue: Any = _ISSUE_NOT_PROVIDED,
) -> list[dict[str, Any]]:
    settings = get_effective_settings()
    task_url = f"{settings.dashboard_url}/tasks/{task.id}"
    render_issue = _resolve_render_issue(task, issue)
    schedule_change = None
    if context.get("previous_scheduled_at") is not None or context.get("scheduled_at") is not None:
        schedule_change = (
            f"{_format_datetime(context.get('previous_scheduled_at'))} → "
            f"{_format_datetime(context.get('scheduled_at'))}"
        )

    field_map: dict[str, Optional[tuple[str, str, bool]]] = {
        MATTERMOST_FIELD_TASK_ID: ("任务 ID", str(task.id), True),
        MATTERMOST_FIELD_PROJECT: ("项目", f"#{task.project_id}", True),
        MATTERMOST_FIELD_ISSUE: (
            "Issue",
            f"#{task.issue_id}" if task.issue_id is not None else "-",
            True,
        ),
        MATTERMOST_FIELD_MERGE_REQUEST: (
            "Merge Request",
            (getattr(render_issue, "merge_request_url", None) or "-") if task.issue_id else "-",
            True,
        ),
        MATTERMOST_FIELD_INITIATOR: ("发起人", task.initiator_username or "-", True),
        MATTERMOST_FIELD_STATUS: ("状态", task.status.value, True),
        MATTERMOST_FIELD_BRANCH: ("分支", (getattr(render_issue, "branch_name", None) or "-") if task.issue_id else "-", True),
        MATTERMOST_FIELD_TARGET_BRANCH: ("目标分支", (getattr(render_issue, "target_branch", None) or "-") if task.issue_id else "-", True),
        MATTERMOST_FIELD_SCHEDULED_AT: ("预约时间", _format_datetime(task.scheduled_at), False),
        MATTERMOST_FIELD_SCHEDULE_CHANGE: ("时间变更", schedule_change or "-", False),
        MATTERMOST_FIELD_ERROR: ("错误摘要", (task.error_message or "-")[:500], False),
        MATTERMOST_FIELD_TASK_LINK: ("任务链接", task_url, False),
    }

    fields: list[dict[str, Any]] = []
    for field_key in field_keys:
        field_value = field_map.get(field_key)
        if field_value is None:
            continue
        title, value, short = field_value
        if value in {"", "-"} and field_key not in {MATTERMOST_FIELD_ISSUE, MATTERMOST_FIELD_ERROR}:
            continue
        fields.append({
            "title": title,
            "value": value,
            "short": short,
        })
    return fields


def _build_card_markdown(
    task: Task,
    event_type: str,
    context: dict[str, Any],
    *,
    issue: Any = _ISSUE_NOT_PROVIDED,
) -> str:
    settings = get_effective_settings()
    task_url = f"{settings.dashboard_url}/tasks/{task.id}"
    lines = [
        f"### {_event_emoji(event_type)} {_event_label(event_type)}",
        f"- 任务: [#{task.id}]({task_url})",
        f"- 项目: #{task.project_id}",
        f"- 状态: `{task.status.value}`",
    ]

    if task.issue_id is not None:
        lines.append(f"- Issue: `#{task.issue_id}`")
    render_issue = _resolve_render_issue(task, issue)
    if render_issue and getattr(render_issue, "merge_request_iid", None) is not None:
        lines.append(f"- Merge Request: `!{render_issue.merge_request_iid}`")
    if task.initiator_username:
        lines.append(f"- 发起人: `{task.initiator_username}`")
    if task.scheduled_at is not None:
        lines.append(f"- 当前预约时间: `{_format_datetime(task.scheduled_at)}`")
    if context.get("previous_scheduled_at") is not None or context.get("scheduled_at") is not None:
        lines.append(
            "- 时间变更: "
            f"`{_format_datetime(context.get('previous_scheduled_at'))} -> {_format_datetime(context.get('scheduled_at'))}`"
        )
    if task.error_message:
        lines.append(f"\n**错误摘要**\n\n{task.error_message[:500]}")

    return "\n".join(lines)


async def notify_task_event(
    task: Task,
    event_type: str,
    *,
    context: Optional[dict[str, Any]] = None,
) -> None:
    """Send Mattermost notifications for one task lifecycle event."""
    if event_type not in MATTERMOST_EVENT_TYPE_SET:
        raise ValueError(f"Unsupported Mattermost event type: {event_type}")

    settings = get_effective_settings()
    if not settings.mattermost_server_url.strip() or not settings.mattermost_bot_token.strip():
        return

    context_data = context or {}

    # Resolve issue data for rendering without mutating the caller's Task.
    # Successful worker notifications run before the caller commits final task
    # status/stats; detaching or reassigning that Task here can drop those
    # pending changes.
    render_issue: Any = _ISSUE_NOT_PROVIDED
    task_state = inspect(task)
    if task_state.expired:
        # The task was expired by an intermediate db.commit() in the caller
        # (e.g. after persisting issue.claude_session_id or merge_request_iid
        # on task completion).  Accessing any expired column attribute in async
        # context raises MissingGreenlet because Task does not use AsyncAttrs.
        # Reload the task — and its issue — from a fresh session so that all
        # attribute access below is safe.
        task_pk = task_state.identity
        if not task_pk:
            logger.warning("notify_task_event: expired task has no identity key; skipping notification")
            return
        task_id_val = task_pk[0]
        async with AsyncSessionLocal() as reload_session:
            reload_result = await reload_session.execute(select(Task).where(Task.id == task_id_val))
            task = reload_result.scalar_one_or_none()
            if task is None:
                logger.warning(
                    "notify_task_event: task %s not found on reload; skipping notification", task_id_val
                )
                return
            if task.issue_id is not None:
                issue_result = await reload_session.execute(select(Issue).where(Issue.id == task.issue_id))
                render_issue = issue_result.scalar_one_or_none()
                if render_issue is not None:
                    reload_session.expunge(render_issue)
                reload_session.expunge(task)
            else:
                render_issue = None
                reload_session.expunge(task)
    elif task.issue_id is not None and "issue" in task_state.unloaded:
        async with AsyncSessionLocal() as session:
            issue_result = await session.execute(
                select(Issue).where(Issue.id == task.issue_id)
            )
            render_issue = issue_result.scalar_one_or_none()
            if render_issue is not None:
                session.expunge(render_issue)
    elif task.issue_id is not None:
        render_issue = getattr(task, "issue", None)
    else:
        render_issue = None

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(MattermostNotificationProfile)
            .where(MattermostNotificationProfile.enabled.is_(True))
            .order_by(MattermostNotificationProfile.id.asc())
        )
        profiles = result.scalars().all()
        if not profiles:
            return

        client = MattermostClient(settings.mattermost_server_url, settings.mattermost_bot_token)
        try:
            for profile in profiles:
                event_types = deserialize_string_list(profile.event_types_json)
                if event_type not in event_types:
                    continue

                target_summary = (
                    f"channel:{profile.channel_id or '-'}"
                    if profile.target_type == MATTERMOST_TARGET_TYPE_CHANNEL
                    else f"dm:{task.initiator_username or '-'}"
                )

                try:
                    fields = _build_attachment_fields(
                        task,
                        event_type,
                        deserialize_string_list(profile.field_keys_json),
                        context_data,
                        issue=render_issue,
                    )
                    task_url = f"{settings.dashboard_url}/tasks/{task.id}"
                    mention_prefix = (
                        f"@{task.initiator_username} "
                        if profile.target_type == MATTERMOST_TARGET_TYPE_CHANNEL
                        and profile.mention_in_channel
                        and task.initiator_username
                        else ""
                    )
                    message = f"{mention_prefix}{_event_emoji(event_type)} {_event_label(event_type)} · [任务 {task.id}]({task_url})"
                    props = {
                        "attachments": [{
                            "color": _event_color(event_type),
                            "title": _event_label(event_type),
                            "fields": fields,
                        }],
                        "card": _build_card_markdown(task, event_type, context_data, issue=render_issue),
                    }

                    if profile.target_type == MATTERMOST_TARGET_TYPE_CHANNEL:
                        channel_id = str(profile.channel_id or "").strip()
                        if not channel_id:
                            raise MattermostNotificationError("Channel profile is missing channel_id.")
                        await client.create_post(channel_id, message, props)
                    else:
                        mattermost_user_id = await _resolve_mattermost_user_id(session, client, task)
                        if not mattermost_user_id:
                            session.add(
                                MattermostNotificationDelivery(
                                    task_id=task.id,
                                    profile_id=profile.id,
                                    event_type=event_type,
                                    status="skipped",
                                    target_summary=target_summary,
                                    error_message="No Mattermost user matched the task initiator.",
                                )
                            )
                            await session.commit()
                            continue

                        direct_channel = await client.create_direct_channel(mattermost_user_id)
                        await client.create_post(str(direct_channel["id"]), message, props)

                    session.add(
                        MattermostNotificationDelivery(
                            task_id=task.id,
                            profile_id=profile.id,
                            event_type=event_type,
                            status="success",
                            target_summary=target_summary,
                            error_message=None,
                        )
                    )
                    await session.commit()
                except Exception as exc:
                    logger.warning("Mattermost notification failed for task %s profile %s: %s", task.id, profile.id, exc)
                    session.add(
                        MattermostNotificationDelivery(
                            task_id=task.id,
                            profile_id=profile.id,
                            event_type=event_type,
                            status="failed",
                            target_summary=target_summary,
                            error_message=str(exc)[:1000],
                        )
                    )
                    await session.commit()
        finally:
            await client.close()
