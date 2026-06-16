#!/usr/bin/env python3
"""Unit tests for the GitLab webhook handler.

Tests cover:
- Token verification (per-project secret, global fallback, missing, mismatch)
- MR merge event → issue closed
- MR non-merge event → ignored
- Non-merge_request event → unsupported
- Already closed issue → idempotent
- No matching issue → no_match
- Multiple matching issues → all closed
- Invalid payload (missing project.id, bad JSON handled by FastAPI)
- WebhookEvent records created for each scenario
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient


def _build_mr_merge_payload(project_id=42, mr_iid=7):
    """Build a minimal GitLab MR merge webhook payload."""
    return {
        "object_kind": "merge_request",
        "project": {"id": project_id, "path_with_namespace": "group/project"},
        "object_attributes": {
            "iid": mr_iid,
            "action": "merge",
            "title": "Fix bug",
            "state": "merged",
            "source_branch": "codify/issue-1",
            "target_branch": "main",
        },
    }


def _build_mr_close_payload(project_id=42, mr_iid=7):
    payload = _build_mr_merge_payload(project_id, mr_iid)
    payload["object_attributes"]["action"] = "close"
    payload["object_attributes"]["state"] = "closed"
    return payload


def _build_note_payload(project_id=42):
    return {
        "object_kind": "note",
        "project": {"id": project_id},
        "object_attributes": {"note": "some comment"},
    }


def _build_pipeline_payload(project_id=42, pipeline_id=678, status="failed", sha="abc123"):
    return {
        "object_kind": "pipeline",
        "project": {"id": project_id, "path_with_namespace": "group/project"},
        "object_attributes": {
            "id": pipeline_id,
            "status": status,
            "sha": sha,
            "ref": "codify/issue-1",
            "url": "https://gitlab.example.com/group/project/-/pipelines/678",
        },
        "merge_request": {
            "iid": 7,
            "source_branch": "codify/issue-1",
            "target_branch": "main",
        },
    }


class TestWebhookReceiver(unittest.IsolatedAsyncioTestCase):
    """Tests for POST /api/webhook/gitlab."""

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock()
        self.mock_db.commit = AsyncMock()
        self.mock_db.add = MagicMock()
        self.mock_db.flush = AsyncMock()
        self.mock_db.get = AsyncMock(return_value=None)

        async def override_db():
            yield self.mock_db

        # Patch project webhook secret lookup
        self.secret_patcher = patch(
            "app.api.webhook_handler.get_project_webhook_secret",
            new_callable=AsyncMock,
            return_value="project-secret",
        )
        self.mock_get_secret = self.secret_patcher.start()

        from app.database import get_db
        from app.main import app

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.secret_patcher.stop()
        from app.database import get_db
        from app.main import app
        app.dependency_overrides.pop(get_db, None)

    def test_missing_token_returns_401(self):
        payload = _build_mr_merge_payload()
        resp = self.client.post("/api/webhook/gitlab", json=payload)
        self.assertEqual(resp.status_code, 401)

    def test_wrong_token_returns_401(self):
        payload = _build_mr_merge_payload()
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "wrong-secret"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_legacy_global_token_is_not_accepted(self):
        self.mock_get_secret.return_value = None
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        payload = _build_mr_merge_payload()
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "global-secret"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_correct_project_token_accepted(self):
        # Mock no matching issues
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        payload = _build_mr_merge_payload()
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "project-secret"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_per_project_secret_takes_priority(self):
        self.mock_get_secret.return_value = "project-secret"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        payload = _build_mr_merge_payload()
        # Global secret should fail when per-project secret is set
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "global-secret"},
        )
        self.assertEqual(resp.status_code, 401)

        # Per-project secret should succeed
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "project-secret"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_mr_merge_closes_matching_issue(self):
        mock_issue = MagicMock()
        mock_issue.id = 1
        mock_issue.status = "in_review"
        mock_issue.project_id = 42
        mock_issue.merge_request_iid = 7

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_issue]
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        payload = _build_mr_merge_payload(project_id=42, mr_iid=7)
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "project-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_issue.status, "closed")
        self.mock_db.commit.assert_awaited()

    def test_mr_merge_already_closed_is_idempotent(self):
        mock_issue = MagicMock()
        mock_issue.id = 1
        mock_issue.status = "closed"
        mock_issue.project_id = 42
        mock_issue.merge_request_iid = 7

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_issue]
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        payload = _build_mr_merge_payload(project_id=42, mr_iid=7)
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "project-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        # Status should still be closed — not changed
        self.assertEqual(mock_issue.status, "closed")
        data = resp.json()
        self.assertIn("ignored_already_closed", str(data.get("results", [])))

    def test_mr_non_merge_action_ignored(self):
        payload = _build_mr_close_payload()
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "project-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["result"], "ignored_action")

    def test_non_mr_event_returns_unsupported(self):
        payload = _build_note_payload()
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "project-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["result"], "unsupported_event")

    def test_pipeline_failed_event_creates_ci_failure_run(self):
        from app.models import CIFailureRun, WebhookEvent

        duplicate_result = MagicMock()
        duplicate_result.scalar_one_or_none.return_value = None
        self.mock_db.execute = AsyncMock(return_value=duplicate_result)

        payload = _build_pipeline_payload(project_id=42, pipeline_id=678)
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "project-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["result"], "ci_failure_collecting")

        added = [call.args[0] for call in self.mock_db.add.call_args_list]
        event = next(item for item in added if isinstance(item, WebhookEvent))
        run = next(item for item in added if isinstance(item, CIFailureRun))
        self.assertEqual(event.event_type, "pipeline")
        self.assertEqual(event.result, "ci_failure_collecting")
        self.assertEqual(event.payload_summary["pipeline_id"], 678)
        self.assertEqual(event.payload_summary["pipeline_status"], "failed")
        self.assertEqual(run.project_id, 42)
        self.assertEqual(run.pipeline_id, 678)
        self.assertEqual(run.pipeline_sha, "abc123")
        self.assertEqual(run.merge_request_iid, 7)
        self.assertEqual(run.status, "collecting")

    def test_pipeline_duplicate_blocks_active_run(self):
        from app.models import CIFailureRun

        existing_run = MagicMock(spec=CIFailureRun)
        existing_run.id = 1
        existing_run.status = "collecting"
        duplicate_result = MagicMock()
        duplicate_result.scalar_one_or_none.return_value = existing_run
        self.mock_db.execute = AsyncMock(return_value=duplicate_result)

        payload = _build_pipeline_payload(project_id=42, pipeline_id=678)
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "project-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["result"], "duplicate")

    def test_pipeline_reprocesses_ignored_run(self):
        from app.models import CIFailureRun

        existing_run = MagicMock(spec=CIFailureRun)
        existing_run.id = 1
        existing_run.status = "ignored"
        existing_run.merge_request_iid = None
        existing_run.source_branch = None
        existing_run.target_branch = None
        existing_run.pipeline_ref = None
        duplicate_result = MagicMock()
        duplicate_result.scalar_one_or_none.return_value = existing_run
        self.mock_db.execute = AsyncMock(return_value=duplicate_result)

        payload = _build_pipeline_payload(project_id=42, pipeline_id=678)
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "project-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["result"], "ci_failure_collecting")
        self.assertEqual(existing_run.status, "collecting")
        self.assertIsNone(existing_run.ignored_reason)
        self.assertEqual(existing_run.collection_attempts, 0)

    def test_pipeline_success_event_is_logged_and_ignored(self):
        payload = _build_pipeline_payload(status="success")
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "project-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["result"], "ignored_action")
        self.assertIn("Pipeline status 'success' ignored", data["detail"])

    def test_missing_project_id_returns_400(self):
        payload = {"object_kind": "merge_request", "object_attributes": {"action": "merge", "iid": 1}}
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "project-secret"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_no_secrets_configured_returns_401(self):
        self.mock_get_secret.return_value = None
        payload = _build_mr_merge_payload()
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "some-token"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_mr_merge_closes_multiple_matching_issues(self):
        """When multiple issues share the same project_id + merge_request_iid, all are closed."""
        issue1 = MagicMock()
        issue1.id = 10
        issue1.status = "in_review"
        issue1.project_id = 42
        issue1.merge_request_iid = 7

        issue2 = MagicMock()
        issue2.id = 20
        issue2.status = "open"
        issue2.project_id = 42
        issue2.merge_request_iid = 7

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [issue1, issue2]
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        payload = _build_mr_merge_payload(project_id=42, mr_iid=7)
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "project-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(issue1.status, "closed")
        self.assertEqual(issue2.status, "closed")
        data = resp.json()
        self.assertEqual(len(data["results"]), 2)
        self.assertTrue(all(r["result"] == "issue_closed" for r in data["results"]))

    @patch("app.api.webhook_handler._try_delete_issue_branch", new_callable=AsyncMock)
    def test_mr_merge_calls_try_delete_issue_branch(self, mock_delete_branch):
        """When MR is merged, _try_delete_issue_branch is called for the issue."""
        mock_issue = MagicMock()
        mock_issue.id = 1
        mock_issue.status = "in_review"
        mock_issue.project_id = 42
        mock_issue.merge_request_iid = 7
        mock_issue.branch_name = "codify/issue-1"
        mock_issue.delete_branch_on_close = True

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_issue]
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        payload = _build_mr_merge_payload(project_id=42, mr_iid=7)
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "project-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_issue.status, "closed")
        # Verify _try_delete_issue_branch was called with the issue and db
        mock_delete_branch.assert_awaited_once_with(mock_issue, self.mock_db)


class TestWebhookEventsEndpoint(unittest.IsolatedAsyncioTestCase):
    """Tests for GET /api/webhook/events."""

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock()

        async def override_db():
            yield self.mock_db

        from app.database import get_db
        from app.dependencies.auth import require_authenticated_user
        from app.main import app

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
        self.client = TestClient(app)

    def tearDown(self):
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_user
        from app.main import app
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_authenticated_user, None)

    def _mock_db_results(self, events, total):
        """Set up mock DB to return the given events and total count."""

        count_result = MagicMock()
        count_result.scalar.return_value = total

        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = events

        self.mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])

    def _make_event(self, id=1, event_type="merge_request", event_action="merge",
                    project_id=42, result="issue_closed"):
        from datetime import datetime
        e = MagicMock()
        e.id = id
        e.event_type = event_type
        e.event_action = event_action
        e.project_id = project_id
        e.merge_request_iid = 7
        e.issue_id = 1
        e.source_ip = "10.0.0.1"
        e.result = result
        e.result_detail = None
        e.payload_summary = {"mr_title": "Fix bug"}
        e.created_at = datetime(2026, 1, 1, 12, 0, 0)
        return e

    def test_list_events_returns_items(self):
        event = self._make_event()
        self._mock_db_results([event], 1)

        resp = self.client.get("/api/webhook/events")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["result"], "issue_closed")
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 20)

    def test_list_events_empty(self):
        self._mock_db_results([], 0)

        resp = self.client.get("/api/webhook/events")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(len(data["items"]), 0)

    def test_pagination_params(self):
        self._mock_db_results([], 0)

        resp = self.client.get("/api/webhook/events?page=2&page_size=10")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["page"], 2)
        self.assertEqual(data["page_size"], 10)

    def test_page_size_clamped_to_100(self):
        self._mock_db_results([], 0)

        resp = self.client.get("/api/webhook/events?page_size=500")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["page_size"], 100)

    def test_filter_by_result(self):
        event = self._make_event(result="issue_closed")
        self._mock_db_results([event], 1)

        resp = self.client.get("/api/webhook/events?result=issue_closed")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)

    def test_filter_by_event_type(self):
        event = self._make_event(event_type="merge_request")
        self._mock_db_results([event], 1)

        resp = self.client.get("/api/webhook/events?event_type=merge_request")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)

    def test_filter_by_project_id(self):
        event = self._make_event(project_id=42)
        self._mock_db_results([event], 1)

        resp = self.client.get("/api/webhook/events?project_id=42")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)


if __name__ == "__main__":
    unittest.main()
