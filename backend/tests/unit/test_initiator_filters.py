"""Tests for stable initiator filter tokens and scoped option facets."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.initiator_filters import apply_initiator_filter, list_initiator_filter_options
from app.dependencies.project_access import ProjectAccessScope
from app.models import Issue, Task


def test_apply_initiator_filter_supports_stable_legacy_and_unknown_tokens():
    query = apply_initiator_filter(
        select(Task),
        Task,
        "user:7,username:legacy-user,unknown",
    )

    sql = str(query)
    assert "tasks.initiator_user_id IN" in sql
    assert "tasks.initiator_username IN" in sql
    assert "tasks.initiator_user_id IS NULL" in sql
    assert "trim(tasks.initiator_username)" in sql


def test_apply_initiator_filter_keeps_raw_username_compatibility():
    query = apply_initiator_filter(select(Issue), Issue, "alice,bob")

    assert "issues.initiator_username IN" in str(query)


def test_apply_initiator_filter_escapes_reserved_snapshot_username():
    query = apply_initiator_filter(select(Issue), Issue, "snapshot:unknown")
    compiled = query.compile()

    assert "issues.initiator_username IN" in str(compiled)
    assert "trim(issues.initiator_username)" not in str(compiled)
    assert ["unknown"] in compiled.params.values()


def test_apply_initiator_filter_rejects_invalid_stable_user_token():
    with pytest.raises(HTTPException) as exc_info:
        apply_initiator_filter(select(Task), Task, "user:not-a-number")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid initiator value: user:not-a-number"


@pytest.mark.asyncio
async def test_list_initiator_filter_options_is_complete_sorted_and_scoped():
    linked_result = MagicMock()
    linked_result.all.return_value = [
        (2, "bob", None, "bob", 5),
        (1, "alice", "Alice", "old-alice", 8),
    ]
    legacy_result = MagicMock()
    legacy_result.all.return_value = [("legacy-user", 3)]
    unknown_result = MagicMock()
    unknown_result.scalar.return_value = 2

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[linked_result, legacy_result, unknown_result])
    scope = ProjectAccessScope(
        is_unrestricted=False,
        accessible_projects=[{"id": 10}, {"id": 20}],
    )

    result = await list_initiator_filter_options(db, Task, scope)

    assert result == {
        "initiators": [
            {
                "value": "user:1",
                "kind": "user",
                "user_id": 1,
                "username": "alice",
                "display_name": "Alice",
                "count": 8,
            },
            {
                "value": "user:2",
                "kind": "user",
                "user_id": 2,
                "username": "bob",
                "display_name": None,
                "count": 5,
            },
            {
                "value": "username:legacy-user",
                "kind": "legacy",
                "user_id": None,
                "username": "legacy-user",
                "display_name": None,
                "count": 3,
            },
            {
                "value": "unknown",
                "kind": "unknown",
                "user_id": None,
                "username": None,
                "display_name": None,
                "count": 2,
            },
        ]
    }
    assert db.execute.await_count == 3
    for call in db.execute.await_args_list:
        assert "tasks.project_id IN" in str(call.args[0])
