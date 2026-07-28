import base64
import io
import tarfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.skills import (
    SkillCreateRequest,
    SkillFilePayload,
    SkillUpdateRequest,
    create_skill,
    delete_skill,
    enable_skill,
    get_skill_for_admin,
    list_all_skills,
    list_enabled_skills,
    update_skill,
)
from app.core.skills import (
    MAX_TASK_SKILL_PACKAGE_BYTES,
    WORKER_PROFILE_SKILL_PACKAGE_LOCK_KEY,
    SkillValidationError,
    acquire_worker_profile_skill_package_lock,
    build_skill_version,
    delete_unreferenced_skill_versions,
    hydrate_skill_snapshots,
    normalize_skill_files,
    replace_task_skill_references,
    resolve_task_skill_snapshots,
    validate_runtime_supports_skills,
)
from app.core.worker_profiles import WorkerProfileValidationError, load_task_worker_runtime
from app.core.worker_runtime import build_task_runtime_archive
from app.models import (
    Base,
    Skill,
    SkillVersion,
    TaskSkillVersionReference,
    TaskWorkerProfileSnapshot,
    WorkerProfile,
)


@pytest.mark.asyncio
async def test_worker_profile_skill_package_lock_uses_postgres_transaction_lock():
    db = MagicMock()
    db.get_bind.return_value = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql")
    )
    db.execute = AsyncMock()

    await acquire_worker_profile_skill_package_lock(db)

    statement, parameters = db.execute.await_args.args
    assert str(statement) == "SELECT pg_advisory_xact_lock(:key)"
    assert parameters == {"key": WORKER_PROFILE_SKILL_PACKAGE_LOCK_KEY}


def _skill_md(
    description: str,
    instructions: str,
    extra_frontmatter: str = "",
    *,
    name: str = "review-changes",
) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"{extra_frontmatter}"
        "---\n\n"
        f"{instructions}\n"
    )


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _profile(**overrides):
    values = {
        "name": "worker",
        "enabled": True,
        "is_default": False,
        "image": "worker:latest",
        "runtime_mode": "mounted_kit",
        "worker_kit_version": "0.3.5",
        "worker_kit_path": "/opt/codify/worker-kits/0.3.5-linux-amd64",
        "volume_mounts": [],
        "environment_variables": [],
        "default_skills": [],
        "pre_script": "",
        "post_script": "",
        "default_execute_run_instruction_template": "{{user_prompt}}",
        "default_plan_run_instruction_template": "{{user_prompt}}",
        "ci_auto_repair_run_instruction_template": "{{user_prompt}}",
    }
    values.update(overrides)
    return WorkerProfile(**values)


