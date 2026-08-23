"""Business implementations for creating and retrying tasks."""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.task_operations import require_task_execution_writer
from app.api.task_responses import (
    apply_queue_context,
    attach_task_worker_snapshot,
    compute_task_queue_contexts,
    refresh_task_response_state,
    serialize_task,
)
from app.api.task_schemas import CreateTaskRequest, RetryTaskRequest
from app.config import get_effective_settings
from app.core.harness_execution_policy import (
    ExecutionPolicyError,
    require_creatable_bundle_v2,
    require_task_executable_contract,
)
from app.core.harness_registry import (
    HarnessRegistryError,
    validate_enabled_harnesses,
)
from app.core.harness_sessions import get_issue_latest_harness_key, session_namespace_for
from app.core.issue_task_order import (
    IssueOrderIntegrityError,
    LineageConflict,
    ScheduleWindowConflict,
    ensure_issue_order_integrity_locked,
    project_tail_lineage,
    validate_schedule_time_locked,
)
from app.core.model_endpoints import (
    COMPAT_PROFILES,
    ensure_harness_protocol_compatibility,
    normalize_endpoint,
)
from app.core.scheduling import resolve_scheduled_at
from app.core.skills import SkillValidationError
from app.core.task_prompt import FREEFORM_RUN_INSTRUCTION_TEMPLATE, TaskPromptValidationError
from app.core.usage_limits import UsageLimitExceeded, usage_limit_exceeded_detail
from app.core.utcnow import utcnow
from app.core.worker_profiles import WorkerProfileValidationError
from app.core.worker_runtime_readiness import (
    read_runtime_readiness,
    readiness_for_profile,
    runtime_unavailable_http_detail,
)
from app.core.worker_shared_configuration import load_shared_configuration
from app.dependencies.project_access import ProjectAccessScope, require_project_access
from app.models import Issue, Task, User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskCreationServices:
    require_issue_operator: Callable[..., Any]
    get_task_with_access_check: Callable[..., Any]
    validate_task_status_for_retry: Callable[..., Any]
    validate_scheduled_datetime_in_future: Callable[..., Any]
    get_usage_quota_service: Callable[..., Any]
    get_project_metadata: Callable[..., Any]
    resolve_provider_for_issue: Callable[..., Any]
    resolve_worker_profile_for_issue: Callable[..., Any]
    prepare_task_runtime_snapshot: Callable[..., Any]
    replace_task_worker_snapshot: Callable[..., Any]
    clone_task_worker_snapshot: Callable[..., Any]
    bind_runtime_bundle: Callable[..., Any]
    select_snapshot_run_instruction_template: Callable[..., Any]
    render_and_store_task_prompt: Callable[..., Any]
    notify_task_retried: Callable[..., Any]


async def _raise_if_usage_limited(
    db: AsyncSession,
    current_user: User | None,
    services: TaskCreationServices,
) -> None:
    if current_user is None or current_user.id is None:
        return
    try:
        await services.get_usage_quota_service().raise_if_over_limit(
            db,
            current_user.id,
            scope="create",
        )
    except UsageLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=usage_limit_exceeded_detail(exc),
        ) from exc


