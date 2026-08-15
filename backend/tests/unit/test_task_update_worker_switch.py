"""F6 §12.3: editing a not-yet-executed Task re-resolves its worker Snapshot.

An explicit ``worker_profile_id`` switch on a PENDING/QUEUED Task re-resolves
the current shared configuration, re-checks runtime readiness, re-freezes the
provider endpoint, and replaces the frozen snapshot. Prompt-only edits must
never refresh the snapshot.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.task_schemas import UpdateTaskRequest
from app.api.task_update_service import TaskUpdateServices, update_task_record
from app.config import get_effective_settings
from app.core.utcnow import utcnow
from app.core.worker_runtime_readiness import fingerprint_from_docker_target
from app.dependencies.project_access import ProjectAccessScope
from app.models import (
    AIProvider,
    Base,
    Issue,
    Task,
    TaskStatus,
    TaskWorkerProfileSnapshot,
    WorkerProfile,
    WorkerRuntimeReadiness,
    WorkerSharedConfiguration,
    WorkerSharedEnvironmentVariable,
)


@pytest.fixture
def db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    return _create


def _services() -> TaskUpdateServices:
    from app.api.task_operations import get_task_with_access_check
    from app.core.task_prompt import render_and_store_task_prompt
    from app.core.worker_profiles import (
        resolve_provider_for_issue,
        select_snapshot_run_instruction_template,
    )

    async def _project_metadata(project_id: int) -> dict:
        return {"project_name": None, "project_path_with_namespace": None}

    return TaskUpdateServices(
        get_task_with_access_check=get_task_with_access_check,
        get_project_metadata=_project_metadata,
        resolve_provider_for_issue=resolve_provider_for_issue,
        select_snapshot_run_instruction_template=select_snapshot_run_instruction_template,
        render_and_store_task_prompt=render_and_store_task_prompt,
    )


def _access_scope() -> ProjectAccessScope:
    return ProjectAccessScope(is_unrestricted=True, accessible_projects=[])


async def _seed_shared(db) -> WorkerSharedConfiguration:
    row = WorkerSharedConfiguration(
        id=1,
        revision=1,
        runtime_mode="mounted_kit",
        worker_kit_version="0.4.0",
        worker_kit_path="/opt/codify/worker-kits/0.4.0",
        volume_mounts=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
    )
    db.add(row)
    db.add(
        WorkerSharedEnvironmentVariable(
            worker_shared_configuration_id=1,
            key="SHARED_A",
            value="a",
            is_secret=False,
        )
    )
    await db.flush()
    return row


async def _seed_provider(db) -> AIProvider:
    provider = AIProvider(
        name="claude-provider",
        base_url="https://api.anthropic.com",
        api_key=None,
        model="claude-sonnet-4-6",
        provider_kind="anthropic_compatible",
        wire_protocol="anthropic_messages",
        provider_driver=None,
        provider_options={},
        credential_ref="mc-1",
    )
    db.add(provider)
    await db.flush()
    return provider


async def _seed_profile(
    db,
    *,
    name: str,
    image: str,
    worker_kit_source: str = "profile",
    runtime_mode: str = "baked_image",
    **overrides,
) -> WorkerProfile:
    kwargs = dict(
        name=name,
        enabled=True,
        is_default=False,
        image=image,
        worker_kit_source=worker_kit_source,
        runtime_mode=runtime_mode,
        volume_mounts=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
    )
    kwargs.update(overrides)
    profile = WorkerProfile(**kwargs)
    profile.environment_variables = []
    profile.default_skills = []
    db.add(profile)
    await db.flush()
    return profile


async def _seed_issue(db, *, worker_profile_id: int) -> Issue:
    issue = Issue(
        project_id=101,
        title="Implement worker profiles",
        description="Implement worker profiles",
        status="open",
        worker_profile_id=worker_profile_id,
    )
    db.add(issue)
    await db.flush()
    return issue


async def _seed_task(
    db,
    *,
    provider_id: int,
    worker_profile_id: int,
    issue_id: int,
    task_id: int = 1,
) -> Task:
    now = datetime(2026, 8, 15, 9, 0, 0)
    task = Task(
        id=task_id,
        issue_id=issue_id,
        project_id=101,
        provider_id=provider_id,
        worker_profile_id=worker_profile_id,
        user_prompt="Original prompt",
        priority=1,
        status=TaskStatus.PENDING,
        task_mode="execute",
        require_changes=True,
        trigger_source="manual",
        session_mode="continue",
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    await db.flush()
    return task


async def _seed_old_snapshot(db, task: Task, profile: WorkerProfile) -> TaskWorkerProfileSnapshot:
    snapshot = TaskWorkerProfileSnapshot(
        task_id=task.id,
        worker_profile_id=profile.id,
        profile_name=profile.name,
        image=profile.image,
        runtime_mode=profile.runtime_mode,
        worker_kit_version=profile.worker_kit_version,
        worker_kit_path=profile.worker_kit_path,
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        harness_key="claude",
        skill_selection_source="profile",
        shared_configuration_revision=1,
        created_at=datetime(2026, 8, 15, 9, 0, 0),
    )
    snapshot.skill_references = []
    db.add(snapshot)
    await db.flush()
    return snapshot


async def _target_fingerprint(db, profile: WorkerProfile) -> str:
    from app.core.worker_shared_configuration import (
        load_shared_configuration,
        resolve_effective_configuration,
    )

    settings = get_effective_settings()
    shared = await load_shared_configuration(db)
    effective = resolve_effective_configuration(profile, shared)
    fingerprint = fingerprint_from_docker_target(
        settings,
        docker_host=getattr(profile, "docker_host", None),
        docker_tls_ca=getattr(profile, "docker_tls_ca", None),
        docker_tls_cert=getattr(profile, "docker_tls_cert", None),
        docker_tls_key=getattr(profile, "docker_tls_key", None),
        runtime_mode=effective.runtime_mode,
        worker_kit_version=effective.worker_kit_version,
        worker_kit_path=effective.worker_kit_path,
    )
    assert fingerprint is not None
    return fingerprint


@pytest.mark.asyncio
async def test_worker_switch_replaces_snapshot_and_refreezes_endpoint(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        provider = await _seed_provider(db)
        source = await _seed_profile(db, name="Source Worker", image="codify-worker/java21:2026.07")
        target = await _seed_profile(db, name="Target Worker", image="codify-worker/java17:2026.08")
        issue = await _seed_issue(db, worker_profile_id=source.id)
        task = await _seed_task(
            db,
            provider_id=provider.id,
            worker_profile_id=source.id,
            issue_id=issue.id,
        )
        await _seed_old_snapshot(db, task, source)
        await db.commit()

        await update_task_record(
            task_id=task.id,
            request=UpdateTaskRequest(worker_profile_id=target.id),
            db=db,
            current_user=None,
            access_scope=_access_scope(),
            services=_services(),
        )

        refreshed_task = await db.get(Task, task.id)
        new_snapshot = await db.get(TaskWorkerProfileSnapshot, task.id)

    assert refreshed_task.worker_profile_id == target.id
    assert refreshed_task.provider_id == provider.id
    assert new_snapshot.worker_profile_id == target.id
    assert new_snapshot.profile_name == "Target Worker"
    assert new_snapshot.image == "codify-worker/java17:2026.08"
    assert new_snapshot.shared_configuration_revision == 1
    # The provider endpoint is re-frozen onto the new snapshot.
    assert new_snapshot.model_endpoint_snapshot is not None
    assert new_snapshot.model_endpoint_snapshot["base_url"] == "https://api.anthropic.com"
    assert new_snapshot.model_endpoint_snapshot["model"] == "claude-sonnet-4-6"
    assert new_snapshot.credential_ref == "mc-1"
    # The worker switch forces a prompt re-render.
    assert refreshed_task.rendered_prompt is not None


@pytest.mark.asyncio
async def test_worker_switch_preserves_task_sourced_skill_selection(db_factory):
    from app.core.skills import replace_task_skill_references, serialize_skill_snapshot
    from app.models import Skill, SkillVersion

    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        provider = await _seed_provider(db)
        source = await _seed_profile(db, name="Source Worker", image="img/source:1")
        target = await _seed_profile(
            db,
            name="Target Worker",
            image="img/target:1",
            worker_kit_source="system",
            runtime_mode="mounted_kit",
            worker_kit_version="0.4.0",
            worker_kit_path="/opt/codify/worker-kits/0.4.0",
        )
        issue = await _seed_issue(db, worker_profile_id=source.id)
        task = await _seed_task(
            db,
            provider_id=provider.id,
            worker_profile_id=source.id,
            issue_id=issue.id,
        )
        snapshot = await _seed_old_snapshot(db, task, source)
        version = SkillVersion(
            name="review-changes",
            description="Review changes before delivery.",
            skill_md=(
                "---\nname: review-changes\ndescription: Review changes.\n---\n\n"
                "Inspect the final diff.\n"
            ),
            files=[],
            package_size_bytes=100,
            digest="a" * 64,
        )
        skill = Skill(
            name=version.name,
            description=version.description,
            current_version=version,
            enabled=True,
        )
        db.add(skill)
        await db.flush()
        replace_task_skill_references(snapshot, [serialize_skill_snapshot(skill)])
        snapshot.skill_selection_source = "task"
        await db.commit()

        await update_task_record(
            task_id=task.id,
            request=UpdateTaskRequest(worker_profile_id=target.id),
            db=db,
            current_user=None,
            access_scope=_access_scope(),
            services=_services(),
        )
        new_snapshot = await db.get(TaskWorkerProfileSnapshot, task.id)

    assert new_snapshot.skill_selection_source == "task"
    skill_ids = [
        reference.skill_id
        for reference in (new_snapshot.skill_references or [])
        if isinstance(getattr(reference, "skill_id", None), int)
    ]
    assert skill_ids == [skill.id]


@pytest.mark.asyncio
async def test_worker_switch_rejects_known_unavailable_runtime_409(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        provider = await _seed_provider(db)
        source = await _seed_profile(db, name="Source Worker", image="img/source:1")
        target = await _seed_profile(
            db,
            name="System Target",
            image="img/system:1",
            worker_kit_source="system",
            runtime_mode="mounted_kit",
            worker_kit_version="0.4.0",
            worker_kit_path="/opt/codify/worker-kits/0.4.0",
        )
        issue = await _seed_issue(db, worker_profile_id=source.id)
        task = await _seed_task(
            db,
            provider_id=provider.id,
            worker_profile_id=source.id,
            issue_id=issue.id,
        )
        await _seed_old_snapshot(db, task, source)
        fingerprint = await _target_fingerprint(db, target)
        db.add(
            WorkerRuntimeReadiness(
                runtime_locator_fingerprint=fingerprint,
                docker_daemon_key="tcp://localhost:2376",
                runtime_mode="mounted_kit",
                worker_kit_version="0.4.0",
                worker_kit_path="/opt/codify/worker-kits/0.4.0",
                status="unavailable",
                failure_code="worker_kit_missing",
                failure_message="worker kit missing",
                checked_at=utcnow(),
            )
        )
        await db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await update_task_record(
                task_id=task.id,
                request=UpdateTaskRequest(worker_profile_id=target.id),
                db=db,
                current_user=None,
                access_scope=_access_scope(),
                services=_services(),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "worker_runtime_unavailable"
    assert exc_info.value.detail["failure_code"] == "worker_kit_missing"


@pytest.mark.asyncio
async def test_prompt_only_edit_does_not_refresh_snapshot(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        provider = await _seed_provider(db)
        source = await _seed_profile(db, name="Source Worker", image="img/source:1")
        issue = await _seed_issue(db, worker_profile_id=source.id)
        task = await _seed_task(
            db,
            provider_id=provider.id,
            worker_profile_id=source.id,
            issue_id=issue.id,
        )
        await _seed_old_snapshot(db, task, source)
        await db.commit()

        await update_task_record(
            task_id=task.id,
            request=UpdateTaskRequest(user_prompt="Changed prompt"),
            db=db,
            current_user=None,
            access_scope=_access_scope(),
            services=_services(),
        )
        refreshed_task = await db.get(Task, task.id)
        snapshot = await db.get(TaskWorkerProfileSnapshot, task.id)

    assert refreshed_task.user_prompt == "Changed prompt"
    assert refreshed_task.worker_profile_id == source.id
    assert snapshot.worker_profile_id == source.id
    assert snapshot.image == "img/source:1"


@pytest.mark.asyncio
async def test_update_task_request_rejects_null_worker_profile_id():
    with pytest.raises(ValidationError):
        UpdateTaskRequest(worker_profile_id=None)


def test_update_task_request_accepts_worker_profile_id():
    request = UpdateTaskRequest(worker_profile_id=5)
    assert request.worker_profile_id == 5
