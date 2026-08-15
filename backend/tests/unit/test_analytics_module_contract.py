"""Architecture contracts for the analytics endpoint split."""

import inspect
from dataclasses import fields
from types import SimpleNamespace

from app.api.analytics_queries import AnalyticsQueries
from app.api.analytics_responses import AnalyticsSummary
from app.api.stats import get_analytics


def test_analytics_route_keeps_query_and_response_details_outside_the_handler():
    source = inspect.getsource(get_analytics)

    assert "build_analytics_queries(" in source
    assert "build_analytics_response(" in source
    assert "select(" not in source


def test_analytics_query_bundle_keeps_all_response_domains_explicit():
    assert [field.name for field in fields(AnalyticsQueries)] == [
        "summary",
        "projects",
        "available_initiators",
        "initiators",
        "trends",
        "priority_waits",
        "issue_statuses",
        "task_statuses",
        "errors",
        "providers",
        "harnesses",
    ]


def _summary_values() -> list:
    return [
        3,  # total_tasks
        10,  # total_additions
        2,  # total_deletions
        12,  # total_changes
        100,  # total_input_tokens
        50,  # total_output_tokens
        2,  # completed_tasks
        1,  # failed_tasks
        0,  # cancelled_tasks
        3,  # finished_tasks
        3,  # tracked_initiator_tasks
        3,  # token_tracked_tasks
        None,  # initiator_tracking_started_at
        60.0,  # total_execution_seconds
        20.0,  # avg_execution_seconds
        40.0,  # max_execution_seconds
        5.0,  # avg_queue_wait_seconds
        8.0,  # max_queue_wait_seconds
        50.0,  # avg_total_tokens_per_tracked_task
        90.0,  # max_total_tokens_per_tracked_task
    ]


def test_analytics_summary_from_row_accepts_namespace_rows():
    field_names = [field.name for field in fields(AnalyticsSummary)]
    row = SimpleNamespace(**dict(zip(field_names, _summary_values())))

    summary = AnalyticsSummary.from_row(row)

    assert summary.total_tasks == 3
    assert summary.total_changes == 12
    assert summary.avg_execution_seconds == 20.0
    assert summary.max_total_tokens_per_tracked_task == 90.0


def test_analytics_summary_from_row_accepts_mapping_rows():
    field_names = [field.name for field in fields(AnalyticsSummary)]
    row = dict(zip(field_names, _summary_values()))

    summary = AnalyticsSummary.from_row(row)

    assert summary.total_tasks == 3
    assert summary.completed_tasks == 2
    assert summary.avg_queue_wait_seconds == 5.0
