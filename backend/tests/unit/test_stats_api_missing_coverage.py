"""Additional tests to cover missing lines in app/api/stats.py.

This file specifically targets the uncovered lines:
- Line 68: my filter with username in get_stats
- Line 129: my filter with user ID in get_stats (issues section)
- Line 259: empty initiator_username after strip in get_analytics
- Line 711: my filter with username in get_activity_heatmap
"""

import os
import sys
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.api.stats import get_stats, get_analytics, get_activity_heatmap
from app.dependencies.project_access import ProjectAccessScope
from app.models import User


class TestGetStatsMyFilterWithUsername(unittest.IsolatedAsyncioTestCase):
    """Test get_stats with my=True and username filtering."""

    def _make_scalar_result(self, value):
        result = MagicMock()
        result.scalar = MagicMock(return_value=value)
        return result

    def _build_side_effects(self, **kwargs):
        """Return 15 mock results for the get_stats call order."""
        defaults = dict(
            total=0, pending=0, queued=0, running=0, completed=0, failed=0, cancelled=0,
            completed_24h=0, failed_cancelled_24h=0, running_long_30min=0,
            issue_total=0, issue_open=0, issue_in_progress=0, issue_in_review=0, issue_closed=0,
        )
        defaults.update(kwargs)
        keys = [
            "total", "pending", "queued", "running", "completed", "failed", "cancelled",
            "completed_24h", "failed_cancelled_24h", "running_long_30min",
            "issue_total", "issue_open", "issue_in_progress", "issue_in_review", "issue_closed",
        ]
        return [self._make_scalar_result(defaults[k]) for k in keys]

    async def test_stats_my_filter_with_username_covers_line_68(self):
        """get_stats with my=True should filter by username (covers line 68)."""
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=self._build_side_effects(total=3, issue_total=2))
        
        # Create a User with username attribute
        mock_user = User(id=1, username="testuser", platform_role="developer")
        
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        
        result = await get_stats(my=True, db=mock_db, current_user=mock_user, access_scope=scope)
        
        self.assertEqual(result["total"], 3)
        self.assertGreater(mock_db.execute.call_count, 0)

    async def test_stats_my_filter_with_username_issues_covers_line_129(self):
        """get_stats with my=True should filter issues by user ID (covers line 129)."""
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=self._build_side_effects(total=3, issue_total=2))
        
        # Create a User with id for issues filtering
        mock_user = User(id=1, username="testuser", platform_role="developer")
        
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        
        result = await get_stats(my=True, db=mock_db, current_user=mock_user, access_scope=scope)
        
        self.assertEqual(result["issues"]["total"], 2)
        self.assertGreater(mock_db.execute.call_count, 0)


class TestGetAnalyticsEmptyInitiatorUsername(unittest.IsolatedAsyncioTestCase):
    """Test get_analytics with empty initiator_username after strip."""

    async def test_analytics_empty_initiator_username_after_strip_covers_line_259(self):
        """get_analytics with whitespace-only initiator_username (covers line 259)."""
        mock_db = MagicMock()
        
        # Mock the query results - need to return a tuple with 19 values
        mock_one_result = (
            0,  # total_tasks
            0,  # total_additions
            0,  # total_deletions
            0,  # total_changes
            0,  # total_input_tokens
            0,  # total_output_tokens
            0,  # completed_tasks
            0,  # failed_tasks
            0,  # cancelled_tasks
            0,  # finished_tasks
            0,  # tracked_initiator_tasks
            0,  # token_tracked_tasks
            None,  # initiator_tracking_started_at
            None,  # avg_execution_seconds
            None,  # max_execution_seconds
            None,  # avg_queue_wait_seconds
            None,  # max_queue_wait_seconds
            None,  # avg_total_tokens_per_tracked_task
            None,  # max_total_tokens_per_tracked_task
        )
        mock_summary = MagicMock()
        mock_summary.one = MagicMock(return_value=mock_one_result)
        
        # Mock result for queries that return .all()
        mock_empty_rows = MagicMock()
        mock_empty_rows.all = MagicMock(return_value=[])
        
        # get_analytics makes 7 DB calls:
        # 1. summary_query (returns .one())
        # 2. project_query (returns .all())
        # 3. available_initiators_query (returns .all())
        # 4. initiator_query (returns .all())
        # 5. trend_query (returns .all())
        # 6. priority_wait_query (returns .all())
        # 7. error_query (returns .all())
        
        mock_db.execute = AsyncMock(side_effect=[
            mock_summary,       # summary
            mock_empty_rows,    # projects
            mock_empty_rows,    # available initiators
            mock_empty_rows,    # initiators
            mock_empty_rows,    # trend
            mock_empty_rows,    # priority wait
            mock_empty_rows,    # errors
        ])
        
        mock_user = User(id=1, username="admin", platform_role="platform_admin")
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        
        # Pass whitespace-only string, which should be stripped to empty and then set to None
        result = await get_analytics(
            days=7,
            project_id=None,
            initiator_username="  ",  # whitespace only
            db=mock_db,
            _current_user=mock_user,
            access_scope=scope,
        )
        
        # Should return valid response dict, not error
        self.assertIsInstance(result, dict)
        self.assertIn("summary", result)
        self.assertIn("trends", result)


class TestGetActivityHeatmapMyFilterWithUsername(unittest.IsolatedAsyncioTestCase):
    """Test get_activity_heatmap with my=True and username filtering."""

    async def test_activity_heatmap_my_filter_with_username_covers_line_711(self):
        """get_activity_heatmap with my=True should filter by username (covers line 711)."""
        mock_db = MagicMock()
        
        # Mock the query results
        mock_result = MagicMock()
        mock_result.all = MagicMock(return_value=[
            SimpleNamespace(date=datetime.now().date(), count=5),
        ])
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        # Mock user with username
        mock_user = User(id=1, username="heatmapuser", platform_role="developer")
        
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        
        result = await get_activity_heatmap(
            days=7,
            my=True,
            db=mock_db,
            current_user=mock_user,
            access_scope=scope,
        )
        
        self.assertIsInstance(result, list)
        self.assertGreater(mock_db.execute.call_count, 0)
