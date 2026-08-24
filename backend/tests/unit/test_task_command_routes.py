"""Unit tests for the V2 command REST surface (phase1-design §2.2).

These use a mocked DB session and patched service functions, mirroring the
existing API test convention, to assert the HTTP layer: PUT idempotent create
(201/200/409), GET recovery ordering, and rejection mapping.
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.task_harness_commands import CommandCreateResult
from app.database import get_db
from app.dependencies.auth import require_authenticated_user
from app.dependencies.project_access import require_project_access_scope
from app.main import (
    _MAX_TASK_COMMAND_REQUEST_BYTES,
    _read_bounded_task_command_body,
    app,
    preflight_task_command_input,
)

VALID_ULID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"


def _command(cmd_id=VALID_ULID, status="queued", sequence_no=1, cmd_type="steer"):
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
            command_id=VALID_ULID, sequence_no=1, created=True, outcome="created"
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
                f"/api/tasks/7/commands/{VALID_ULID}",
                json={"type": "steer", "text": "先修复并发问题"},
            )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertTrue(body["created"])
        self.assertEqual(body["command"]["command_id"], VALID_ULID)
        self.assertEqual(body["command"]["sequence_no"], 1)
        self.assert_public_command_projection(body["command"])
        # create_command called with the canonical payload envelope.
        _, kwargs = create_mock.call_args
        self.assertEqual(kwargs["payload"], {"text": "先修复并发问题"})
        self.assertEqual(kwargs["command_type"], "steer")

    def test_put_command_replay_returns_200(self):
        result = CommandCreateResult(
            command_id=VALID_ULID, sequence_no=1, created=False, outcome="existing_same"
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
                f"/api/tasks/7/commands/{VALID_ULID}",
                json={"type": "steer", "text": "先修复并发问题"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["created"])
        self.assertEqual(body["outcome"], "existing_same")
        self.assert_public_command_projection(body["command"])

    def test_put_command_conflict_returns_409(self):
        result = CommandCreateResult(
            command_id=VALID_ULID,
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
                f"/api/tasks/7/commands/{VALID_ULID}",
                json={"type": "steer", "text": "different"},
            )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["detail"]["code"], "existing_conflict")

    def test_put_command_control_gate_closed_returns_409(self):
        result = CommandCreateResult(
            command_id=VALID_ULID,
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
                f"/api/tasks/7/commands/{VALID_ULID}",
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
            command_id=VALID_ULID,
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
                f"/api/tasks/7/commands/{VALID_ULID}",
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
            resp = self.client.get(f"/api/tasks/7/commands/{VALID_ULID}")
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
            resp = self.client.get(f"/api/tasks/7/commands/{VALID_ULID}")
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
            resp = self.client.get(f"/api/tasks/7/commands/{VALID_ULID}")
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
            resp = self.client.get(f"/api/tasks/7/commands/{VALID_ULID}")
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
            resp = self.client.get(f"/api/tasks/7/commands/{VALID_ULID}")
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
            f"/api/tasks/7/commands/{VALID_ULID}",
            json={"type": "explode", "text": "x"},
        )
        self.assertEqual(resp.status_code, 422)

    def test_invalid_command_id_is_rejected_before_access_or_database_work(self):
        malicious_id = "not-a-command-id-private-secret"
        with patch(
            "app.api.task_command_routes.get_task_with_access_check", new=AsyncMock()
        ) as access_check:
            put = self.client.put(
                f"/api/tasks/7/commands/{malicious_id}",
                json={"type": "steer", "text": "x"},
            )
            get = self.client.get(f"/api/tasks/7/commands/{malicious_id}")
        self.assertEqual(put.status_code, 422)
        self.assertEqual(get.status_code, 422)
        self.assertEqual(
            put.json()["detail"],
            {"code": "invalid_command_id", "message": "The command ID format is invalid."},
        )
        self.assertEqual(get.json()["detail"], put.json()["detail"])
        self.assertNotIn(malicious_id, put.text)
        self.assertNotIn(malicious_id, get.text)
        access_check.assert_not_awaited()

    def test_preflight_rejects_id_and_utf16_text_before_real_auth_dependencies(self):
        """A 422 here proves FastAPI did not enter the normal 401 auth path."""
        app.dependency_overrides.clear()
        client = TestClient(app, raise_server_exceptions=False)
        malicious_id = "not-a-command-id-private-secret"
        signed_task_gets = [client.get(f"/api/tasks/7/commands/{malicious_id}")]
        put = client.put(
            f"/api/tasks/7/commands/{VALID_ULID}",
            json={"type": "steer", "text": "😀" * 2000 + "a"},
        )
        surrogate_put = client.put(
            f"/api/tasks/7/commands/{VALID_ULID}",
            content=b'{"type":"steer","text":"\\ud800"}',
            headers={"content-type": "application/json"},
        )
        for response in signed_task_gets:
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"]["code"], "invalid_command_id")
            self.assertNotIn(malicious_id, response.text)
        self.assertEqual(put.status_code, 422)
        self.assertEqual(surrogate_put.status_code, 422)
        self.assertEqual(put.json()["detail"]["code"], "payload_too_large")
        self.assertEqual(surrogate_put.json()["detail"]["code"], "payload_too_large")

    def test_invalid_task_id_is_nonreflecting_before_real_auth_dependencies(self):
        app.dependency_overrides.clear()
        client = TestClient(app, raise_server_exceptions=False)
        marker = "private-task-path-marker"
        responses = (
            client.get(f"/api/tasks/{marker}/commands/{VALID_ULID}"),
            client.put(
                f"/api/tasks/%2B1/commands/{VALID_ULID}",
                json={"type": "steer", "text": "x"},
            ),
            client.get(f"/api/tasks/0/commands/{VALID_ULID}"),
            client.get(f"/api/tasks/2147483648/commands/{VALID_ULID}"),
        )
        for response in responses:
            self.assertEqual(response.status_code, 422)
            self.assertEqual(
                response.json()["detail"],
                {"code": "invalid_task_id", "message": "The task ID format is invalid."},
            )
            self.assertNotIn(marker, response.text)

    def test_non_application_plus_json_is_rejected_without_body_reflection(self):
        app.dependency_overrides.clear()
        client = TestClient(app, raise_server_exceptions=False)
        marker = "private-command-body-marker"
        response = client.put(
            f"/api/tasks/7/commands/{VALID_ULID}",
            content=(f'{{"type":"steer","text":"{marker}"}}').encode(),
            headers={"content-type": "text/example+json"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "invalid_command_payload")
        self.assertNotIn(marker, response.text)

    def test_bounded_preflight_reader_limits_chunked_body_and_replays_valid_bytes(self):
        def receive_chunks(chunks):
            chunks = list(chunks)
            index = 0

            async def receive():
                nonlocal index
                if index == len(chunks):
                    return {"type": "http.disconnect"}
                chunk = chunks[index]
                index += 1
                return {
                    "type": "http.request",
                    "body": chunk,
                    "more_body": index < len(chunks),
                }

            return receive

        async def read(chunks):
            request = Request(
                {
                    "type": "http",
                    "method": "PUT",
                    "path": f"/api/tasks/7/commands/{VALID_ULID}",
                    "headers": [],
                },
                receive=receive_chunks(chunks),
            )
            result = await _read_bounded_task_command_body(request)
            return result, await request.body() if result is not None else None

        valid = b'{"type":"steer","text":"x"}'
        result, replayed = asyncio.run(read((valid[:8], valid[8:])))
        self.assertEqual(result, valid)
        self.assertEqual(replayed, valid)
        oversized = b"x" * (_MAX_TASK_COMMAND_REQUEST_BYTES + 1)
        result, replayed = asyncio.run(read((oversized[:1], oversized[1:])))
        self.assertIsNone(result)
        self.assertIsNone(replayed)

    def test_preflight_only_rewrites_scope_path_command_id(self):
        original_path = f"/api/tasks/0007/commands/{VALID_UUID.upper()}"
        original_raw_path = original_path.encode()
        scope = {
            "type": "http",
            "method": "GET",
            "path": original_path,
            "raw_path": original_raw_path,
            "query_string": b"view=history",
            "headers": [],
        }
        request = Request(scope)
        observed = {}

        async def call_next(passed_request):
            observed["path"] = passed_request.scope["path"]
            observed["raw_path"] = passed_request.scope["raw_path"]
            observed["query_string"] = passed_request.scope["query_string"]
            return MagicMock()

        asyncio.run(preflight_task_command_input(request, call_next))
        self.assertEqual(observed["path"], f"/api/tasks/0007/commands/{VALID_UUID}")
        self.assertEqual(observed["raw_path"], original_raw_path)
        self.assertEqual(observed["query_string"], b"view=history")

    def test_command_item_payload_validation_is_nonreflecting_before_real_auth(self):
        app.dependency_overrides.clear()
        client = TestClient(app, raise_server_exceptions=False)
        marker = "private-command-body-marker"
        responses = (
            client.put(
                f"/api/tasks/7/commands/{VALID_ULID}",
                json={"type": "steer", "text": {"marker": marker}},
            ),
            client.put(
                f"/api/tasks/7/commands/{VALID_ULID}",
                content=(f'{{"type":"steer","text":"{marker}"').encode(),
                headers={"content-type": "application/json"},
            ),
            client.put(
                f"/api/tasks/7/commands/{VALID_ULID}",
                content=marker.encode(),
                headers={"content-type": "text/plain"},
            ),
        )
        for response in responses:
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"]["code"], "invalid_command_payload")
            self.assertNotIn(marker, response.text)

    def test_uuid_and_case_insensitive_ulid_paths_are_canonical_before_create(self):
        for command_id, canonical_id in (
            (VALID_UUID.upper(), VALID_UUID),
            (VALID_ULID.lower(), VALID_ULID),
        ):
            with (
                self.subTest(command_id=command_id, canonical_id=canonical_id),
                patch(
                    "app.api.task_command_routes.get_task_with_access_check",
                    new=AsyncMock(return_value=MagicMock()),
                ),
                patch(
                    "app.api.task_command_routes.create_command",
                    new=AsyncMock(
                        return_value=CommandCreateResult(
                            command_id=canonical_id,
                            sequence_no=1,
                            created=True,
                            outcome="created",
                        )
                    ),
                ) as create_mock,
                patch(
                    "app.api.task_command_routes._load_command",
                    new=AsyncMock(return_value=_command(canonical_id)),
                ),
            ):
                response = self.client.put(
                    f"/api/tasks/7/commands/{command_id}",
                    json={"type": "steer", "text": "x"},
                )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(create_mock.call_args.kwargs["command_id"], canonical_id)
            self.assertEqual(response.json()["command"]["command_id"], canonical_id)

    def test_case_variants_are_canonical_before_single_command_load(self):
        for command_id, canonical_id in (
            (VALID_UUID.upper(), VALID_UUID),
            (VALID_ULID.lower(), VALID_ULID),
        ):
            with (
                self.subTest(command_id=command_id, canonical_id=canonical_id),
                patch(
                    "app.api.task_command_routes.get_task_with_access_check",
                    new=AsyncMock(return_value=MagicMock()),
                ),
                patch(
                    "app.api.task_command_routes._load_command",
                    new=AsyncMock(return_value=_command(canonical_id)),
                ) as load_command,
            ):
                response = self.client.get(f"/api/tasks/7/commands/{command_id}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(load_command.call_args.kwargs["command_id"], canonical_id)
            self.assertEqual(response.json()["command_id"], canonical_id)

    def test_utf16_boundaries_are_enforced_before_access_check(self):
        cases = (
            ("a" * 4000, 201),
            ("a" * 4001, 422),
            ("😀" * 2000, 201),
            ("😀" * 2000 + "a", 422),
            ("a" * 3998 + "😀", 201),
            ("a" * 3998 + "😀" + "a", 422),
        )
        for text, expected_status in cases:
            with (
                self.subTest(units=len(text), expected_status=expected_status),
                patch(
                    "app.api.task_command_routes.get_task_with_access_check",
                    new=AsyncMock(return_value=MagicMock()),
                ) as access_check,
                patch(
                    "app.api.task_command_routes.create_command",
                    new=AsyncMock(
                        return_value=CommandCreateResult(
                            command_id=VALID_ULID,
                            sequence_no=1,
                            created=True,
                            outcome="created",
                        )
                    ),
                ),
                patch(
                    "app.api.task_command_routes._load_command",
                    new=AsyncMock(return_value=_command()),
                ),
            ):
                response = self.client.put(
                    f"/api/tasks/7/commands/{VALID_ULID}",
                    json={"type": "steer", "text": text},
                )
            self.assertEqual(response.status_code, expected_status)
            self.assertEqual(access_check.await_count, 1 if expected_status == 201 else 0)

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
            resp = self.client.get(f"/api/tasks/7/commands/{VALID_ULID}")
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