@pytest.mark.asyncio
async def test_skill_crud_and_enabled_listing():
    engine, factory = await _session_factory()
    try:
        async with factory() as db:
            created = await create_skill(
                SkillCreateRequest(
                    name="review-changes",
                    skill_md=_skill_md(
                        "Review changes when a task asks for code review.",
                        "Inspect the diff and report findings first.",
                        "allowed-tools: Read Grep\ncontext: fork\n",
                    ),
                    files=[
                        SkillFilePayload(
                            path="scripts/check.sh",
                            content_base64=base64.b64encode(b"#!/bin/sh\nexit 0\n").decode(),
                            executable=True,
                        ),
                        SkillFilePayload(
                            path="references/checklist.md",
                            content_base64=base64.b64encode(b"# Checklist\n").decode(),
                        ),
                    ],
                ),
                db=db,
            )
            assert created.name == "review-changes"
            assert "allowed-tools: Read Grep" in created.skill_md
            assert "context: fork" in created.skill_md
            assert [item.path for item in created.files] == [
                "references/checklist.md",
                "scripts/check.sh",
            ]
            managed_skill = await db.get(Skill, created.id)
            original_version_id = managed_skill.current_version_id
            task_snapshot = TaskWorkerProfileSnapshot(
                task_id=901,
                profile_name="worker",
                image="worker:latest",
                volume_mounts=[],
                environment_variables=[],
                skill_references=[
                    TaskSkillVersionReference(
                        position=0,
                        skill_id=managed_skill.id,
                        skill_version_id=original_version_id,
                        name=managed_skill.name,
                        description=managed_skill.description,
                    )
                ],
                pre_script="",
                post_script="",
                default_execute_run_instruction_template="{{user_prompt}}",
                default_plan_run_instruction_template="{{user_prompt}}",
                ci_auto_repair_run_instruction_template="{{user_prompt}}",
            )
            db.add(task_snapshot)
            await db.flush()
            options = await list_enabled_skills(db)
            assert [skill.model_dump() for skill in options] == [
                {
                    "id": created.id,
                    "name": "review-changes",
                    "description": "Review changes when a task asks for code review.",
                    "version_id": original_version_id,
                }
            ]

            disabled = await update_skill(
                created.id,
                SkillUpdateRequest(
                    enabled=False,
                    skill_md=_skill_md(
                        "Review changes when a task asks for code review.",
                        "Review the complete code path.",
                    ),
                ),
                db=db,
            )
            assert disabled.enabled is False
            assert len((await get_skill_for_admin(created.id, db=db)).files) == 2
            await db.refresh(managed_skill)
            assert managed_skill.current_version_id != original_version_id
            replacement_version_id = managed_skill.current_version_id
            assert await db.get(SkillVersion, original_version_id) is not None
            assert await list_enabled_skills(db) == []
            assert [skill.id for skill in await list_all_skills(db)] == [created.id]

            profile = _profile(default_skills=[managed_skill])
            db.add(profile)
            await db.commit()
            await delete_skill(created.id, db=db)
            await db.refresh(profile, attribute_names=["default_skills"])
            assert await list_all_skills(db) == []
            assert profile.default_skills == []
            assert await db.get(SkillVersion, original_version_id) is not None
            assert await db.get(SkillVersion, replacement_version_id) is None
            await db.delete(task_snapshot)
            await db.flush()
            assert await delete_unreferenced_skill_versions(db) == 1
            assert await db.get(SkillVersion, original_version_id) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_skill_rename_conflict_returns_409_and_preserves_original_version():
    engine, factory = await _session_factory()
    try:
        async with factory() as db:
            first = await create_skill(
                SkillCreateRequest(
                    name="review-changes",
                    skill_md=_skill_md("Review changes.", "Review the diff."),
                ),
                db=db,
            )
            await create_skill(
                SkillCreateRequest(
                    name="run-tests",
                    skill_md=_skill_md(
                        "Run focused tests.",
                        "Run the relevant tests.",
                        name="run-tests",
                    ),
                ),
                db=db,
            )
            managed_first = await db.get(Skill, first.id)
            original_version_id = managed_first.current_version_id

            with pytest.raises(HTTPException) as exc_info:
                await update_skill(
                    first.id,
                    SkillUpdateRequest(
                        name="run-tests",
                        skill_md=_skill_md(
                            "Run focused tests.",
                            "Use the renamed Skill.",
                            name="run-tests",
                        ),
                    ),
                    db=db,
                )

            assert exc_info.value.status_code == 409
            assert exc_info.value.detail == "Skill with name 'run-tests' already exists"
            result = await db.execute(
                select(Skill)
                .where(Skill.id == first.id)
                .execution_options(populate_existing=True)
            )
            reloaded = result.scalar_one()
            assert reloaded.name == "review-changes"
            assert reloaded.current_version_id == original_version_id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_task_selection_snapshots_profile_defaults_and_rejects_disabled_override():
    engine, factory = await _session_factory()
    try:
        async with factory() as db:
            first_version = build_skill_version(
                name="backend-review",
                skill_md=_skill_md(
                    "Review backend changes.",
                    "Inspect database and API behavior.",
                    name="backend-review",
                ),
                files=[],
            )
            first = Skill(
                name=first_version.name,
                description=first_version.description,
                current_version=first_version,
                enabled=True,
            )
            disabled_version = build_skill_version(
                name="disabled-skill",
                skill_md=_skill_md(
                    "Unavailable instructions.",
                    "Do not run.",
                    name="disabled-skill",
                ),
                files=[],
            )
            disabled = Skill(
                name=disabled_version.name,
                description=disabled_version.description,
                current_version=disabled_version,
                enabled=False,
            )
            db.add_all([first, disabled])
            await db.flush()
            profile = _profile(default_skills=[first])
            db.add(profile)
            await db.flush()

            inherited = await resolve_task_skill_snapshots(db, profile, None)
            assert inherited == [
                {
                    "id": first.id,
                    "name": "backend-review",
                    "description": "Review backend changes.",
                    "version_id": first_version.id,
                }
            ]

            replacement = build_skill_version(
                name="backend-review",
                skill_md=_skill_md(
                    "Review backend changes.",
                    "Changed after task creation.",
                    name="backend-review",
                ),
                files=[],
            )
            db.add(replacement)
            first.current_version = replacement
            await db.flush()
            hydrated = await hydrate_skill_snapshots(db, inherited)
            assert "Inspect database and API behavior." in hydrated[0]["skill_md"]

            with pytest.raises(SkillValidationError, match="disabled"):
                await resolve_task_skill_snapshots(db, profile, [disabled.id])
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_replacing_task_skill_selection_updates_ordered_reference_rows():
    engine, factory = await _session_factory()
    try:
        async with factory() as db:
            first = build_skill_version(
                name="first-skill",
                skill_md=_skill_md(
                    "First skill.",
                    "Run the first workflow.",
                    name="first-skill",
                ),
                files=[],
            )
            second = build_skill_version(
                name="second-skill",
                skill_md=_skill_md(
                    "Second skill.",
                    "Run the second workflow.",
                    name="second-skill",
                ),
                files=[],
            )
            db.add_all([first, second])
            await db.flush()
            snapshot = TaskWorkerProfileSnapshot(
                task_id=902,
                profile_name="worker",
                image="worker:latest",
                volume_mounts=[],
                environment_variables=[],
                skill_references=[],
                pre_script="",
                post_script="",
                default_execute_run_instruction_template="{{user_prompt}}",
                default_plan_run_instruction_template="{{user_prompt}}",
                ci_auto_repair_run_instruction_template="{{user_prompt}}",
            )
            replace_task_skill_references(
                snapshot,
                [
                    {
                        "id": None,
                        "name": first.name,
                        "description": first.description,
                        "version_id": first.id,
                    }
                ],
            )
            db.add(snapshot)
            await db.commit()

            replace_task_skill_references(
                snapshot,
                [
                    {
                        "id": None,
                        "name": second.name,
                        "description": second.description,
                        "version_id": second.id,
                    }
                ],
            )
            await db.flush()

            assert len(snapshot.skill_references) == 1
            assert snapshot.skill_references[0].position == 0
            assert snapshot.skill_references[0].skill_version_id == second.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_skill_update_cannot_break_existing_worker_profile_package_limit():
    engine, factory = await _session_factory()
    try:
        async with factory() as db:
            target_version = build_skill_version(
                name="target-skill",
                skill_md=_skill_md(
                    "Target skill.",
                    "Run the target workflow.",
                    name="target-skill",
                ),
                files=[],
            )
            target = Skill(
                name=target_version.name,
                description=target_version.description,
                current_version=target_version,
                enabled=True,
            )
            large_version = build_skill_version(
                name="large-skill",
                skill_md=_skill_md(
                    "Large skill.",
                    "Run the large workflow.",
                    name="large-skill",
                ),
                files=[],
            )
            large_version.package_size_bytes = MAX_TASK_SKILL_PACKAGE_BYTES - 1000
            large = Skill(
                name=large_version.name,
                description=large_version.description,
                current_version=large_version,
                enabled=True,
            )
            profile = _profile(default_skills=[target, large])
            db.add(profile)
            await db.commit()

            target_id = target.id
            original_version_id = target.current_version_id
            with pytest.raises(HTTPException) as exc_info:
                await update_skill(
                    target_id,
                    SkillUpdateRequest(
                        skill_md=_skill_md(
                            "Target skill.",
                            "x" * 2000,
                            name="target-skill",
                        )
                    ),
                    db=db,
                )
            assert exc_info.value.status_code == 422
            assert "Worker Profile 'worker'" in str(exc_info.value.detail)
            persisted = await db.get(Skill, target_id)
            assert persisted.current_version_id == original_version_id

            persisted.enabled = False
            await db.commit()
            await update_skill(
                target_id,
                SkillUpdateRequest(
                    skill_md=_skill_md(
                        "Target skill.",
                        "x" * 2000,
                        name="target-skill",
                    )
                ),
                db=db,
            )
            with pytest.raises(HTTPException) as enable_exc_info:
                await enable_skill(target_id, db=db)
            assert enable_exc_info.value.status_code == 422
            assert "Worker Profile 'worker'" in str(enable_exc_info.value.detail)
    finally:
        await engine.dispose()


