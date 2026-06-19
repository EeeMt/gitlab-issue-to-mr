"""Task run-instruction template selection, validation, rendering, and persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.utcnow import utcnow
from app.models import Task, TaskStatus

MAX_RUN_INSTRUCTION_TEMPLATE_LENGTH = 50_000
MAX_RENDERED_PROMPT_LENGTH = 100_000
CI_FAILURE_CONTEXT_PATH = "/tmp/codify-runtime/ci-failure"
PREVIOUS_TASK_SUMMARIES_PATH = "/tmp/codify-runtime/previous-task-summaries.md"

BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE = """请直接完成下面的需求，不要先输出规划或步骤清单。

需求:
{{user_prompt}}

上下文:
- 仓库路径: {{project_path}}

要求:
1. 直接检查代码库并实施修改。
2. 仅在当前仓库内工作，优先做精确修改，不要引入无关改动。
3. 完成后运行相关验证命令；如果仓库里没有对应命令，就明确说明。
4. 最终输出简短执行摘要，至少包含：
    - 做了什么，为什么这么做
    - 运行了哪些验证
5. 如果执行摘要需要表达流程、架构、时序、状态转换等图表，必须使用 Markdown 的 mermaid fenced code block（语言标记为 mermaid），不要使用 ASCII 图、图片链接或其它图表格式。
6. 不要描述\"未跟踪文件\"\"待提交\"\"可按需提交\"这类提交前状态，默认以已经完成并准备提交的口吻总结结果。
7. 不要要求人工确认，除非你真的被阻塞。
"""

BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE = """请分析下面的需求，给出详细的实施方案。不要修改任何文件，不要执行任何写操作（包括 git commit、git push、创建 MR）。

需求:
{{user_prompt}}

上下文:
- 仓库路径: {{project_path}}

要求:
1. 检查代码库，理解现有结构和约束。
2. 给出清晰、可操作的实施方案，包含：
    - 需要新增或修改哪些文件，以及具体的改动思路
    - 为什么这么设计
    - 潜在风险或需要注意的地方
3. 不要修改任何文件，不要执行任何写操作。
4. 如果方案需要表达流程、架构、时序、状态转换等图表，必须使用 Markdown 的 mermaid fenced code block（语言标记为 mermaid），不要使用 ASCII 图、图片链接或其它图表格式。
5. 不要要求人工确认。
"""

BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE = """请直接修复「{{issue_title}}」当前 MR 的 GitLab CI 失败，不要先输出规划或步骤清单。

上下文:
- 仓库路径: {{project_path}}
- CI 失败上下文目录: {{ci_failure_context_path}}
- Pipeline: {{ci_failure_context_path}}/pipeline.json
- 失败 Jobs: {{ci_failure_context_path}}/failed-jobs.json
- Job 日志目录: {{ci_failure_context_path}}/jobs/

要求:
1. 先读取 pipeline、失败 job 元数据和根因 job 日志，再修改代码。
2. 只修复当前 CI 失败，不要扩大原始需求范围，不要修改无关文件。
3. 仅在当前仓库内工作，优先做精确修改，不要引入无关改动。
4. 完成后运行与失败项直接相关的验证；如果仓库里没有对应命令，就明确说明。
5. 不要执行 git commit 或 git push，提交和推送由 worker 收尾流程处理。
6. 最终输出简短执行摘要，至少包含：
    - 修复了什么，为什么这么修复
    - 运行了哪些验证