async def retry_task_record(
    *,
    task_id: int,
    request: RetryTaskRequest | None,
    db: AsyncSession,
    current_user: User | None,
    access_scope: ProjectAccessScope,
    services: TaskCreationServices,
) -> dict:
    original_task = await services.get_task_with_access_check(
        task_id,
        db,
        access_scope,
        current_user,
    )
    services.validate_task_status_for_retry(original_task)
    require_task_execution_writer(original_task, action="retry")

    existing_retry = (
        await db.execute(
            select(Task).where(
                Task.retry_source_task_id == task_id,
                Task.status.in_(["pending", "queued", "running"]),
            )
        )
    ).scalar_one_or_none()
    if existing_retry:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An active retry task (#{existing_retry.id}) already exists for task #{task_id}",
        )

    scheduled_at: datetime | None = None
    if request and request.scheduled_datetime is not None:
        scheduled_at = services.validate_scheduled_datetime_in_future(request.scheduled_datetime)

    await _raise_if_usage_limited(db, current_user, services)

    issue = (
        await db.execute(select(Issue).where(Issue.id == original_task.issue_id).with_for_update())
    ).scalar_one_or_none()
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status == "closed":
        raise HTTPException(status_code=400, detail="Cannot retry tasks on a closed issue")

    source_snapshot = original_task.worker_profile_snapshot
    if source_snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Retry source has no immutable Worker snapshot",
        )
    # The provider snapshot is deferred because it may contain encrypted runtime
    # configuration. Load it explicitly before copying execution truth; implicit
    # async lazy loading here would raise MissingGreenlet.
    await db.refresh(original_task, attribute_names=["provider_runtime_snapshot"])

    # Runtime readiness gate (§12): a retry reuses the source snapshot's frozen
    # Kit locator; refuse to create a retry when that runtime is known
    # unavailable.
    source_fingerprint = getattr(source_snapshot, "runtime_locator_fingerprint", None)
    if source_fingerprint:
        readiness = await read_runtime_readiness(db, source_fingerprint)
        if readiness.is_unavailable:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=runtime_unavailable_http_detail(readiness),
            )

    original_session_mode = getattr(original_task, "session_mode", "continue")
    original_output_session_id = getattr(original_task, "output_session_id", None)
    retry_session_mode = (
        "fresh"
        if original_session_mode == "fresh"
        and not (isinstance(original_output_session_id, str) and original_output_session_id.strip())
        else "continue"
    )

    # Issue input-stream ordering: repair legacy NULL rows and read the tail
    # projection while holding the Issue lock before allocating the tail turn.
    try:
        integrity_report = await ensure_issue_order_integrity_locked(
            db,
            issue_id=issue.id,
            repair_nulls=True,
        )
    except IssueOrderIntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail) from exc

    tail_projection = integrity_report["tail_projection"]
    source_projection = {
        "harness_key": getattr(original_task, "projected_harness_key", None),
        "session_namespace": getattr(original_task, "projected_session_namespace", None),
        "generation": getattr(original_task, "projected_lineage_generation", None),
        "reset_task_id": getattr(original_task, "projected_reset_task_id", None),
    }
    if not source_projection["harness_key"] or not source_projection["session_namespace"]:
        source_harness = getattr(source_snapshot, "harness_key", None) or "legacy"
        endpoint = getattr(source_snapshot, "model_endpoint_snapshot", None) or {}
        fingerprint = endpoint.get("fingerprint") if isinstance(endpoint, dict) else None
        source_projection = {
            "harness_key": source_harness,
            "session_namespace": session_namespace_for(source_harness, fingerprint),
            "generation": None,
            "reset_task_id": None,
        }

    retry_is_fresh = retry_session_mode == "fresh" or bool(
        request and request.lineage_strategy == "fresh_retry"
    )
    if retry_is_fresh:
        projection = project_tail_lineage(
            tail_projection,
            issue_id=issue.id,
            harness_key=source_projection["harness_key"],
            session_namespace=source_projection["session_namespace"],
            session_mode="fresh",
        )
    else:
        # A default `continue` retry is only allowed when the source projection
        # matches the current tail projection on the FULL lineage tuple
        # (harness_key, session_namespace, generation, reset_task_id) — spec
        # §4.6. Otherwise the source belongs to an older lineage and the user
        # must explicitly choose fresh_retry; silently re-binding the source to
        # the current generation would rewrite session history.
        source_tuple = (
            source_projection["harness_key"],
            source_projection["session_namespace"],
            source_projection["generation"],
            source_projection["reset_task_id"],
        )
        tail_tuple = (
            tail_projection["harness_key"] if tail_projection is not None else None,
            tail_projection["session_namespace"] if tail_projection is not None else None,
            tail_projection["generation"] if tail_projection is not None else None,
            tail_projection["reset_task_id"] if tail_projection is not None else None,
        )
        if tail_projection is None or source_tuple != tail_tuple:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "retry_lineage_conflict",
                    "message": "Retry source belongs to an older session lineage",
                    "issue_id": issue.id,
                    "task_id": task_id,
                    "source_lineage": {
                        "harness_key": source_projection["harness_key"],
                        "session_namespace": source_projection["session_namespace"],
                        "generation": source_projection["generation"],
                        "reset_task_id": source_projection["reset_task_id"],
                    },
                    "tail_lineage": tail_projection,
                    "allowed_actions": ["fresh_retry"],
                },
            ) from None
        projection = project_tail_lineage(
            tail_projection,
            issue_id=issue.id,
            harness_key=source_projection["harness_key"],
            session_namespace=source_projection["session_namespace"],
            session_mode="continue",
        )

    if scheduled_at is not None:
        try:
            await validate_schedule_time_locked(
                db,
                issue_id=issue.id,
                scheduled_at=scheduled_at,
            )
        except ScheduleWindowConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=exc.detail,
            ) from exc
        except IssueOrderIntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=exc.detail,
            ) from exc

        # Slot capacity is checked only after the Issue row lock and window
        # validation (spec §5.4 / §6.3) so create and retry share one lock order
        # and cannot deadlock against a concurrent reschedule.
        from app.core.slot_capacity import check_slot_capacity, slot_full_detail_dict

        slot_info = await check_slot_capacity(
            db,
            scheduled_at,
            exclude_task_id=task_id,
            acquire_lock=True,
        )
        if slot_info.is_full and slot_info.enforce:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=slot_full_detail_dict(slot_info),
            )

    # Defensive re-assertion of the freeform three-value invariant: a retry of a
    # freeform source must never propagate require_changes=True or a non-canonical
    # template, even if the source row drifted. execute/plan retry semantics are
    # unchanged.
    retry_task_mode = original_task.task_mode if original_task.task_mode else "execute"
    retry_require_changes = original_task.require_changes
    retry_run_instruction_template = original_task.run_instruction_template
    if retry_task_mode == "freeform":
        retry_require_changes = False
        retry_run_instruction_template = FREEFORM_RUN_INSTRUCTION_TEMPLATE

    new_task = Task(
        issue_id=original_task.issue_id,
        project_id=original_task.project_id,
        user_prompt=original_task.user_prompt,
        priority=original_task.priority,
        scheduled_at=scheduled_at,
        is_retry=True,
        retry_source_task_id=original_task.id,
        trigger_source="retry",
        ci_failure_run_id=original_task.ci_failure_run_id,
        provider_id=original_task.provider_id,
        worker_profile_id=source_snapshot.worker_profile_id,
        provider_runtime_snapshot=deepcopy(original_task.provider_runtime_snapshot),
        initiator_user_id=current_user.id if current_user is not None else None,
        initiator_gitlab_user_id=(
            current_user.gitlab_user_id if current_user is not None else None
        ),
        initiator_username=current_user.username if current_user is not None else None,
        initiator_display_name=(current_user.display_name if current_user is not None else None),
        initiator_email=current_user.email if current_user is not None else None,
        task_mode=retry_task_mode,
        require_changes=retry_require_changes,
        # Continue a session established by the source run. If a fresh run failed before it
        # produced a session, preserve fresh mode so the retry cannot fall back to the old one.
        session_mode=retry_session_mode,
        run_instruction_template=retry_run_instruction_template,
        rendered_prompt=original_task.rendered_prompt,
        rendered_prompt_at=original_task.rendered_prompt_at,
        issue_sequence=integrity_report["max_sequence"] + 1,
        projected_harness_key=projection["harness_key"],
        projected_session_namespace=projection["session_namespace"],
        projected_lineage_generation=projection["generation"],
        projected_reset_task_id=projection["reset_task_id"],
        lineage_projection_reason=projection["reason"],
    )
    issue.workspace_last_used_at = utcnow()
    issue.workspace_delete_attempted_at = None
    issue.workspace_deleted_at = None
    issue.workspace_delete_error = None
    db.add(new_task)
    await db.flush()
    if retry_is_fresh and projection["reset_task_id"] is None:
        new_task.projected_reset_task_id = new_task.id
    try:
        snapshot = await services.clone_task_worker_snapshot(
            db,
            source=source_snapshot,
            target_task=new_task,
        )
        if not isinstance(new_task.rendered_prompt, str) or not new_task.rendered_prompt.strip():
            raise TaskPromptValidationError("Retry source has no persisted rendered prompt")
        await services.bind_runtime_bundle(db, new_task, source_task=original_task)
    except (TaskPromptValidationError, SkillValidationError, RuntimeError) as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    await db.commit()
    await refresh_task_response_state(db, new_task, snapshot)
    attach_task_worker_snapshot(new_task, snapshot)
    new_task.issue = issue
    await services.notify_task_retried(new_task, None, scheduled_at)
    action = f"scheduled for retry at {scheduled_at}" if scheduled_at else "created as retry"
    logger.info("Task %s %s (retry of task %s)", new_task.id, action, task_id)
    response = serialize_task(
        new_task,
        await services.get_project_metadata(new_task.project_id),
        include_prompt_details=True,
    )
    queue_contexts = await compute_task_queue_contexts(db, [new_task])
    apply_queue_context(response, new_task.id, queue_contexts, current_user=current_user)
    return response