def test_mounted_worker_kit_must_support_non_empty_skill_snapshot():
    with pytest.raises(SkillValidationError, match="baked-image mode is deprecated"):
        validate_runtime_supports_skills(
            SimpleNamespace(runtime_mode="baked_image", worker_kit_version=None),
            [{"name": "review"}],
        )

    with pytest.raises(SkillValidationError, match="0.3.5 or newer"):
        validate_runtime_supports_skills(
            SimpleNamespace(runtime_mode="mounted_kit", worker_kit_version="0.3.4"),
            [{"name": "review"}],
        )

    validate_runtime_supports_skills(
        SimpleNamespace(runtime_mode="mounted_kit", worker_kit_version="0.3.5"),
        [{"name": "review"}],
    )


def test_skill_markdown_requires_matching_claude_compatible_frontmatter():
    with pytest.raises(SkillValidationError, match="requires a text name"):
        build_skill_version(
            name="review-changes",
            skill_md="---\ndescription: Review changes.\n---\n\nInspect the diff.\n",
            files=[],
        )

    with pytest.raises(SkillValidationError, match="must match Skill name"):
        build_skill_version(
            name="review-changes",
            skill_md=_skill_md(
                "Review changes.",
                "Inspect the diff.",
                name="different-name",
            ),
            files=[],
        )

    with pytest.raises(SkillValidationError, match="reserved words"):
        build_skill_version(
            name="claude-review",
            skill_md=_skill_md(
                "Review changes.",
                "Inspect the diff.",
                name="claude-review",
            ),
            files=[],
        )


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("../secret", "Invalid skill file path"),
        ("/absolute", "Invalid skill file path"),
        ("scripts\\check.sh", "Invalid skill file path"),
        ("SKILL.md", "package entry point"),
        ("SKILL.md/nested", "package entry point"),
    ],
)
def test_skill_package_rejects_unsafe_paths(path, message):
    with pytest.raises(SkillValidationError, match=message):
        normalize_skill_files(
            [{"path": path, "content_base64": "", "executable": False}]
        )


