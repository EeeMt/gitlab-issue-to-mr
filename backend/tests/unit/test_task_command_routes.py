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
    cmd.dispatch_started_at = None
    cmd.native_request_id = None
    cmd.native_sent_at = None
    cmd.native_ack_at = None
    cmd.outcome_unknown_at = None
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
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertTrue(body["created"])
        self.assertEqual(body["command"]["command_id"], "01Kxyz")
        self.assertEqual(body["command"]["sequence_no"], 1)
        self.assert_public_command_projection(body["command"])
        # create_command called with the canonical payload envelope.
        _, kwargs = create_mock.call_args
        self.assertEqual(kwargs["payload"], {"text": "先修复并发问题"})
        self.assertEqual(kwargs["command_type"], "steer")

    def test_put_command_replay_returns_200(self):
        result = CommandCreateResult(
            command_id="01Kxyz", sequence_no=1, created=False, outcome="existing_same"
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
        self.assertFalse(body["created"])
        self.assertEqual(body["outcome"], "existing_same")
        self.assert_public_command_projection(body["command"])

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
        self.assertEqual(
            resp.json()["detail"]["message"],
            "The command channel is not accepting commands.",
        )

    def test_rejection_never_exposes_persisted_diagnostics(self):
        result = CommandCreateResult(
            command_id="01Kxyz",
            sequence_no=0,
            created=False,
            outcome="control_gate_closed",
            rejection_code="control_gate_closed",
            rejection_message="socket /tmp/private-token-payload failed: sk-secret",
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
        self.assertNotIn("private-token-payload", resp.text)
        self.assertNotIn("sk-secret", resp.text)

    def test_unknown_rejection_code_uses_generic_public_message(self):
        command = _command("c-unsafe", status="rejected")
        command.rejection_code = "bridge_exception"
        command.rejection_message = "ValueError: /private/path with payload=super-secret"
        with (
            patch(
                "app.api.task_command_routes.get_task_with_access_check",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.api.task_command_routes._load_command",
                new=AsyncMock(return_value=command),
            ),
        ):
            resp = self.client.get("/api/tasks/7/commands/c-unsafe")
        self.assertEqual(resp.status_code, 200)
        projected = resp.json()
        self.assertEqual(projected["rejection_code"], "command_rejected")
        self.assertEqual(projected["rejection_message"], "The command was rejected.")
        self.assertNotIn("private/path", resp.text)
        self.assertNotIn("super-secret", resp.text)
        self.assert_public_command_projection(projected)

    def test_single_unknown_type_fails_closed_without_echoing_value(self):
        command = _command("c-unsafe", cmd_type="injected-type-secret")
        with (
            patch(
                "app.api.task_command_routes.get_task_with_access_check",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.api.task_command_routes._load_command",
                new=AsyncMock(return_value=command),
            ),
        ):
            resp = self.client.get("/api/tasks/7/commands/c-unsafe")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(
            resp.json()["detail"],
            {
                "code": "command_projection_unavailable",
                "message": "Command history is temporarily unavailable.",
            },
        )
        self.assertNotIn("injected-type-secret", resp.text)

    def test_single_unknown_status_fails_closed_without_echoing_value(self):
        command = _command("c-unsafe", status="persisted-status-secret")
        with (
            patch(
                "app.api.task_command_routes.get_task_with_access_check",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.api.task_command_routes._load_command",
                new=AsyncMock(return_value=command),
            ),
        ):
            resp = self.client.get("/api/tasks/7/commands/c-unsafe")
        self.assertEqual(resp.status_code, 500)
        self.assertNotIn("persisted-status-secret", resp.text)

    def test_list_unknown_status_fails_closed_without_echoing_value(self):
        commands = [_command("c-1"), _command("c-2", status="status-secret")]
        with (
            patch(
                "app.api.task_command_routes.get_task_with_access_check",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.api.task_command_routes.list_commands",
                new=AsyncMock(return_value=commands),
            ),
        ):
            resp = self.client.get("/api/tasks/7/commands")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()["detail"]["code"], "command_projection_unavailable")
        self.assertNotIn("status-secret", resp.text)

    def test_list_unknown_type_fails_closed_without_echoing_value(self):
        commands = [_command("c-1"), _command("c-2", cmd_type="type-secret")]
        with (
            patch(
                "app.api.task_command_routes.get_task_with_access_check",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.api.task_command_routes.list_commands",
                new=AsyncMock(return_value=commands),
            ),
        ):
            resp = self.client.get("/api/tasks/7/commands")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()["detail"]["code"], "command_projection_unavailable")
        self.assertNotIn("type-secret", resp.text)

    def test_dispatching_projects_allowlisted_timestamps(self):
        command = _command("c-dispatching", status="dispatching")
        command.dispatch_started_at = datetime(2026, 8, 21, 1, 2, 3, tzinfo=UTC)
        command.native_ack_at = None
        with (
            patch(
                "app.api.task_command_routes.get_task_with_access_check",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.api.task_command_routes._load_command",
                new=AsyncMock(return_value=command),
            ),
        ):
            resp = self.client.get("/api/tasks/7/commands/c-dispatching")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "dispatching")
        self.assertEqual(resp.json()["dispatch_started_at"], "2026-08-21T01:02:03+00:00")
        self.assertIsNone(resp.json()["native_ack_at"])

    def test_outcome_unknown_projects_only_stable_delivery_code(self):
        command = _command("c-unknown", status="outcome_unknown")
        command.rejection_code = "delivery_outcome_unknown"
        command.rejection_message = "bridge secret and /private/path"
        command.outcome_unknown_at = datetime(2026, 8, 21, tzinfo=UTC)
        with (
            patch(
                "app.api.task_command_routes.get_task_with_access_check",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.api.task_command_routes._load_command",
                new=AsyncMock(return_value=command),
            ),
        ):
            resp = self.client.get("/api/tasks/7/commands/c-unknown")
        self.assertEqual(resp.status_code, 200)
        projected = resp.json()
        self.assertEqual(projected["rejection_code"], "delivery_outcome_unknown")
        self.assertEqual(
            projected["rejection_message"], "The command delivery outcome is unknown."
        )
        self.assertNotIn("bridge secret", resp.text)
        self.assertNotIn("private/path", resp.text)

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
        commands = resp.json()["commands"]
        self.assertEqual([c["command_id"] for c in commands], ["c-1", "c-2"])
        for command in commands:
            self.assert_public_command_projection(command)

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

    def assert_public_command_projection(self, command):
        self.assertEqual(
            set(command),
            {
                "command_id",
                "sequence_no",
                "type",
                "status",
                "created_at",
                "dispatch_started_at",
                "native_ack_at",
                "outcome_unknown_at",
                "delivered_at",
                "rejected_at",
                "rejection_code",
                "rejection_message",
            },
        )
        for internal_field in (
            "task_id",
            "attempt_id",
            "payload",
            "payload_digest",
            "created_by",
            "delivery_attempts",
            "last_attempt_at",
            "native_request_id",
            "native_sent_at",
        ):
            self.assertNotIn(internal_field, command)


if __name__ == "__main__":
    unittest.main()
