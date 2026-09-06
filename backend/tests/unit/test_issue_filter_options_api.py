"""Tests for the worker profile options returned by GET /api/issues/filter-options."""

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _result(rows):
    result = MagicMock()
    result.all.return_value = rows
    return result


class TestIssueFilterOptionsWorkerProfiles(unittest.IsolatedAsyncioTestCase):
    """Worker profile filter options reflect in-scope issues only."""

    async def _options(self, db, scope):
        from app.api.issues import get_issue_filter_options

        with patch(
            "app.api.issues.list_initiator_filter_options",
            new=AsyncMock(return_value={"initiators": []}),
        ):
            return await get_issue_filter_options(
                db=db, _current_user=MagicMock(), access_scope=scope
            )

    async def test_returns_profiles_with_issue_counts(self):
        """Options list every referenced profile with its distinct issue count."""
        from app.dependencies.project_access import ProjectAccessScope

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _result([("0.4.0", 2)]),
                _result([(2, "Python Worker", 3), (5, "Go Worker", 1)]),
            ]
        )
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await self._options(db, scope)

        self.assertEqual(
            result["worker_profiles"],
            [
                {"value": "2", "label": "Python Worker", "count": 3},
                {"value": "5", "label": "Go Worker", "count": 1},
            ],
        )
        # worker kit options remain available alongside profile options
        self.assertEqual(result["worker_kits"], [{"value": "0.4.0", "label": "0.4.0", "count": 2}])

    async def test_restricted_scope_filters_profile_options_by_project(self):
        """Restricted scopes must not leak profiles of other projects."""
        from app.dependencies.project_access import ProjectAccessScope

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _result([]),
                _result([(2, "Python Worker", 3)]),
            ]
        )
        scope = ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 10, "name": "P"}, {"id": 20, "name": "Q"}],
        )

        result = await self._options(db, scope)

        self.assertEqual(result["worker_profiles"], [{"value": "2", "label": "Python Worker", "count": 3}])
        profile_sql = str(db.execute.await_args_list[1].args[0])
        self.assertIn("issues.project_id IN", profile_sql)

    async def test_restricted_empty_scope_returns_no_profile_options(self):
        """An empty access scope short-circuits the profile options query."""
        from app.dependencies.project_access import ProjectAccessScope

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _result([]),
                _result([]),
            ]
        )
        scope = ProjectAccessScope(is_unrestricted=False, accessible_projects=[])

        result = await self._options(db, scope)

        self.assertEqual(result["worker_profiles"], [])
        profile_sql = str(db.execute.await_args_list[1].args[0])
        self.assertIn("false", profile_sql)
