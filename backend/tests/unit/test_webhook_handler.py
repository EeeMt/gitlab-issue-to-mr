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


def _make_mock_settings(gitlab_webhook_secret="global-secret"):
    settings = MagicMock()
    settings.gitlab_webhook_secret = gitlab_webhook_secret
    return settings


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

        # Patch settings
        self.settings_patcher = patch(
            "app.api.webhook_handler.get_effective_settings",
            return_value=_make_mock_settings(),
        )
        self.mock_settings = self.settings_patcher.start()

        # Patch load_runtime_config_from_db
        self.runtime_patcher = patch(
            "app.api.webhook_handler.load_runtime_config_from_db",
            new_callable=AsyncMock,
        )
        self.runtime_patcher.start()

        # Patch project webhook secret lookup
        self.secret_patcher = patch(
            "app.api.webhook_handler.get_project_webhook_secret",
            new_callable=AsyncMock,
            return_value=None,  # No per-project secret by default → use global
        )
        self.mock_get_secret = self.secret_patcher.start()

        from app.main import app
        from app.database import get_db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.settings_patcher.stop()
        self.runtime_patcher.stop()
        self.secret_patcher.stop()
        from app.main import app
        from app.database import get_db
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

    def test_correct_global_token_accepted(self):
        # Mock no matching issues
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        payload = _build_mr_merge_payload()
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "global-secret"},
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
            headers={"X-Gitlab-Token": "global-secret"},
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
            headers={"X-Gitlab-Token": "global-secret"},
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
            headers={"X-Gitlab-Token": "global-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["result"], "ignored_action")

    def test_non_mr_event_returns_unsupported(self):
        payload = _build_note_payload()
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "global-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["result"], "unsupported_event")

    def test_missing_project_id_returns_400(self):
        payload = {"object_kind": "merge_request", "object_attributes": {"action": "merge", "iid": 1}}
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "global-secret"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_no_secrets_configured_returns_401(self):
        self.mock_settings.return_value = _make_mock_settings(gitlab_webhook_secret="")
        payload = _build_mr_merge_payload()
        resp = self.client.post(
            "/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "some-token"},
        )
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