def test_skill_package_rejects_invalid_base64_and_file_directory_conflicts():
    with pytest.raises(SkillValidationError, match="valid base64"):
        normalize_skill_files(
            [{"path": "references/readme.md", "content_base64": "%%%", "executable": False}]
        )

    with pytest.raises(SkillValidationError, match="conflicts with directory"):
        normalize_skill_files(
            [
                {"path": "references", "content_base64": "", "executable": False},
                {"path": "references-old", "content_base64": "", "executable": False},
                {"path": "references/readme.md", "content_base64": "", "executable": False},
            ]
        )


@pytest.mark.asyncio
async def test_worker_runtime_explicitly_loads_deferred_skill_content():
    engine, factory = await _session_factory()
    try:
        async with factory() as db:
            version = build_skill_version(
                name="review-changes",
                skill_md=_skill_md(
                    "Review changes before delivery.",
                    "Inspect the final diff.",
                ),
                files=[
                    {
                        "path": "references/checklist.md",
                        "content_base64": base64.b64encode(b"# Checklist\n").decode(),
                        "executable": False,
                    }
                ],
            )
            db.add(version)
            await db.flush()
            db.add(
                TaskWorkerProfileSnapshot(
                    task_id=41,
                    profile_name="worker",
                    image="worker:latest",
                    runtime_mode="mounted_kit",
                    worker_kit_version="0.3.5",
                    worker_kit_path="/opt/codify/worker-kits/0.3.5-linux-amd64",
                    volume_mounts=[],
                    environment_variables=[],
                    skill_references=[
                        TaskSkillVersionReference(
                            position=0,
                            skill_id=7,
                            skill_version_id=version.id,
                            name="review-changes",
                            description="Review changes before delivery.",
                        )
                    ],
                    pre_script="",
                    post_script="",
                    default_execute_run_instruction_template="{{user_prompt}}",
                    default_plan_run_instruction_template="{{user_prompt}}",
                    ci_auto_repair_run_instruction_template="{{user_prompt}}",
                )
            )
            await db.commit()
            db.sync_session.expunge_all()

            snapshot = (
                await db.execute(
                    select(TaskWorkerProfileSnapshot).where(
                        TaskWorkerProfileSnapshot.task_id == 41
                    )
                )
            ).scalar_one()
            assert "skill_references" in sa_inspect(snapshot).unloaded

            runtime = await load_task_worker_runtime(db, SimpleNamespace(id=41))
            assert "Inspect the final diff." in runtime.skills[0]["skill_md"]
            assert runtime.skills[0]["files"][0]["path"] == "references/checklist.md"

            snapshot.runtime_mode = "baked_image"
            snapshot.worker_kit_version = None
            snapshot.worker_kit_path = None
            await db.commit()
            with pytest.raises(WorkerProfileValidationError, match="baked-image mode"):
                await load_task_worker_runtime(db, SimpleNamespace(id=41))
    finally:
        await engine.dispose()


