#!/usr/bin/env python3
"""Unit tests for GitLab webhook secret verification."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.api.webhook import verify_gitlab_webhook


class WebhookVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_verify_gitlab_webhook_prefers_project_secret(self) -> None:
        payload = {"project": {"id": 12}, "object_kind": "note"}
        request = MagicMock()
        request.json = AsyncMock(return_value=payload)

        with patch("app.api.webhook.get_project_webhook_secret", AsyncMock(return_value="project-secret")), patch(
            "app.api.webhook.get_effective_settings",
            return_value=SimpleNamespace(gitlab_webhook_secret="global-secret"),
        ):
            result = await verify_gitlab_webhook(request, MagicMock(), "project-secret")

        self.assertEqual(result, payload)

    async def test_verify_gitlab_webhook_falls_back_to_global_secret(self) -> None:
        payload = {"project": {"id": 12}, "object_kind": "note"}
        request = MagicMock()
        request.json = AsyncMock(return_value=payload)

        with patch("app.api.webhook.get_project_webhook_secret", AsyncMock(return_value=None)), patch(
            "app.api.webhook.get_effective_settings",
            return_value=SimpleNamespace(gitlab_webhook_secret="global-secret"),
        ):
            result = await verify_gitlab_webhook(request, MagicMock(), "global-secret")

        self.assertEqual(result, payload)

    async def test_verify_gitlab_webhook_rejects_invalid_secret(self) -> None:
        payload = {"project": {"id": 12}, "object_kind": "note"}
        request = MagicMock()
        request.json = AsyncMock(return_value=payload)

        with patch("app.api.webhook.get_project_webhook_secret", AsyncMock(return_value="project-secret")), patch(
            "app.api.webhook.get_effective_settings",
            return_value=SimpleNamespace(gitlab_webhook_secret="global-secret"),
        ):
            with self.assertRaises(HTTPException):
                await verify_gitlab_webhook(request, MagicMock(), "wrong-secret")


if __name__ == "__main__":
    unittest.main()
