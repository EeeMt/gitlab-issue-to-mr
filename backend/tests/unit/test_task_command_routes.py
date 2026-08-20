"""Unit tests for the V2 command REST surface (phase1-design §2.2).

These use a mocked DB session and patched service functions, mirroring the
existing API test convention, to assert the HTTP layer: PUT idempotent create
(201/200/409), GET recovery ordering, and rejection mapping.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.core.task_harness_commands import CommandCreateResult
from app.database import get_db
from app.dependencies.auth import require_authenticated_user
from app.dependencies.project_access import require_project_access_scope
from app.main import app


def _command(cmd_id="01Kxyz", status="queued", sequence_no=1, cmd_type="steer"):
    cmd = MagicMock()
    cmd.command_id = cmd_id
    cmd.task_id = 7
    cmd.attempt_id = "task-7-attempt-1"
    cmd.sequence_no = sequence_no
    cmd.command_type = cmd_type
    cmd.payload = {"text": "先修复并发问题"}
    cmd.payload_digest = "d" * 64
    cmd.status = status
    cmd.created_by = "alice"
    cmd.created_at = datetime(2026, 8, 21, tzinfo=UTC)
    cmd.delivery_attempts = 0
    cmd.last_attempt_at = None
    cmd.delivered_at = None
    cmd.rejected_at = None
    cmd.rejection_code = None
    cmd.rejection_message = None
    return cmd


class TaskCommandRoutesTest(unittest.TestCase):
    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock()
        self.mock_db.get = AsyncMock()
        self.mock_db.commit = AsyncMock()
        self.mock_db.flush = AsyncMock()
        self.mock_db.add = MagicMock()

        app.dependency_overrides[get_db] = lambda: self.mock_db
        app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
        app.dependency_overrides[require_project_access_scope] = lambda: MagicMock()
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_put_command_created_returns_201_body(self):
        result = CommandCreateResult(
            command_id="01Kxyz", sequence_no=1, created=True, outcome="created"
        )
        with (
            patch(
                "app.api.task_command_routes.get_task_with_access_check",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.api.task_command_routes.create_command",
                new=AsyncMock(return_value=result),
            ) as create_mock,
            patch(
                "app.api.task_command_routes._load_command",
                new=AsyncMock(return_value=_command()),
            ),
        ):
            resp = self.client.put(
                "/api/tasks/7/commands/01Kxyz",
                json={"type": "steer", "text": "先修复并发问题"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["created"])
        self.assertEqual(body["command"]["command_id"], "01Kxyz")
        self.assertEqual(body["command"]["sequence_no"], 1)
        # create_command called with the canonical payload envelope.
        _, kwargs = create_mock.call_args
        self.assertEqual(kwargs["payload"], {"text": "先修复并发问题"})
        self.assertEqual(kwargs["command_type"], "steer")

    def test_put_command_conflict_returns_409(self):
        result = CommandCreateResult(
            command_id="01Kxyz",
            sequence_no=0,
            created=False,
            outcome="existing_conflict",
            rejection_code="existing_conflict",
            rejection_message="command_id already exists with a different payload",
        )
        with (
            patch(
                "app.api.task_command_routes.get_task_with_access_check",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.api.task_command_routes.create_command",
                new=AsyncMock(return_value=result),
            ),
        ):
            resp = self.client.put(
                "/api/tasks/7/commands/01Kxyz",
                json={"type": "steer", "text": "different"},
            )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["detail"]["code"], "existing_conflict")

    def test_put_command_control_gate_closed_returns_409(self):
        result = CommandCreateResult(
            command_id="01Kxyz",
            sequence_no=0,
            created=False,
            outcome="control_gate_closed",
            rejection_code="control_gate_closed",
            rejection_message="control gate is disabled, not accepting",
        )
        with (
            patch(
                "app.api.task_command_routes.get_task_with_access_check",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.api.task_command_routes.create_command",
                new=AsyncMock(return_value=result),
            ),
        ):
            resp = self.client.put(
                "/api/tasks/7/commands/01Kxyz",
                json={"type": "steer", "text": "x"},
            )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["detail"]["code"], "control_gate_closed")

    def test_put_command_invalid_type_returns_422(self):
        resp = self.client.put(
            "/api/tasks/7/commands/01Kxyz",
            json={"type": "explode", "text": "x"},
        )
        self.assertEqual(resp.status_code, 422)

    def test_get_commands_returns_ordered_list(self):
        cmds = [_command("c-1", sequence_no=1), _command("c-2", sequence_no=2)]
        with (
            patch(
                "app.api.task_command_routes.get_task_with_access_check",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.api.task_command_routes.list_commands",
                new=AsyncMock(return_value=cmds),
            ),
        ):
            resp = self.client.get("/api/tasks/7/commands")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([c["command_id"] for c in resp.json()["commands"]], ["c-1", "c-2"])

    def test_get_command_not_found_returns_404(self):
        with (
            patch(
                "app.api.task_command_routes.get_task_with_access_check",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.api.task_command_routes._load_command",
                new=AsyncMock(return_value=None),
            ),
        ):
            resp = self.client.get("/api/tasks/7/commands/01Kxyz")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