def test_runtime_archive_contains_task_scoped_claude_skill_without_home_mount():
    archive_bytes = build_task_runtime_archive(
        SimpleNamespace(id=41, rendered_prompt="Implement the change"),
        skills=[
            {
                "id": 7,
                "name": "review-changes",
                "description": "Review changes before delivery.",
                "skill_md": _skill_md(
                    "Review changes before delivery.",
                    "Run focused tests and inspect the final diff.",
                    "allowed-tools: Read Grep\ncontext: fork\n",
                ),
                "files": [
                    {
                        "path": "scripts/check.sh",
                        "content_base64": base64.b64encode(b"#!/bin/sh\nexit 0\n").decode(),
                        "executable": True,
                    },
                    {
                        "path": "references/checklist.md",
                        "content_base64": base64.b64encode(b"# Checklist\n").decode(),
                        "executable": False,
                    },
                ],
            }
        ],
    )
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
        names = archive.getnames()
        skill_path = (
            "codify-runtime/skill-scope/.claude/skills/review-changes/SKILL.md"
        )
        assert skill_path in names
        script_path = (
            "codify-runtime/skill-scope/.claude/skills/review-changes/scripts/check.sh"
        )
        reference_path = (
            "codify-runtime/skill-scope/.claude/skills/review-changes/"
            "references/checklist.md"
        )
        assert script_path in names
        assert reference_path in names
        assert not any(name.startswith("home/") for name in names)
        content = archive.extractfile(skill_path).read().decode("utf-8")
        assert archive.extractfile(script_path).read() == b"#!/bin/sh\nexit 0\n"
        assert archive.getmember(script_path).mode == 0o755
        assert archive.getmember(reference_path).mode == 0o644
    assert "allowed-tools: Read Grep" in content
    assert "context: fork" in content
    assert content.endswith("Run focused tests and inspect the final diff.\n")
