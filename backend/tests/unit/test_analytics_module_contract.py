"""Architecture contracts for the analytics endpoint split."""

import inspect
from dataclasses import fields

from app.api.analytics_queries import AnalyticsQueries
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
    ]
