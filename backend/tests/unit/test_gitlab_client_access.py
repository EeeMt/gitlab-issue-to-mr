#!/usr/bin/env python3
"""Unit tests for OAuth project visibility resolution."""

import os
import sys
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.gitlab_client import get_accessible_projects_for_oauth_token


class GitLabClientAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_accessible_projects_include_membership_public_and_internal(self) -> None:
        original_async_client = httpx.AsyncClient
        responses = {
            frozenset({
                ("membership", "true"),
                ("simple", "true"),
                ("per_page", "100"),
                ("page", "1"),
                ("order_by", "id"),
                ("sort", "asc"),
            }): [
                {"id": 2, "name": "private-proj", "path_with_namespace": "team/private-proj"},
                {"id": 3, "name": "shared-proj", "path_with_namespace": "team/shared-proj"},
            ],
            frozenset({
                ("visibility", "public"),
                ("simple", "true"),
                ("per_page", "100"),
                ("page", "1"),
                ("order_by", "id"),
                ("sort", "asc"),
            }): [
                {"id": 1, "name": "public-proj", "path_with_namespace": "oss/public-proj"},
                {"id": 3, "name": "shared-proj", "path_with_namespace": "team/shared-proj"},
            ],
            frozenset({
                ("visibility", "internal"),
                ("simple", "true"),
                ("per_page", "100"),
                ("page", "1"),
                ("order_by", "id"),
                ("sort", "asc"),
            }): [
                {"id": 4, "name": "internal-proj", "path_with_namespace": "corp/internal-proj"},
                {"id": 3, "name": "shared-proj", "path_with_namespace": "team/shared-proj"},
            ],
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            key = frozenset((k, v) for k, v in request.url.params.multi_items())
            payload = responses[key]
            return httpx.Response(200, json=payload, headers={"X-Next-Page": ""})

        transport = httpx.MockTransport(handler)

        with patch("app.core.gitlab_client.settings.gitlab_url", "https://gitlab.example.com"), patch(
            "app.core.gitlab_client.httpx.AsyncClient",
            side_effect=lambda *args, **kwargs: original_async_client(
                transport=transport,
                timeout=kwargs.get("timeout"),
            ),
        ):
            projects = await get_accessible_projects_for_oauth_token("token-123")

        self.assertEqual(
            projects,
            [
                {"id": 2, "name": "private-proj", "path_with_namespace": "team/private-proj"},
                {"id": 3, "name": "shared-proj", "path_with_namespace": "team/shared-proj"},
                {"id": 1, "name": "public-proj", "path_with_namespace": "oss/public-proj"},
                {"id": 4, "name": "internal-proj", "path_with_namespace": "corp/internal-proj"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
