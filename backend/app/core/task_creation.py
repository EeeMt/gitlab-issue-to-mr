"""Shared task creation steps for manual, retry, and CI repair tasks."""

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.skills import (
    normalize_skill_snapshots,
    replace_task_skill_references,
    resolve_task_skill_snapshots,
    validate_runtime_supports_skills,
)
from app.core.task_prompt import render_and_store_task_prompt
from app.core.worker_profiles import (
    replace_task_worker_snapshot,
    select_snapshot_run_instruction_template,
)
from app.models import Issue, Task, TaskWorkerProfileSnapshot

ReplaceSnapshot = Callable[
    [AsyncSession, Task, Any],
    Awaitable[TaskWorkerProfileSnapshot],
]
SelectTemplate = Callable[..., str]
RenderPrompt = Callable[[Task, Issue, dict[str, Any], str], None]


async def prepare_task_runtime_snapshot(
    db: AsyncSession,
    task: Task,
    issue: Issue,
    worker_profile: Any,
    project_metadata: dict[str, Any],
    *,
    run_instruction_template: str | None,
    template_trigger_source: str | None = None,
    replace_snapshot: ReplaceSnapshot = replace_task_worker_snapshot,
    select_template: SelectTemplate = select_snapshot_run_instruction_template,
    render_prompt: RenderPrompt = render_and_store_task_prompt,
    skill_ids: list[int] | None = None,
    skill_ids_provided: bool = False,
    skill_snapshots: list[dict[str, Any]] | None = None,
    skill_selection_source: str | None = None,
    harness_key: str | None = None,
    endpoint: Any | None = None,
) -> TaskWorkerProfileSnapshot:
    """Snapshot the worker profile and persist the task's rendered prompt."""
    if skill_snapshots is None:
        resolved_skills = await resolve_task_skill_snapshots(
            db,
            worker_profile,
            skill_ids if skill_ids_provided else None,
        )
        resolved_source = "task" if skill_ids_provided else "profile"
    else:
        resolved_skills = normalize_skill_snapshots(skill_snapshots)
        validate_runtime_supports_skills(worker_profile, resolved_skills)
        resolved_source = skill_selection_source or "task"
    snapshot = await replace_snapshot(
        db, task, worker_profile, harness_key=harness_key, endpoint=endpoint
    )
    replace_task_skill_references(snapshot, resolved_skills)
    snapshot.skill_selection_source = resolved_source
    task.worker_profile_snapshot = snapshot
    template = run_instruction_template
    if template is None:
        template = select_template(
            snapshot,
            task_mode=task.task_mode or "execute",
            trigger_source=template_trigger_source or task.trigger_source or "manual",
        )
    render_prompt(task, issue, project_metadata, template)
    return snapshot
