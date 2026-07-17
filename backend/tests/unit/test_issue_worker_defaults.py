from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.issues import CreateIssueRequest, UpdateIssueRequest, create_issue, update_issue
from app.models import Issue, WorkerProfile


def test_issue_worker_is_required_and_cannot_be_changed():
    with pytest.raises(ValidationError):
        CreateIssueRequest(title="Pinned", project_id=100)
    with pytest.raises(ValidationError, match="cannot be changed"):
        UpdateIssueRequest.model_validate({"worker_profile_id": 7})


@pytest.mark.asyncio
async def test_create_issue_persists_explicit_worker_and_default_provider():
    request = CreateIssueRequest(
        title="Add profile defaults",
        project_id=100,
        description="Use issue defaults",
        worker_profile_id=11,
    )

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    async def refresh(issue):
        issue.id = 55
        issue.created_at = datetime(2026, 6, 25, 9, 0, 0)
        issue.updated_at = datetime(2026, 6, 25, 9, 0, 0)

    db.refresh = AsyncMock(side_effect=refresh)
    current_user = SimpleNamespace(id=7, username="alice")

    worker = SimpleNamespace(id=11, enabled=True)
    default_provider = SimpleNamespace(id=22)
    db.get = AsyncMock(return_value=worker)

    with (
        patch("app.api.issues.get_default_provider", new=AsyncMock(return_value=default_provider)),
        patch("app.api.issues.build_issue_workspace_paths", return_value=None),
    ):
        await create_issue(body=request, db=db, current_user=current_user)

    issue = db.add.call_args.args[0]
    assert issue.worker_profile_id == 11
    assert issue.default_provider_id == 22
    db.get.assert_awaited_once_with(WorkerProfile, 11, with_for_update=True)


@pytest.mark.asyncio
async def test_update_issue_changes_provider_but_preserves_pinned_worker():
    issue = Issue(
        id=55,
        title="Add profile defaults",
        project_id=100,
        description="Use issue defaults",
        status="open",
        worker_profile_id=11,
        default_provider_id=22,
        created_at=datetime(2026, 6, 25, 9, 0, 0),
        updated_at=datetime(2026, 6, 25, 9, 0, 0),
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = issue

    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.get = AsyncMock(return_value=SimpleNamespace(id=44, is_disabled=False))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    current_user = SimpleNamespace(id=7, username="alice")

    await update_issue(
        issue_id=55,
        body=UpdateIssueRequest(default_provider_id=44),
        db=db,
        current_user=current_user,
    )

    assert issue.worker_profile_id == 11
    assert issue.default_provider_id == 44


@pytest.mark.asyncio
async def test_reactivating_issue_rejects_unavailable_pinned_worker():
    issue = Issue(
        id=55,
        title="Closed issue",
        project_id=100,
        status="closed",
        worker_profile_id=11,
        created_at=datetime(2026, 6, 25, 9, 0, 0),
        updated_at=datetime(2026, 6, 25, 9, 0, 0),
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = issue
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.get = AsyncMock(return_value=SimpleNamespace(id=11, enabled=False))
    db.commit = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await update_issue(
            issue_id=55,
            body=UpdateIssueRequest(status="open"),
            db=db,
            current_user=SimpleNamespace(id=7, username="alice"),
        )

    assert getattr(exc.value, "status_code", None) == 422
    assert issue.status == "closed"
    db.get.assert_awaited_once_with(WorkerProfile, 11, with_for_update=True)
    db.commit.assert_not_awaited()
