#!/usr/bin/env python3
"""Unit tests for task initiator persistence and analytics API."""

import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.stats import get_analytics
from app.api.tasks import CreateTaskRequest, create_task
from app.dependencies.project_access import ProjectAccessScope
from app.models import TaskStatus


@pytest.mark.asyncio
async def test_create_task_persists_manual_initiator_metadata():
    from app.models import Issue
    request = CreateTaskRequest(
        issue_id=1,
        user_prompt="Build analytics page",
        priority=1,
    )
    mock_issue = MagicMock()
    mock_issue.id = 1
    mock_issue.project_id = 101
    mock_issue.description = "Build analytics page"
    mock_issue.status = "open"

    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.get = AsyncMock(return_value=mock_issue)

    async def refresh(task):
        task.id = 23
        task.status = TaskStatus.PENDING
        task.created_at = datetime(2026, 3, 14, 12, 0, 0)
        task.updated_at = datetime(2026, 3, 14, 12, 0, 0)

    db.refresh = AsyncMock(side_effect=refresh)
    current_user = SimpleNamespace(id=7, gitlab_user_id=77, username="alice")
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    with patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})):
        result = await create_task(request=request, db=db, current_user=current_user, access_scope=access_scope)

    task = db.add.call_args.args[0]
    assert task.initiator_user_id == 7
    assert task.initiator_gitlab_user_id == 77
    assert task.initiator_username == "alice"
    assert result["id"] == 23


class MockResult:
    """Simple mock result that behaves like SQLAlchemy execute result."""

    def __init__(self, data):
        self._data = data

    def one(self):
        return tuple(self._data)

    def all(self):
        return self._data

    def scalars(self):
        return self

    def scalar(self):
        return self._data[0] if self._data else None


@dataclass(frozen=True)
class AnalyticsSummaryRow:
    """Readable fixture for the analytics summary aggregate row."""

    total_tasks: int = 0
    total_additions: int = 0
    total_deletions: int = 0
    total_changes: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    cancelled_tasks: int = 0
    finished_tasks: int = 0
    tracked_initiator_tasks: int = 0
    token_tracked_tasks: int = 0
    initiator_tracking_started_at: datetime | None = None
    avg_execution_seconds: float | None = None
    max_execution_seconds: float | None = None
    avg_queue_wait_seconds: float | None = None
    max_queue_wait_seconds: float | None = None
    avg_total_tokens_per_tracked_task: float | None = None
    max_total_tokens_per_tracked_task: float | None = None

    def as_result_row(self) -> list[object]:
        return [
            self.total_tasks,
            self.total_additions,
            self.total_deletions,
            self.total_changes,
            self.total_input_tokens,
            self.total_output_tokens,
            self.completed_tasks,
            self.failed_tasks,
            self.cancelled_tasks,
            self.finished_tasks,
            self.tracked_initiator_tasks,
            self.token_tracked_tasks,
            self.initiator_tracking_started_at,
            self.avg_execution_seconds,
            self.max_execution_seconds,
            self.avg_queue_wait_seconds,
            self.max_queue_wait_seconds,
            self.avg_total_tokens_per_tracked_task,
            self.max_total_tokens_per_tracked_task,
        ]


