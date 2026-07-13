import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError


class MaintenanceApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_system_data_endpoint_delegates_to_service(self):
        from app.api.maintenance import CleanupSystemDataRequest, cleanup_system_data_endpoint

        db = MagicMock()
        service_result = MagicMock()
        service_result.to_dict.return_value = {
            "deleted_issues": 1,
            "deleted_tasks": 2,
            "skipped_active_issues": 0,
            "skipped_active_tasks": 0,
            "deleted_archives": 2,
            "missing_archives": 0,
            "deleted_workspaces": 1,
            "container_cleanup_errors": [],
            "file_cleanup_errors": [],
        }

        with (
            patch("app.api.maintenance.get_effective_settings") as settings,
            patch(
                "app.api.maintenance.cleanup_system_data",
                new=AsyncMock(return_value=service_result),
            ) as cleanup,
        ):
            settings.return_value.worker_workspace_host_path = "/workspaces"
            response = await cleanup_system_data_endpoint(
                body=CleanupSystemDataRequest(older_than_days=30, force=True),
                db=db,
                _current_user=MagicMock(),
            )

        cleanup.assert_awaited_once_with(
            db,
            older_than_days=30,
            force=True,
            workspace_root="/workspaces",
            settings=settings.return_value,
        )
        self.assertEqual(response.deleted_issues, 1)
        self.assertEqual(response.deleted_tasks, 2)

    async def test_cleanup_system_data_request_defaults_force_to_false(self):
        from app.api.maintenance import CleanupSystemDataRequest

        request = CleanupSystemDataRequest(older_than_days=30)

        self.assertEqual(request.older_than_days, 30)
        self.assertFalse(request.force)

    async def test_cleanup_system_data_request_requires_older_than_days(self):
        from app.api.maintenance import CleanupSystemDataRequest

        with self.assertRaises(ValidationError):
            CleanupSystemDataRequest()

    async def test_cleanup_system_data_request_rejects_zero_retention(self):
        from app.api.maintenance import CleanupSystemDataRequest

        with self.assertRaises(ValidationError):
            CleanupSystemDataRequest(older_than_days=0, force=False)
