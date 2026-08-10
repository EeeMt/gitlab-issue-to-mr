"""F5: previous-task summaries order by issue_sequence NULLS LAST, id (spec §6.8).

Kept in its own file so the ordering assertion does not depend on shared worker
test helpers that other issues may still be modifying.
"""

import unittest
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql

from app.core.worker_gitlab import build_previous_task_summaries


def _make_issue(**overrides):
    issue = MagicMock()
    issue.id = overrides.get("id", 10)
    issue.project_id = overrides.get("project_id", 100)
    issue.title = overrides.get("title", "Auth Issue")
    issue.description = overrides.get("description", "Implement auth")
    return issue


class TestBuildPreviousTaskSummariesOrdering(IsolatedAsyncioTestCase):
    """F5: previous summaries must follow issue_sequence (legacy NULLs last), then id."""

    async def test_orders_by_issue_sequence_nulls_last_then_id(self):
        issue = _make_issue()
        current_task = MagicMock()
        current_task.id = 3
        current_task.issue_id = issue.id
        current_task.issue_sequence = 3

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        await build_previous_task_summaries(mock_db, issue, current_task)

        stmt = mock_db.execute.call_args[0][0]
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        self.assertRegex(
            compiled,
            r"ORDER BY tasks\.issue_sequence ASC NULLS LAST, tasks\.id",
        )


if __name__ == "__main__":
    unittest.main()