class AnalyticsQueryStub:
    """Route analytics queries by intent instead of db.execute call order."""

    def __init__(self, *, summary: AnalyticsSummaryRow, provider_rows: list | None = None):
        self.summary = summary
        self.provider_rows = provider_rows or []

    def __call__(self, query):
        sql = " ".join(str(query).split())

        if self._is_summary_query(sql):
            return MockResult(self.summary.as_result_row())
        if self._is_project_query(sql):
            return MockResult([])
        if self._is_available_initiators_query(sql):
            return MockResult([])
        if self._is_initiators_query(sql):
            return MockResult([])
        if self._is_trend_query(sql):
            return MockResult([])
        if self._is_priority_wait_query(sql):
            return MockResult([])
        if self._is_issue_status_query(sql):
            return MockResult([])
        if self._is_task_status_query(sql):
            return MockResult([])
        if self._is_error_query(sql):
            return MockResult([])
        if self._is_provider_query(sql):
            return MockResult(self.provider_rows)

        raise AssertionError(f"unrecognized analytics query: {sql}")

    @staticmethod
    def _is_summary_query(sql: str) -> bool:
        return "SELECT count(tasks.id) AS count_1" in sql and "min(CASE WHEN (tasks.initiator_username IS NOT NULL)" in sql

    @staticmethod
    def _is_project_query(sql: str) -> bool:
        return "GROUP BY tasks.project_id" in sql

    @staticmethod
    def _is_available_initiators_query(sql: str) -> bool:
        return (
            "GROUP BY tasks.initiator_username, tasks.initiator_gitlab_user_id" in sql
            and "completed_tasks" not in sql
        )

    @staticmethod
    def _is_initiators_query(sql: str) -> bool:
        return (
            "GROUP BY tasks.initiator_username, tasks.initiator_gitlab_user_id" in sql
            and "completed_tasks" in sql
        )

    @staticmethod
    def _is_trend_query(sql: str) -> bool:
        return "GROUP BY date(tasks.created_at)" in sql

    @staticmethod
    def _is_priority_wait_query(sql: str) -> bool:
        return "GROUP BY tasks.priority" in sql

    @staticmethod
    def _is_issue_status_query(sql: str) -> bool:
        return "FROM issues" in sql and "GROUP BY issues.status" in sql

    @staticmethod
    def _is_task_status_query(sql: str) -> bool:
        return "FROM tasks" in sql and "GROUP BY tasks.status" in sql and "tasks.error_message" not in sql

    @staticmethod
    def _is_error_query(sql: str) -> bool:
        return "tasks.error_message" in sql and "GROUP BY tasks.error_message" in sql

    @staticmethod
    def _is_provider_query(sql: str) -> bool:
        return "provider_id" in sql and "provider_name" in sql and "provider_model" in sql


