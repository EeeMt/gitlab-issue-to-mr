from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.issues import CreateIssueRequest, UpdateIssueRequest, create_issue, update_issue
from app.models import Issue


@pytest.mark.asyncio
async def test_create_issue_persists_current_default_worker_and_provider():
    request = CreateIssueRequest(
        title="Add profile defaults",
        project_id=100,
        description="Use issue defaults",
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

    default_worker = SimpleNamespace(id=11)
    default_provider = SimpleNamespace(id=22)

    with (
        patch(
            "app.api.issues.get_default_worker_profile",
            new=AsyncMock(return_value=default_worker),
        ),
        patch("app.api.issues.get_default_provider", new=AsyncMock(return_value=default_provider)),
        patch("app.api.issues.build_issue_workspace_paths", return_value=None),
    ):
        await create_issue(body=request, db=db, current_user=current_user)

    issue = db.add.call_args.args[0]
    assert issue.default_worker_profile_id == 11
    assert issue.default_provider_id == 22


@pytest.mark.asyncio
async def test_update_issue_changes_default_worker_and_provider():
    issue = Issue(
        id=55,
        title="Add profile defaults",
        project_id=100,
        description="Use issue defaults",
        status="open",
        default_worker_profile_id=11,
        default_provider_id=22,
        created_at=datetime(2026, 6, 25, 9, 0, 0),
        updated_at=datetime(2026, 6, 25, 9, 0, 0),
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = issue

    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.get = AsyncMock(
        side_effect=[
            SimpleNamespace(id=33, enabled=True),
            SimpleNamespace(id=44, is_disabled=False),
        ]
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    current_user = SimpleNamespace(id=7, username="alice")

    await update_issue(
        issue_id=55,
        body=UpdateIssueRequest(default_worker_profile_id=33, default_provider_id=44),
        db=db,
        current_user=current_user,
    )

    assert issue.default_worker_profile_id == 33
    assert issue.default_provider_id == 44
