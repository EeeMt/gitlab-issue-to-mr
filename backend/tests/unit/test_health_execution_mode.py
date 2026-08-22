"""Health endpoint exposes the harness execution mode (plan §4.8).

The deployment preflight compares the ``harness_execution_mode`` reported by
the Backend and Scheduler /health payloads, so the field must always be
present and reflect effective settings.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_health_reports_harness_execution_mode(client):
    with (
        patch("sqlalchemy.text", MagicMock()),
        patch("app.database.engine") as engine,
        patch("docker.from_env") as from_env,
    ):
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value = None
        engine.connect.return_value = conn
        from_env.return_value.ping.return_value = None

        resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["harness_execution_mode"] in ("dual_canary", "v2_only")


def test_health_mode_reflects_settings_without_dependency_failure(client):
    """The mode is read even when a dependency check fails."""
    with (
        patch("sqlalchemy.text", MagicMock()),
        patch("app.database.engine") as engine,
        patch("docker.from_env") as from_env,
    ):
        engine.connect.side_effect = RuntimeError("db down")
        from_env.return_value.ping.return_value = None

        resp = client.get("/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unhealthy"
    # The mode is still reported so preflight can compare values.
    assert body["harness_execution_mode"] in ("dual_canary", "v2_only")
