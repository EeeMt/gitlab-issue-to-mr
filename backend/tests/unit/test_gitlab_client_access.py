#!/usr/bin/env python3
"""Unit tests for OAuth project visibility resolution."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import reset_runtime_config, set_runtime_config
from app.core.gitlab_client import (
    get_accessible_projects_for_oauth_token,
    get_gitlab_client,
    reset_gitlab_client,
)


class GitLabClientAccessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_runtime_config()
        reset_gitlab_client()

    def tearDown(self) -> None:
        reset_gitlab_client()
        reset_runtime_config()

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

        set_runtime_config({"gitlab_url": "https://gitlab.example.com"})

        with patch(
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

    def test_get_gitlab_client_recreates_singleton_when_runtime_config_changes(self) -> None:
        created_clients: list[MagicMock] = []

        def build_gitlab(base_url: str, private_token: str):
            client = MagicMock()
            client.base_url = base_url
            client.private_token = private_token
            created_clients.append(client)
            return client

        set_runtime_config({
            "gitlab_url": "https://gitlab-one.example.com",
            "gitlab_bot_token": "token-one",
        })

        with patch("app.core.gitlab_client.gitlab.Gitlab", side_effect=build_gitlab):
            first = get_gitlab_client()
            second = get_gitlab_client()
            self.assertIs(first, second)

            set_runtime_config({
                "gitlab_url": "https://gitlab-two.example.com",
                "gitlab_bot_token": "token-two",
            })
            third = get_gitlab_client()

        self.assertIsNot(first, third)
        self.assertEqual(len(created_clients), 2)
        self.assertEqual(created_clients[0].base_url, "https://gitlab-one.example.com")
        self.assertEqual(created_clients[1].base_url, "https://gitlab-two.example.com")


if __name__ == "__main__":
    unittest.main()
