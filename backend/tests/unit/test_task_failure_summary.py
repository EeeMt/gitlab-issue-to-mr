from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.task_failure_summary import load_task_failure_summary


def _result(scalar_value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    return result


@pytest.mark.asyncio
async def test_returns_none_when_task_has_no_attempt():
    db = AsyncMock()
    db.execute.return_value = _result(None)

    assert await load_task_failure_summary(db, 1) == {
        "failure_kind": None,
        "failure_message": None,
    }


@pytest.mark.asyncio
async def test_returns_none_when_terminal_event_is_missing():
    db = AsyncMock()
    db.execute.side_effect = [_result("attempt-1"), _result(None)]

    assert await load_task_failure_summary(db, 1) == {
        "failure_kind": None,
        "failure_message": None,
    }


@pytest.mark.asyncio
async def test_extracts_failure_kind_and_message():
    event = {
        "type": "run.failed",
        "payload": {
            "status": "failed",
            "failure": {
                "kind": "protocol_error",
                "message": "Harness stream ended without result",
                "exit_code": 1,
            },
        },
    }
    db = AsyncMock()
    db.execute.side_effect = [_result("attempt-1"), _result(event)]

    assert await load_task_failure_summary(db, 1) == {
        "failure_kind": "protocol_error",
        "failure_message": "Harness stream ended without result",
    }


@pytest.mark.asyncio
async def test_falls_back_to_terminal_status_when_failure_payload_missing():
    event = {"type": "run.failed", "payload": {"status": "cancelled"}}
    db = AsyncMock()
    db.execute.side_effect = [_result("attempt-1"), _result(event)]

    assert await load_task_failure_summary(db, 1) == {
        "failure_kind": "cancelled",
        "failure_message": None,
    }