async def create_task_record(
    *,
    request: CreateTaskRequest,
    db: AsyncSession,
    current_user: User | None,
    access_scope: ProjectAccessScope,
    services: TaskCreationServices,
) -> dict:
    issue = await db.get(Issue, request.issue_id, with_for_update=True)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status == "closed":
        raise HTTPException(status_code=400, detail="Cannot create tasks on a closed issue")

    services.require_issue_operator(issue, current_user)
    require_project_access(issue.project_id, access_scope)
    # Issue input-stream ordering: repair legacy-NULL sequences inside the row
    # lock before allocating the tail sequence; an unrecoverable issue fails
    # closed instead of appending out of order.
    try:
        integrity_report = await ensure_issue_order_integrity_locked(
            db,
            issue_id=issue.id,
            repair_nulls=True,
        )
    except IssueOrderIntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail) from exc
    prompt = request.user_prompt or issue.description
    if not prompt:
        raise HTTPException(
            status_code=400,
            detail="No prompt provided and issue has no description",
        )

    try:
        worker_profile = await services.resolve_worker_profile_for_issue(
            db,
            issue,
        )
        provider = await services.resolve_provider_for_issue(
            db,
            issue,
            request.provider_id,
        )
    except WorkerProfileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    # Resolve + validate the harness choice (Issue default, then Profile default
    # when omitted) and freeze a secret-free ModelEndpoint into the snapshot.
    issue_default_key = getattr(issue, "default_harness_key", None)
    if not isinstance(issue_default_key, str) or not issue_default_key:
        issue_default_key = None
    profile_default_key = getattr(worker_profile, "default_harness_key", None)
    if not isinstance(profile_default_key, str) or not profile_default_key:
        profile_default_key = "claude"
    harness_key = request.harness_key or issue_default_key or profile_default_key
    if request.session_mode == "continue":
        # A continue task must match the issue's current harness lineage;
        # switching harness is only allowed on a fresh session. The resolved
        # harness_key covers both an explicit request.harness_key and the
        # profile default, so an API-direct continue that omits harness_key can
        # no longer silently cross the lineage boundary.
        current_harness = await get_issue_latest_harness_key(db, issue.id)
        if current_harness is not None:
            if harness_key != current_harness:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="续跑会话必须沿用原 Harness；切换 Harness 请勾选“使用新会话执行”",
                )
            harness_key = current_harness
    enabled_harnesses = getattr(worker_profile, "enabled_harnesses", None)
    if not isinstance(enabled_harnesses, list) or not enabled_harnesses:
        enabled_harnesses = ["claude"]
    try:
        validate_enabled_harnesses(enabled_harnesses, default_harness_key=harness_key)
        endpoint = normalize_endpoint(provider)
        ensure_harness_protocol_compatibility(harness_key, endpoint)
        if endpoint.compat_profile is not None and endpoint.compat_profile not in COMPAT_PROFILES:
            raise HarnessRegistryError(f"unknown compat_profile: {endpoint.compat_profile!r}")
    except (HarnessRegistryError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    # Runtime readiness gate (§12): refuse to create a Task for a Kit locator
    # that is known unavailable. Unknown/expired readiness never blocks. The
    # shared baseline is loaded once under lock and handed to both the gate and
    # the frozen snapshot below so a concurrent shared PATCH cannot interleave
    # between the two reads (§11.2).
    shared = await load_shared_configuration(db, for_update=True)
    readiness = await readiness_for_profile(
        db,
        worker_profile,
        get_effective_settings(),
        shared=shared,
    )
    if readiness.is_unavailable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=runtime_unavailable_http_detail(readiness),
        )

    scheduled_at = resolve_scheduled_at(
        request.scheduled_datetime,
        request.delay_seconds,
    )
    await _raise_if_usage_limited(db, current_user, services)

    # Freeze the projected session namespace from the harness/endpoint material
    # that will land in the Task snapshot; it must not be recomputed at runtime
    # from a newer Provider configuration.
    projected_namespace = session_namespace_for(harness_key, endpoint.fingerprint)

    slot_warning = None
    if scheduled_at is not None:
        # A scheduled append must satisfy the Issue queue floor (max scheduled_at
        # of active predecessors) before consuming a slot.
        try:
            await validate_schedule_time_locked(
                db,
                issue_id=issue.id,
                scheduled_at=scheduled_at,
            )
        except ScheduleWindowConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=exc.detail,
            ) from exc

        from app.core.slot_capacity import check_slot_capacity, slot_full_detail_dict

        slot_info = await check_slot_capacity(db, scheduled_at, acquire_lock=True)
        if slot_info.is_full:
            if slot_info.enforce:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=slot_full_detail_dict(slot_info),
                )
            slot_warning = slot_full_detail_dict(slot_info)

    try:
        projection = project_tail_lineage(
            integrity_report["tail_projection"],
            issue_id=issue.id,
            harness_key=harness_key,
            session_namespace=projected_namespace,
            session_mode=request.session_mode,
        )
    except LineageConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail,
        ) from exc
    task = Task(
        issue_id=issue.id,
        project_id=issue.project_id,
        user_prompt=prompt,
        initiator_user_id=current_user.id if current_user is not None else None,
        initiator_gitlab_user_id=(
            current_user.gitlab_user_id if current_user is not None else None
        ),
        initiator_username=current_user.username if current_user is not None else None,
        initiator_display_name=(current_user.display_name if current_user is not None else None),
        initiator_email=current_user.email if current_user is not None else None,
        priority=request.priority,
        scheduled_at=scheduled_at,
        provider_id=provider.id,
        worker_profile_id=worker_profile.id,
        task_mode=request.task_mode,
        require_changes=request.effective_require_changes,
        session_mode=request.session_mode,
        issue_sequence=integrity_report["max_sequence"] + 1,
        projected_harness_key=projection["harness_key"],
        projected_session_namespace=projection["session_namespace"],
        projected_lineage_generation=projection["generation"],
        projected_reset_task_id=projection["reset_task_id"],
        lineage_projection_reason=projection["reason"],
    )
    issue.workspace_last_used_at = utcnow()
    issue.workspace_delete_attempted_at = None
    issue.workspace_deleted_at = None
    issue.workspace_delete_error = None
    db.add(task)
    await db.flush()
    if request.session_mode == "fresh" and projection["reset_task_id"] is None:
        # A fresh generation is its own reset point; the id only exists after flush.
        task.projected_reset_task_id = task.id
    try:
        snapshot = await services.prepare_task_runtime_snapshot(
            db,
            task,
            issue,
            worker_profile,
            await services.get_project_metadata(issue.project_id),
            run_instruction_template=request.run_instruction_template,
            replace_snapshot=services.replace_task_worker_snapshot,
            select_template=services.select_snapshot_run_instruction_template,
            render_prompt=services.render_and_store_task_prompt,
            skill_ids=request.skill_ids,
            skill_ids_provided=(
                "skill_ids" in request.model_fields_set and request.skill_ids is not None
            ),
            harness_key=harness_key,
            endpoint=endpoint,
            shared_configuration=shared,
        )
        bundle = await services.bind_runtime_bundle(db, task, harness_key=harness_key)
        # Execution policy: under v2_only, refuse to create a Task whose bound
        # bundle pins a legacy V1 contract (reject up front instead of letting
        # recovery terminalize it later).
        require_creatable_bundle_v2(
            bundle,
            get_effective_settings().harness_execution_mode,
            subject=f"task for issue {issue.id}",
        )
        # Freeze the immutable Adapter + Bundle facts into the snapshot so the
        # execution truth is self-contained and immune to later edits. Guards
        # keep mocked/partial bundles or snapshots from breaking creation.
        if snapshot is not None:
            bundle_manifest = getattr(bundle, "manifest", None)
            adapter = {}
            if isinstance(bundle_manifest, dict):
                adapter = (bundle_manifest.get("adapters") or {}).get(harness_key) or {}
            if isinstance(adapter, dict):
                # V2 preserves adapter identity under ``adapter`` while V1
                # exposes it at the adapter root.  Freeze the actual V2 facts,
                # never a missing top-level compatibility projection.
                adapter_identity = adapter.get("adapter")
                if not isinstance(adapter_identity, dict):
                    adapter_identity = adapter
                snapshot.harness_adapter_version = adapter_identity.get("version")
                snapshot.harness_adapter_digest = adapter_identity.get("digest")
            bundle_digest = getattr(bundle, "digest", None)
            if isinstance(bundle_digest, str):
                snapshot.runtime_bundle_digest = bundle_digest
            contract_version = getattr(bundle, "contract_version", None)
            if isinstance(contract_version, str):
                snapshot.runtime_contract_version = contract_version
            orchestration_version = getattr(bundle, "orchestration_version", None)
            if isinstance(orchestration_version, str):
                snapshot.orchestration_version = orchestration_version
            cli_runtime = getattr(worker_profile, "harness_runtimes", None) or {}
            if not isinstance(cli_runtime, dict):
                cli_runtime = {}
            cli_runtime = cli_runtime.get(harness_key)
            if isinstance(cli_runtime, dict):
                snapshot.cli_source = cli_runtime.get("source")
                snapshot.cli_executable_path = cli_runtime.get("executable_path")
                snapshot.cli_version = cli_runtime.get("version")
                snapshot.cli_binary_digest = cli_runtime.get("binary_digest")
            # The snapshot helper normally attaches this relationship, but
            # keep the writer boundary explicit for alternate/test services.
            task.worker_profile_snapshot = snapshot

        # Creation is an execution writer too.  Validate the complete frozen
        # Task/Snapshot/Bundle identity after all facts are populated and
        # before the first commit, rather than deferring an invalid row to the
        # Scheduler claim path.
        require_task_executable_contract(
            task,
            bundle,
            get_effective_settings().harness_execution_mode,
        )
    except (TaskPromptValidationError, SkillValidationError, RuntimeError) as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except ExecutionPolicyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": exc.code,
                "message": str(exc),
            },
        ) from exc

    await db.commit()
    await refresh_task_response_state(db, task, snapshot)
    attach_task_worker_snapshot(task, snapshot)
    task.issue = issue
    logger.info(
        "Created task %s for issue %s (project %s), priority=%s, delay=%s",
        task.id,
        issue.id,
        issue.project_id,
        request.priority,
        request.delay_seconds,
    )

    response = serialize_task(
        task,
        await services.get_project_metadata(issue.project_id),
        include_prompt_details=True,
    )
    if slot_warning:
        response["slot_warning"] = slot_warning
    queue_contexts = await compute_task_queue_contexts(db, [task])
    apply_queue_context(response, task.id, queue_contexts, current_user=current_user)
    return response