7. 如果执行摘要需要表达流程、架构、时序、状态转换等图表，必须使用 Markdown 的 mermaid fenced code block（语言标记为 mermaid），不要使用 ASCII 图、图片链接或其它图表格式。
8. 不要描述\"未跟踪文件\"\"待提交\"\"可按需提交\"这类提交前状态，默认以已经完成并准备提交的口吻总结结果。
9. 不要要求人工确认，除非你真的被阻塞。
"""

PLACEHOLDER_NAMES = (
    "user_prompt",
    "issue_title",
    "project_path",
    "branch_name",
    "base_branch",
    "target_branch",
    "task_mode",
    "require_changes",
    "previous_task_summaries_path",
    "ci_failure_context_path",
)
NORMAL_PLACEHOLDER_NAMES = PLACEHOLDER_NAMES[:-1]
CI_PLACEHOLDER_NAMES = tuple(name for name in PLACEHOLDER_NAMES if name != "user_prompt")

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class TaskPromptValidationError(ValueError):
    """Raised when a run-instruction template or rendered prompt is invalid."""


@dataclass(frozen=True)
class TaskPromptRenderResult:
    rendered_prompt: str
    used_placeholders: tuple[str, ...]
    unused_known_placeholders: tuple[str, ...]


def normalize_prompt_text(value: str) -> str:
    """Normalize all supported line endings without otherwise changing content."""
    return value.replace("\r\n", "\n").replace("\r", "\n")


def extract_placeholders(template: str) -> tuple[str, ...]:
    """Return placeholder names once each, preserving their first appearance order."""
    seen: set[str] = set()
    names: list[str] = []
    for match in _PLACEHOLDER_RE.finditer(template):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            names.append(name)
    return tuple(names)


def validate_run_instruction_template(template: str) -> str:
    """Normalize and validate a submitted run-instruction template."""
    if not isinstance(template, str):
        raise TaskPromptValidationError("run instruction template must be a string")
    normalized = normalize_prompt_text(template)
    if len(normalized) > MAX_RUN_INSTRUCTION_TEMPLATE_LENGTH:
        raise TaskPromptValidationError(
            f"run instruction template must be {MAX_RUN_INSTRUCTION_TEMPLATE_LENGTH} characters or fewer"
        )
    if not normalized.strip():
        raise TaskPromptValidationError("run instruction template cannot be blank")
    unknown = [name for name in extract_placeholders(normalized) if name not in PLACEHOLDER_NAMES]
    if unknown:
        raise TaskPromptValidationError(f"unknown placeholder(s): {', '.join(unknown)}")
    return normalized


def render_run_instruction_template(
    template: str,
    context: Mapping[str, Any],
    *,
    available_placeholders: Sequence[str] = PLACEHOLDER_NAMES,
) -> TaskPromptRenderResult:
    """Render a validated template with plain allowlisted string replacement."""
    normalized = validate_run_instruction_template(template)
    used = extract_placeholders(normalized)

    def replace(match: re.Match[str]) -> str:
        value = context.get(match.group(1), "")
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    rendered = _PLACEHOLDER_RE.sub(replace, normalized)
    rendered = normalize_prompt_text(rendered)
    if len(rendered) > MAX_RENDERED_PROMPT_LENGTH:
        raise TaskPromptValidationError(
            f"rendered prompt must be {MAX_RENDERED_PROMPT_LENGTH} characters or fewer"
        )
    if not rendered.strip():
        raise TaskPromptValidationError("rendered prompt cannot be blank")
    return TaskPromptRenderResult(
        rendered_prompt=rendered,
        used_placeholders=used,
        unused_known_placeholders=tuple(name for name in available_placeholders if name not in used),
    )


def select_run_instruction_template(
    settings: Any,
    *,
    task_mode: str,
    trigger_source: str = "manual",
    retry_snapshot: str | None = None,
) -> str:
    """Select a template snapshot using retry, trigger source, then task mode precedence."""
    if retry_snapshot is not None:
        return validate_run_instruction_template(retry_snapshot)
    if trigger_source == "ci_auto_repair":
        return validate_run_instruction_template(settings.ci_auto_repair_run_instruction_template)
    if task_mode == "plan":
        return validate_run_instruction_template(settings.default_plan_run_instruction_template)
    return validate_run_instruction_template(settings.default_execute_run_instruction_template)


def build_task_prompt_context(
    task: Task,
    issue: Any | None,
    project_metadata: Mapping[str, Any] | None = None,
    *,
    previous_task_summaries_path: str | None = None,
) -> dict[str, str]:
    """Build the canonical string context for one persisted or prospective task."""
    metadata = project_metadata or {}
    return {
        "user_prompt": task.user_prompt or "",
        "issue_title": getattr(issue, "title", "") or "",
        "project_path": metadata.get("project_path_with_namespace") or "",
        "branch_name": getattr(issue, "branch_name", "") or "",
        "base_branch": getattr(issue, "base_branch", "") or "",
        "target_branch": getattr(issue, "target_branch", "") or "",
        "task_mode": task.task_mode or "execute",
        "require_changes": "true" if bool(task.require_changes) else "false",
        "previous_task_summaries_path": (
            PREVIOUS_TASK_SUMMARIES_PATH
            if previous_task_summaries_path is None and issue is not None
            else (previous_task_summaries_path or "")
        ),
        "ci_failure_context_path": (
            CI_FAILURE_CONTEXT_PATH
            if task.trigger_source == "ci_auto_repair" or task.ci_failure_run_id is not None
            else ""
        ),
    }


def render_and_store_task_prompt(
    task: Task,
    issue: Any | None,
    project_metadata: Mapping[str, Any] | None,
    template: str,
) -> TaskPromptRenderResult:
    """Render and assign a task snapshot without committing the surrounding transaction."""
    normalized = validate_run_instruction_template(template)
    result = render_run_instruction_template(
        normalized,
        build_task_prompt_context(task, issue, project_metadata),
    )
    task.run_instruction_template = normalized
    task.rendered_prompt = result.rendered_prompt
    task.rendered_prompt_at = utcnow()
    return result


async def backfill_active_task_prompts(
    db: AsyncSession,
    settings: Any,
) -> int:
    """Atomically backfill missing prompt snapshots for pending and queued tasks."""
    from app.core.projects import build_project_lookup

    tasks = (
        await db.execute(
            select(Task)
            .options(selectinload(Task.issue))
            .where(
                Task.status.in_((TaskStatus.PENDING, TaskStatus.QUEUED)),
                (
                    Task.run_instruction_template.is_(None)
                    | Task.rendered_prompt.is_(None)
                    | Task.rendered_prompt_at.is_(None)
                ),
            )
            .order_by(Task.id)
        )
    ).scalars().all()
    if not tasks:
        return 0

    project_lookup = await build_project_lookup()
    for task in tasks:
        template = task.run_instruction_template
        if template is None:
            template = select_run_instruction_template(
                settings,
                task_mode=task.task_mode or "execute",
                trigger_source=task.trigger_source or "manual",
            )
        render_and_store_task_prompt(
            task,
            task.issue,
            project_lookup.get(task.project_id) or {},
            template,
        )
    await db.commit()
    return len(tasks)
