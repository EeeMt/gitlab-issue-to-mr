from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.issues import (
    CreateIssueRequest,
    UpdateIssueRequest,
    _resolve_issue_default_harness_key,
    _resolve_issue_worker_id,
    create_issue,
    update_issue,
)
from app.models import Issue, WorkerProfile


def test_issue_worker_is_required_and_cannot_be_changed():
    with pytest.raises(ValidationError):
        CreateIssueRequest(title="Pinned", project_id=100)
    with pytest.raises(ValidationError, match="cannot be changed"):
        UpdateIssueRequest.model_validate({"worker_profile_id": 7})
    with pytest.raises(ValidationError, match="cannot be changed"):
        UpdateIssueRequest.model_validate({"git_clone_depth": 50})
    with pytest.raises(ValidationError, match="cannot be changed"):
        UpdateIssueRequest.model_validate({"git_clone_filter": "blob:none"})


def test_issue_git_clone_options_are_validated():
    full = CreateIssueRequest(title="Full", project_id=100, worker_profile_id=11)
    assert full.git_clone_depth is None
    assert full.git_clone_filter is None

    optimized = CreateIssueRequest(
        title="Optimized",
        project_id=100,
        worker_profile_id=11,
        git_clone_depth=50,
        git_clone_filter="blob:none",
    )
    assert optimized.git_clone_depth == 50
    assert optimized.git_clone_filter == "blob:none"

    with pytest.raises(ValidationError):
        CreateIssueRequest(
            title="Invalid depth",
            project_id=100,
            worker_profile_id=11,
            git_clone_depth=0,
        )
    with pytest.raises(ValidationError):
        CreateIssueRequest(
            title="Boolean depth",
            project_id=100,
            worker_profile_id=11,
            git_clone_depth=True,
        )
    with pytest.raises(ValidationError):
        CreateIssueRequest.model_validate(
            {
                "title": "Invalid filter",
                "project_id": 100,
                "worker_profile_id": 11,
                "git_clone_filter": "tree:0",
            }
        )


@pytest.mark.asyncio
async def test_repository_clone_options_require_a_compatible_mounted_worker_kit():
    db = MagicMock()
    old_profile = SimpleNamespace(
        id=11,
        enabled=True,
        runtime_mode="mounted_kit",
        worker_kit_version="0.2.0",
    )
    db.get = AsyncMock(return_value=old_profile)

    with pytest.raises(HTTPException, match="worker-kit 0.3.0 or newer") as exc_info:
        await _resolve_issue_worker_id(
            db,
            11,
            requires_repository_policy=True,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == (
        "repository_clone_worker_kit_version_required"
    )

    # Full-clone Issues preserve compatibility with an older mounted kit.
    assert await _resolve_issue_worker_id(db, 11) == 11

    baked_profile = SimpleNamespace(
        id=13,
        enabled=True,
        runtime_mode="baked_image",
        worker_kit_version=None,
    )
    db.get = AsyncMock(return_value=baked_profile)
    with pytest.raises(HTTPException, match="mounted-kit worker profile") as exc_info:
        await _resolve_issue_worker_id(
            db,
            13,
            requires_repository_policy=True,
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "repository_clone_requires_mounted_kit"

    # Full-clone Issues remain valid for baked-image workers.
    assert await _resolve_issue_worker_id(db, 13) == 13

    compatible_profile = SimpleNamespace(
        id=12,
        enabled=True,
        runtime_mode="mounted_kit",
        worker_kit_version="0.3.0",
    )
    db.get = AsyncMock(return_value=compatible_profile)
    assert (
        await _resolve_issue_worker_id(
            db,
            12,
            requires_repository_policy=True,
        )
        == 12
    )


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
        patch(
            "app.api.issues._resolve_issue_default_harness_key",
            new=AsyncMock(return_value="claude"),
        ),
        patch("app.api.issues.build_issue_workspace_paths", return_value=None),
    ):
        await create_issue(body=request, db=db, current_user=current_user)

    issue = db.add.call_args.args[0]
    assert issue.worker_profile_id == 11
    assert issue.default_provider_id == 22
    assert issue.default_harness_key == "claude"
    db.get.assert_awaited_once_with(WorkerProfile, 11, with_for_update=True)


@pytest.mark.asyncio
async def test_create_issue_resolves_profile_default_harness_key():
    request = CreateIssueRequest(
        title="Use harness default",
        project_id=100,
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
    profile = SimpleNamespace(
        id=11,
        enabled=True,
        enabled_harnesses=["claude", "codex"],
        default_harness_key="codex",
    )
    db.get = AsyncMock(return_value=profile)

    with (
        patch("app.api.issues._resolve_issue_worker_id", new=AsyncMock(return_value=11)),
        patch(
            "app.api.issues._resolve_issue_default_provider_id",
            new=AsyncMock(return_value=None),
        ),
        patch("app.api.issues.build_issue_workspace_paths", return_value=None),
    ):
        await create_issue(body=request, db=db, current_user=current_user)

    issue = db.add.call_args.args[0]
    assert issue.default_harness_key == "codex"


@pytest.mark.asyncio
async def test_issue_default_harness_must_be_enabled_by_worker():
    db = MagicMock()
    db.get = AsyncMock(
        return_value=SimpleNamespace(
            id=11,
            enabled=True,
            enabled_harnesses=["claude"],
            default_harness_key="claude",
        )
    )

    with pytest.raises(HTTPException, match="codex") as exc_info:
        await _resolve_issue_default_harness_key(db, 11, "codex")

    assert exc_info.value.status_code == 422

    with pytest.raises(HTTPException, match="unknown harness key") as exc_info:
        await _resolve_issue_default_harness_key(db, 11, "fake")

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_update_issue_changes_default_harness():
    issue = Issue(
        id=55,
        title="Update harness default",
        project_id=100,
        status="open",
        worker_profile_id=11,
        default_harness_key="claude",
        created_at=datetime(2026, 6, 25, 9, 0, 0),
        updated_at=datetime(2026, 6, 25, 9, 0, 0),
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = issue

    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.get = AsyncMock(
        return_value=SimpleNamespace(
            id=11,
            enabled=True,
            enabled_harnesses=["claude", "codex"],
            default_harness_key="claude",
        )
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    await update_issue(
        issue_id=55,
        body=UpdateIssueRequest(default_harness_key="codex"),
        db=db,
        current_user=SimpleNamespace(id=7, username="alice"),
    )

    assert issue.default_harness_key == "codex"


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