@pytest.mark.asyncio
async def test_get_analytics_returns_project_initiator_and_trend_breakdowns():
    fixed_now = datetime(2026, 3, 14, 12, 0, 0)

    # Create mock db
    db = MagicMock()

    # Track call count for side_effect
    call_count = [0]

    def execute_side_effect(query):
        call_count[0] += 1

        # Summary query (call 1)
        if call_count[0] == 1:
            return MockResult([
                4,      # total_tasks
                21,     # total_additions
                9,      # total_deletions
                30,     # total_changes
                1000,   # total_input_tokens
                2000,   # total_output_tokens
                3,      # completed_tasks
                1,      # failed_tasks
                0,      # cancelled_tasks
                4,      # finished_tasks
                2,      # tracked_initiator_tasks
                2,      # token_tracked_tasks
                datetime(2026, 3, 12, 8, 0, 0),  # initiator_tracking_started_at
                540.0,  # avg_execution_seconds
                900.0,  # max_execution_seconds
                180.0,  # avg_queue_wait_seconds
                300.0,  # max_queue_wait_seconds
                1500.0, # avg_total_tokens_per_tracked_task
                2000.0, # max_total_tokens_per_tracked_task
            ])

        # Project query (call 2)
        elif call_count[0] == 2:
            return MockResult([
                SimpleNamespace(
                    project_id=101,
                    task_count=3,
                    completed_tasks=2,
                    failed_tasks=1,
                    cancelled_tasks=0,
                    additions=16,
                    deletions=5,
                    total_changes=21,
                    input_tokens=800,
                    output_tokens=1600,
                    total_tokens=2400,
                    avg_execution_seconds=600.0,
                    avg_queue_wait_seconds=150.0,
                    last_task_at=datetime(2026, 3, 14, 9, 0, 0),
                )
            ])

        # Available initiators query (call 3)
        elif call_count[0] == 3:
            return MockResult([])

        # Initiators breakdown query (call 4)
        elif call_count[0] == 4:
            return MockResult([
                SimpleNamespace(
                    initiator_username="alice",
                    initiator_gitlab_user_id=77,
                    task_count=2,
                    completed_tasks=2,
                    failed_tasks=0,
                    cancelled_tasks=0,
                    additions=10,
                    deletions=4,
                    total_changes=14,
                    input_tokens=500,
                    output_tokens=1000,
                    total_tokens=1500,
                    avg_execution_seconds=420.0,
                    avg_queue_wait_seconds=120.0,
                    last_task_at=datetime(2026, 3, 14, 9, 0, 0),
                )
            ])

        # Trend query (call 5)
        elif call_count[0] == 5:
            return MockResult([
                SimpleNamespace(
                    day=date(2026, 3, 12),
                    task_count=1,
                    completed_tasks=1,
                    failed_tasks=0,
                    cancelled_tasks=0,
                    additions=4,
                    deletions=1,
                    total_changes=5,
                    input_tokens=100,
                    output_tokens=200,
                    total_tokens=300,
                    avg_execution_seconds=300.0,
                ),
                SimpleNamespace(
                    day=date(2026, 3, 14),
                    task_count=3,
                    completed_tasks=2,
                    failed_tasks=1,
                    cancelled_tasks=0,
                    additions=17,
                    deletions=8,
                    total_changes=25,
                    input_tokens=500,
                    output_tokens=1000,
                    total_tokens=1500,
                    avg_execution_seconds=720.0,
                ),
            ])

        # Priority wait query (call 6)
        elif call_count[0] == 6:
            return MockResult([
                SimpleNamespace(
                    priority=0,
                    task_count=2,
                    avg_queue_wait_seconds=90.0,
                    max_queue_wait_seconds=180.0,
                ),
                SimpleNamespace(
                    priority=2,
                    task_count=1,
                    avg_queue_wait_seconds=300.0,
                    max_queue_wait_seconds=300.0,
                ),
            ])

        # Issue status breakdown query (call 7)
        elif call_count[0] == 7:
            return MockResult([
                SimpleNamespace(status="open", count=3),
                SimpleNamespace(status="in_review", count=1),
            ])

        # Task status breakdown query (call 8)
        elif call_count[0] == 8:
            return MockResult([
                SimpleNamespace(status=TaskStatus.PENDING, count=2),
                SimpleNamespace(status=TaskStatus.COMPLETED, count=1),
                SimpleNamespace(status=TaskStatus.FAILED, count=1),
            ])

        # Error breakdown query (call 9)
        elif call_count[0] == 9:
            return MockResult([
                SimpleNamespace(error_message="Task timed out after 30m", count=2),
                SimpleNamespace(error_message="docker container exited unexpectedly", count=1),
            ])

        return MockResult([])

    db.execute = AsyncMock(side_effect=execute_side_effect)

    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    with patch("app.api.stats.utcnow", return_value=fixed_now), patch(
        "app.api.stats.build_project_lookup",
        new=AsyncMock(
            return_value={
                101: {
                    "project_name": "Project Alpha",
                    "project_path_with_namespace": "team/project-alpha",
                }
            }
        ),
    ):
        response = await get_analytics(days=7, project_id=None, initiator_username=None, db=db, _current_user=None, access_scope=access_scope)

    assert response["window_days"] == 7
    assert response["summary"]["total_tasks"] == 4
    assert response["summary"]["success_rate"] == pytest.approx(0.75)
    assert response["summary"]["avg_execution_seconds"] == pytest.approx(540.0)
    assert response["summary"]["avg_queue_wait_seconds"] == pytest.approx(180.0)
    assert response["summary"]["tracked_initiator_tasks"] == 2
    assert response["projects"][0]["project_name"] == "Project Alpha"
    assert response["projects"][0]["success_rate"] == pytest.approx(2 / 3)
    assert response["projects"][0]["avg_execution_seconds"] == pytest.approx(600.0)
    assert response["initiators"][0]["initiator_username"] == "alice"
    assert response["initiators"][0]["success_rate"] == pytest.approx(1.0)
    assert len(response["trends"]) == 7
    assert response["trends"][0]["date"] == "2026-03-08"
    assert response["trends"][-1]["date"] == "2026-03-14"
    assert response["trends"][-1]["task_count"] == 3
    assert response["trends"][-1]["avg_execution_seconds"] == pytest.approx(720.0)
    assert response["priority_waits"][0]["priority"] == 0
    assert response["priority_waits"][1]["avg_queue_wait_seconds"] == pytest.approx(300.0)
    assert response["issue_status_breakdown"] == [
        {"status": "open", "count": 3, "share": pytest.approx(0.75)},
        {"status": "in_progress", "count": 0, "share": pytest.approx(0.0)},
        {"status": "in_review", "count": 1, "share": pytest.approx(0.25)},
        {"status": "closed", "count": 0, "share": pytest.approx(0.0)},
    ]
    assert response["task_status_breakdown"] == [
        {"status": "pending", "count": 2, "share": pytest.approx(0.5)},
        {"status": "queued", "count": 0, "share": pytest.approx(0.0)},
        {"status": "running", "count": 0, "share": pytest.approx(0.0)},
        {"status": "completed", "count": 1, "share": pytest.approx(0.25)},
        {"status": "failed", "count": 1, "share": pytest.approx(0.25)},
        {"status": "cancelled", "count": 0, "share": pytest.approx(0.0)},
    ]
    assert response["error_breakdown"][0]["category"] == "Timeout"
    assert response["error_breakdown"][0]["count"] == 2
    assert response["error_breakdown"][1]["category"] == "Docker"


