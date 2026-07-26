"""Shared initiator filtering and option queries for list endpoints."""

from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.project_access import ProjectAccessScope
from app.models import User

INITIATOR_USER_PREFIX = "user:"
INITIATOR_USERNAME_PREFIX = "username:"
INITIATOR_SNAPSHOT_USERNAME_PREFIX = "snapshot:"
UNKNOWN_INITIATOR_VALUE = "unknown"


def _project_scope_conditions(model: Any, access_scope: ProjectAccessScope) -> list[Any]:
    if access_scope.is_unrestricted:
        return []
    if not access_scope.accessible_project_ids:
        return [false()]
    return [model.project_id.in_(access_scope.accessible_project_ids)]


def apply_initiator_filter(query: Any, model: Any, value: str | None) -> Any:
    """Apply stable user, legacy username, and unknown initiator tokens.

    Raw username tokens remain supported for backwards-compatible URLs and API
    clients. New clients should use ``user:<id>``, ``username:<legacy-name>``,
    ``snapshot:<name>``, or ``unknown`` values. Snapshot tokens preserve the
    broad username semantics of the legacy ``initiator_username`` parameter,
    including names that collide with reserved tokens such as ``unknown``.
    """
    if not value:
        return query

    user_ids: list[int] = []
    legacy_usernames: list[str] = []
    snapshot_usernames: list[str] = []
    raw_usernames: list[str] = []
    include_unknown = False

    for raw_token in value.split(","):
        token = raw_token.strip()
        if not token:
            continue
        if token == UNKNOWN_INITIATOR_VALUE:
            include_unknown = True
        elif token.startswith(INITIATOR_USER_PREFIX):
            raw_user_id = token.removeprefix(INITIATOR_USER_PREFIX)
            try:
                user_id = int(raw_user_id)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid initiator value: {token}",
                ) from exc
            if user_id <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid initiator value: {token}",
                )
            user_ids.append(user_id)
        elif token.startswith(INITIATOR_USERNAME_PREFIX):
            username = token.removeprefix(INITIATOR_USERNAME_PREFIX).strip()
            if not username:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid initiator value: {token}",
                )
            legacy_usernames.append(username)
        elif token.startswith(INITIATOR_SNAPSHOT_USERNAME_PREFIX):
            username = token.removeprefix(INITIATOR_SNAPSHOT_USERNAME_PREFIX).strip()
            if not username:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid initiator value: {token}",
                )
            snapshot_usernames.append(username)
        else:
            raw_usernames.append(token)

    conditions: list[Any] = []
    if user_ids:
        conditions.append(model.initiator_user_id.in_(user_ids))
    if legacy_usernames:
        conditions.append(
            and_(
                model.initiator_user_id.is_(None),
                model.initiator_username.in_(legacy_usernames),
            )
        )
    if snapshot_usernames:
        conditions.append(model.initiator_username.in_(snapshot_usernames))
    if raw_usernames:
        conditions.append(model.initiator_username.in_(raw_usernames))
    if include_unknown:
        conditions.append(
            and_(
                model.initiator_user_id.is_(None),
                or_(
                    model.initiator_username.is_(None),
                    func.trim(model.initiator_username) == "",
                ),
            )
        )

    if not conditions:
        return query
    return query.where(or_(*conditions))


async def list_initiator_filter_options(
    db: AsyncSession,
    model: Any,
    access_scope: ProjectAccessScope,
) -> dict[str, list[dict[str, Any]]]:
    """Return complete initiator facets within the caller's project scope."""
    scope_conditions = _project_scope_conditions(model, access_scope)

    linked_result = await db.execute(
        select(
            model.initiator_user_id,
            User.username,
            User.display_name,
            func.max(model.initiator_username).label("snapshot_username"),
            func.count(model.id).label("record_count"),
        )
        .outerjoin(User, User.id == model.initiator_user_id)
        .where(model.initiator_user_id.is_not(None), *scope_conditions)
        .group_by(model.initiator_user_id, User.username, User.display_name)
    )

    options: list[dict[str, Any]] = []
    for user_id, username, display_name, snapshot_username, record_count in linked_result.all():
        effective_username = username or snapshot_username or f"user-{user_id}"
        options.append(
            {
                "value": f"{INITIATOR_USER_PREFIX}{user_id}",
                "kind": "user",
                "user_id": user_id,
                "username": effective_username,
                "display_name": display_name,
                "count": int(record_count or 0),
            }
        )

    normalized_username = func.nullif(func.trim(model.initiator_username), "")
    legacy_result = await db.execute(
        select(
            normalized_username.label("username"),
            func.count(model.id).label("record_count"),
        )
        .where(
            model.initiator_user_id.is_(None),
            normalized_username.is_not(None),
            *scope_conditions,
        )
        .group_by(normalized_username)
    )
    for username, record_count in legacy_result.all():
        options.append(
            {
                "value": f"{INITIATOR_USERNAME_PREFIX}{username}",
                "kind": "legacy",
                "user_id": None,
                "username": username,
                "display_name": None,
                "count": int(record_count or 0),
            }
        )

    unknown_result = await db.execute(
        select(func.count(model.id)).where(
            model.initiator_user_id.is_(None),
            or_(
                model.initiator_username.is_(None),
                func.trim(model.initiator_username) == "",
            ),
            *scope_conditions,
        )
    )
    unknown_count = int(unknown_result.scalar() or 0)
    if unknown_count:
        options.append(
            {
                "value": UNKNOWN_INITIATOR_VALUE,
                "kind": "unknown",
                "user_id": None,
                "username": None,
                "display_name": None,
                "count": unknown_count,
            }
        )

    options.sort(
        key=lambda option: (
            option["kind"] == "unknown",
            (option["display_name"] or option["username"] or "").casefold(),
        )
    )
    return {"initiators": options}
