"""Tests for task run-instruction rendering and active-task backfill."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.task_prompt import (
    BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE,
    BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE,
    BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE,
    MAX_RENDERED_PROMPT_LENGTH,
    MAX_RUN_INSTRUCTION_TEMPLATE_LENGTH,
    TaskPromptValidationError,
    backfill_active_task_prompts,
    extract_placeholders,
    render_run_instruction_template,
    select_run_instruction_template,
    validate_run_instruction_template,
)
from app.core.worker_runtime import materialize_task_prompt
from app.models import Base, Issue, Task, TaskStatus


def test_extracts_and_renders_placeholders_exactly() -> None:
    template = "A {{ user_prompt }} B {{project_path}} C {{user_prompt}}"
    assert extract_placeholders(template) == ("user_prompt", "project_path")
    result = render_run_instruction_template(
        template,
        {"user_prompt": "need", "project_path": "group/repo"},
    )
    assert result.rendered_prompt == "A need B group/repo C need"
    assert result.used_placeholders == ("user_prompt", "project_path")


@pytest.mark.parametrize("template", ["literal only", "No requirement {{project_path}}"])
def test_templates_without_user_prompt_are_valid(template: str) -> None:
    assert render_run_instruction_template(template, {}).rendered_prompt.startswith(
        template.split("{{", 1)[0]
    )


def test_normalizes_line_endings_and_leaves_malformed_text_literal() -> None:
    result = render_run_instruction_template("A\r\n{{user_prompt}\rB {{9bad}}", {})
    assert result.rendered_prompt == "A\n{{user_prompt}\nB {{9bad}}"


@pytest.mark.parametrize(
    ("template", "message"),
    [
        ("{{unknown}}", "unknown placeholder"),
        (" \n\t", "cannot be blank"),
        ("{{user_prompt}}", "rendered prompt cannot be blank"),
    ],
)
def test_rejects_invalid_templates_or_rendered_results(template: str, message: str) -> None:
    with pytest.raises(TaskPromptValidationError, match=message):
        render_run_instruction_template(template, {"user_prompt": ""})


def test_enforces_template_and_rendered_boundaries() -> None:
    assert len(validate_run_instruction_template("x" * MAX_RUN_INSTRUCTION_TEMPLATE_LENGTH)) == 50_000
    with pytest.raises(TaskPromptValidationError, match="50000"):
        validate_run_instruction_template("x" * (MAX_RUN_INSTRUCTION_TEMPLATE_LENGTH + 1))
    result = render_run_instruction_template("{{user_prompt}}", {"user_prompt": "x" * MAX_RENDERED_PROMPT_LENGTH})
    assert len(result.rendered_prompt) == 100_000
    with pytest.raises(TaskPromptValidationError, match="100000"):
        render_run_instruction_template(
            "{{user_prompt}}",
            {"user_prompt": "x" * (MAX_RENDERED_PROMPT_LENGTH + 1)},
        )


def test_template_selection_precedence() -> None:
    settings = SimpleNamespace(
        default_execute_run_instruction_template="execute",
        default_plan_run_instruction_template="plan",
        ci_auto_repair_run_instruction_template="ci",
    )
    assert select_run_instruction_template(settings, task_mode="execute") == "execute"
    assert select_run_instruction_template(settings, task_mode="plan") == "plan"
    assert (
        select_run_instruction_template(
            settings, task_mode="plan", trigger_source="ci_auto_repair"
        )
        == "ci"
    )
    assert (
        select_run_instruction_template(
            settings,
            task_mode="plan",
            trigger_source="ci_auto_repair",
            retry_snapshot="snapshot",
        )
        == "snapshot"
    )


@pytest.mark.asyncio
async def test_backfills_only_active_tasks_atomically() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = SimpleNamespace(
        default_execute_run_instruction_template=BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE,
        default_plan_run_instruction_template=BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE,
        ci_auto_repair_run_instruction_template=BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE,
    )
    async with factory() as db:
        issue = Issue(id=1, title="Issue", project_id=9, status="open", branch_name="work")
        db.add(issue)
        db.add_all(
            [
                Task(id=1, issue_id=1, project_id=9, user_prompt="execute", status=TaskStatus.PENDING),
                Task(
                    id=2,
                    issue_id=1,
                    project_id=9,
                    user_prompt="plan",
                    status=TaskStatus.QUEUED,
                    task_mode="plan",
                ),
                Task(
                    id=3,
                    issue_id=1,
                    project_id=9,
                    user_prompt="done",
                    status=TaskStatus.COMPLETED,
                ),
            ]
        )
        await db.commit()
        with patch(
            "app.core.projects.build_project_lookup",
            new=AsyncMock(return_value={9: {"project_path_with_namespace": "group/repo"}}),
        ):
            assert await backfill_active_task_prompts(db, settings) == 2
        active_execute = await db.get(Task, 1)
        active_plan = await db.get(Task, 2)
        terminal = await db.get(Task, 3)
        assert active_execute.run_instruction_template == BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE
        assert active_plan.run_instruction_template == BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE
        assert active_execute.rendered_prompt_at is not None
        assert terminal.run_instruction_template is None
        assert terminal.rendered_prompt is None
    await engine.dispose()


def test_materializes_persisted_prompt_exactly(tmp_path) -> None:
    task = Task(id=7, issue_id=1, project_id=9, user_prompt="metadata")
    task.rendered_prompt = "line one\nline two"
    prompt_path = materialize_task_prompt(task, tmp_path / "runtime")
    assert prompt_path.read_bytes() == b"line one\nline two"


def test_materialization_rejects_missing_prompt_before_writing(tmp_path) -> None:
    task = Task(id=7, issue_id=1, project_id=9, user_prompt="metadata")
    task.rendered_prompt = "  \n"
    with pytest.raises(RuntimeError, match="no persisted rendered prompt"):
        materialize_task_prompt(task, tmp_path / "runtime")
    assert not (tmp_path / "runtime").exists()