@pytest.mark.asyncio
async def test_get_analytics_returns_provider_metrics_and_unknown_legacy_bucket():
    """It returns separate provider/model rows plus an Unknown / Legacy bucket for legacy tasks."""
    fixed_now = datetime(2026, 3, 14, 12, 0, 0)
    db = MagicMock()

    db.execute = AsyncMock(
        side_effect=AnalyticsQueryStub(
            summary=AnalyticsSummaryRow(
                total_tasks=6,
                total_additions=30,
                total_deletions=10,
                total_changes=40,
                total_input_tokens=1600,
                total_output_tokens=2400,
                completed_tasks=3,
                failed_tasks=2,
                cancelled_tasks=1,
                finished_tasks=6,
                tracked_initiator_tasks=4,
                token_tracked_tasks=4,
                initiator_tracking_started_at=datetime(2026, 3, 12, 8, 0, 0),
                avg_execution_seconds=600.0,
                max_execution_seconds=900.0,
                avg_queue_wait_seconds=120.0,
                max_queue_wait_seconds=240.0,
                avg_total_tokens_per_tracked_task=1000.0,
                max_total_tokens_per_tracked_task=1400.0,
            ),
            provider_rows=[
                SimpleNamespace(
                    provider_id=1,
                    provider_name="Claude Sonnet",
                    provider_model="claude-sonnet-4-6",
                    task_count=2,
                    completed_tasks=2,
                    failed_tasks=0,
                    cancelled_tasks=0,
                    finished_tasks=2,
                    total_input_tokens=400,
                    total_output_tokens=600,
                    total_tokens=1000,
                    avg_tokens_per_task=500.0,
                    avg_tokens_per_second=4.0,
                    avg_tokens_per_changed_line=12.0,
                    avg_execution_seconds=300.0,
                    avg_execution_seconds_per_changed_line=3.0,
                ),
                SimpleNamespace(
                    provider_id=1,
                    provider_name="Claude Sonnet",
                    provider_model="claude-3-5-sonnet",
                    task_count=1,
                    completed_tasks=0,
                    failed_tasks=1,
                    cancelled_tasks=0,
                    finished_tasks=1,
                    total_input_tokens=200,
                    total_output_tokens=300,
                    total_tokens=500,
                    avg_tokens_per_task=500.0,
                    avg_tokens_per_second=2.0,
                    avg_tokens_per_changed_line=10.0,
                    avg_execution_seconds=250.0,
                    avg_execution_seconds_per_changed_line=5.0,
                ),
                SimpleNamespace(
                    provider_id=None,
                    provider_name=None,
                    provider_model=None,
                    task_count=2,
                    completed_tasks=1,
                    failed_tasks=0,
                    cancelled_tasks=1,
                    finished_tasks=2,
                    total_input_tokens=200,
                    total_output_tokens=300,
                    total_tokens=500,
                    avg_tokens_per_task=250.0,
                    avg_tokens_per_second=None,
                    avg_tokens_per_changed_line=None,
                    avg_execution_seconds=450.0,
                    avg_execution_seconds_per_changed_line=None,
                ),
            ],
        )
    )
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    with patch("app.api.stats.utcnow", return_value=fixed_now), patch(
        "app.api.stats.build_project_lookup", new=AsyncMock(return_value={})
    ):
        response = await get_analytics(
            days=7,
            project_id=None,
            initiator_username=None,
            db=db,
            _current_user=None,
            access_scope=access_scope,
        )

    assert response["provider_summary"]["active_provider_count"] == 3
    assert response["provider_summary"]["provider_covered_task_count"] == 5
    assert response["provider_summary"]["provider_covered_total_tokens"] == 2000
    assert response["provider_summary"]["provider_success_rate"] == pytest.approx(3 / 5)

    provider_rows = {
        (row["provider_name"], row["provider_model"]): row for row in response["providers"]
    }

    claude_sonnet_46 = provider_rows[("Claude Sonnet", "claude-sonnet-4-6")]
    assert claude_sonnet_46["avg_tokens_per_second"] == pytest.approx(4.0)

    unknown_legacy = provider_rows[("Unknown / Legacy", None)]
    assert unknown_legacy["avg_tokens_per_second"] is None
    assert unknown_legacy["avg_tokens_per_changed_line"] is None
    assert unknown_legacy["avg_execution_seconds_per_changed_line"] is None

    claude_sonnet_35 = provider_rows[("Claude Sonnet", "claude-3-5-sonnet")]
    assert claude_sonnet_35["success_rate"] == pytest.approx(0.0)

    assert response["provider_chart_series"]["success_rate"] == [
        {
            "provider_id": 1,
            "label": "Claude Sonnet / claude-sonnet-4-6",
            "value": pytest.approx(1.0),
        },
        {
            "provider_id": 1,
            "label": "Claude Sonnet / claude-3-5-sonnet",
            "value": pytest.approx(0.0),
        },
        {
            "provider_id": None,
            "label": "Unknown / Legacy",
            "value": pytest.approx(0.5),
        },
    ]
    assert response["provider_chart_series"]["avg_tokens_per_second"] == [
        {
            "provider_id": 1,
            "label": "Claude Sonnet / claude-sonnet-4-6",
            "value": pytest.approx(4.0),
        },
        {
            "provider_id": 1,
            "label": "Claude Sonnet / claude-3-5-sonnet",
            "value": pytest.approx(2.0),
        },
    ]


@pytest.mark.asyncio
async def test_get_analytics_provider_query_groups_by_provider_and_model():
    """It groups provider analytics by provider/model pair instead of provider only."""
    fixed_now = datetime(2026, 3, 14, 12, 0, 0)
    db = MagicMock()

    def execute_side_effect(query):
        sql = " ".join(str(query).split())

        if AnalyticsQueryStub._is_summary_query(sql):
            return MockResult(AnalyticsSummaryRow().as_result_row())
        if AnalyticsQueryStub._is_project_query(sql):
            return MockResult([])
        if AnalyticsQueryStub._is_available_initiators_query(sql):
            return MockResult([])
        if AnalyticsQueryStub._is_initiators_query(sql):
            return MockResult([])
        if AnalyticsQueryStub._is_trend_query(sql):
            return MockResult([])
        if AnalyticsQueryStub._is_priority_wait_query(sql):
            return MockResult([])
        if AnalyticsQueryStub._is_issue_status_query(sql):
            return MockResult([])
        if AnalyticsQueryStub._is_task_status_query(sql):
            return MockResult([])
        if AnalyticsQueryStub._is_error_query(sql):
            return MockResult([])
        if AnalyticsQueryStub._is_provider_query(sql):
            assert "GROUP BY tasks.provider_id, ai_providers.name, tasks.model_name" in sql
            return MockResult([])

        raise AssertionError(f"unrecognized analytics query: {sql}")

    db.execute = AsyncMock(side_effect=execute_side_effect)
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    with patch("app.api.stats.utcnow", return_value=fixed_now), patch(
        "app.api.stats.build_project_lookup", new=AsyncMock(return_value={})
    ):
        response = await get_analytics(
            days=7,
            project_id=None,
            initiator_username=None,
            db=db,
            _current_user=None,
            access_scope=access_scope,
        )

    assert response["providers"] == []
    assert response["provider_chart_series"] == {
        "success_rate": [],
        "avg_tokens_per_second": [],
        "avg_tokens_per_changed_line": [],
        "avg_execution_seconds_per_changed_line": [],
    }
