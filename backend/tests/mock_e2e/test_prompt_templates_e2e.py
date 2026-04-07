"""Mock E2E tests for the Prompt Templates CRUD API.

Tests the full HTTP request/response cycle through the FastAPI app using a
real in-memory SQLite database.  Only authentication dependencies are
mocked — the actual SQL queries, model validation, config persistence, and
HTTP routing all execute for real.

Endpoints under test:
- GET    /api/prompt-templates              — list all templates
- POST   /api/prompt-templates              — create template
- GET    /api/prompt-templates/{id}         — get single template
- PUT    /api/prompt-templates/{id}         — update template
- DELETE /api/prompt-templates/{id}         — delete template
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.pool import StaticPool

# Ensure a usable encryption key is available for secret config persistence
os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "test-templates-e2e-key-32chars!")

from app.database import get_db
from app.dependencies.auth import (
    get_optional_current_user,
    require_admin_user,
    require_authenticated_user,
)
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access_scope,
)
from app.main import app
from app.models import Base

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "/api/prompt-templates"

VALID_TEMPLATE = {
    "name": "Code Review",
    "content": "Please review the code in {{project_name}}.",
    "variable_tips": {"project_name": "The name of the project to review"},
    "is_active": True,
}

MINIMAL_TEMPLATE = {
    "name": "Quick Fix",
    "content": "Fix the bug.",
}


# ---------------------------------------------------------------------------
# Fixtures  (follows test_mattermost_e2e.py pattern exactly)
# ---------------------------------------------------------------------------


@pytest.fixture()
async def _test_engine():
    """In-memory SQLite async engine with all tables created."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _register_pg_compat(dbapi_conn, connection_record):
        dbapi_conn.create_function("pg_advisory_xact_lock", 1, lambda _key: None)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def session_factory(_test_engine):
    return async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture()
async def db_session(session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture()
def _mock_admin_user():
    user = MagicMock()
    user.id = 1
    user.username = "testadmin"
    user.gitlab_user_id = 100
    user.platform_role = "platform_admin"
    return user


@pytest.fixture()
async def client(session_factory, _mock_admin_user):
    """httpx.AsyncClient wired to the FastAPI app with auth overrides."""

    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    access_scope = ProjectAccessScope(
        is_unrestricted=True, accessible_projects=[]
    )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_optional_current_user] = lambda: None
    app.dependency_overrides[require_authenticated_user] = lambda: None
    app.dependency_overrides[require_admin_user] = lambda: _mock_admin_user
    app.dependency_overrides[require_project_access_scope] = lambda: access_scope

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _isolate_runtime_config():
    """Save / restore module-level _runtime_config between tests."""
    from app.config import _runtime_config

    saved = dict(_runtime_config)
    yield
    _runtime_config.clear()
    _runtime_config.update(saved)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_template(client: AsyncClient, payload: dict | None = None) -> dict:
    """POST helper — returns the JSON body of a successfully created template."""
    resp = await client.post(BASE_URL, json=payload or VALID_TEMPLATE)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/prompt-templates — List templates
# ═══════════════════════════════════════════════════════════════════════════


class TestListTemplates:
    """GET /api/prompt-templates"""

    async def test_empty_db_returns_empty_list(self, client):
        """Fresh database returns an empty JSON array."""
        resp = await client.get(BASE_URL)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_returns_created_templates(self, client):
        """After creating a template it appears in the list."""
        await _create_template(client)
        resp = await client.get(BASE_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == VALID_TEMPLATE["name"]

    async def test_multiple_templates_correct_count(self, client):
        """Creating several templates returns the correct count."""
        await _create_template(client, {"name": "Tmpl A", "content": "Content A"})
        await _create_template(client, {"name": "Tmpl B", "content": "Content B"})
        await _create_template(client, {"name": "Tmpl C", "content": "Content C"})

        resp = await client.get(BASE_URL)
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    async def test_ordered_by_created_at_desc(self, client):
        """Templates are returned newest-first (created_at DESC)."""
        await _create_template(client, {"name": "First", "content": "1"})
        await _create_template(client, {"name": "Second", "content": "2"})
        await _create_template(client, {"name": "Third", "content": "3"})

        data = (await client.get(BASE_URL)).json()
        names = [t["name"] for t in data]
        # newest first → Third, Second, First
        assert names == ["Third", "Second", "First"]

    async def test_response_contains_all_fields(self, client):
        """Each template in the list has all expected fields."""
        created = await _create_template(client)
        data = (await client.get(BASE_URL)).json()
        item = data[0]
        for field in ("id", "name", "content", "variable_tips", "is_active",
                       "created_at", "updated_at"):
            assert field in item, f"Missing field: {field}"
        assert item["id"] == created["id"]


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/prompt-templates — Create template
# ═══════════════════════════════════════════════════════════════════════════


class TestCreateTemplate:
    """POST /api/prompt-templates"""

    async def test_create_with_all_fields(self, client):
        """Full payload creates template and returns 201 with correct data."""
        resp = await client.post(BASE_URL, json=VALID_TEMPLATE)
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == VALID_TEMPLATE["name"]
        assert body["content"] == VALID_TEMPLATE["content"]
        assert body["variable_tips"] == VALID_TEMPLATE["variable_tips"]
        assert body["is_active"] is True

    async def test_create_minimal_template_applies_defaults(self, client):
        """Payload with only name + content gets default is_active=True."""
        resp = await client.post(BASE_URL, json=MINIMAL_TEMPLATE)
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == MINIMAL_TEMPLATE["name"]
        assert body["content"] == MINIMAL_TEMPLATE["content"]
        assert body["is_active"] is True
        assert body["variable_tips"] is None

    async def test_create_with_variable_tips(self, client):
        """variable_tips dict is stored and returned correctly."""
        tips = {"project": "Project name", "branch": "Branch to review"}
        payload = {"name": "Tips Test", "content": "Review {{project}}", "variable_tips": tips}
        body = await _create_template(client, payload)
        assert body["variable_tips"] == tips

    async def test_create_inactive_template(self, client):
        """is_active=false is persisted correctly."""
        payload = {**MINIMAL_TEMPLATE, "is_active": False}
        body = await _create_template(client, payload)
        assert body["is_active"] is False

    async def test_create_returns_timestamps(self, client):
        """Created template has created_at and updated_at timestamps."""
        body = await _create_template(client)
        assert body["created_at"] is not None
        assert body["updated_at"] is not None

    async def test_create_returns_unique_ids(self, client):
        """Each created template gets a unique auto-incremented ID."""
        t1 = await _create_template(client, {"name": "T1", "content": "C1"})
        t2 = await _create_template(client, {"name": "T2", "content": "C2"})
        assert t1["id"] != t2["id"]

    async def test_create_missing_name_returns_422(self, client):
        """Missing required 'name' field yields 422 Unprocessable Entity."""
        resp = await client.post(BASE_URL, json={"content": "No name"})
        assert resp.status_code == 422

    async def test_create_missing_content_returns_422(self, client):
        """Missing required 'content' field yields 422 Unprocessable Entity."""
        resp = await client.post(BASE_URL, json={"name": "No content"})
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/prompt-templates/{id} — Get single template
# ═══════════════════════════════════════════════════════════════════════════


class TestGetTemplate:
    """GET /api/prompt-templates/{id}"""

    async def test_get_existing_template(self, client):
        """Fetching a known template ID returns 200 with full data."""
        created = await _create_template(client)
        tid = created["id"]

        resp = await client.get(f"{BASE_URL}/{tid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == tid
        assert body["name"] == VALID_TEMPLATE["name"]
        assert body["content"] == VALID_TEMPLATE["content"]
        assert body["variable_tips"] == VALID_TEMPLATE["variable_tips"]
        assert body["is_active"] is True

    async def test_get_nonexistent_template_returns_404(self, client):
        """Fetching a non-existent ID returns 404."""
        resp = await client.get(f"{BASE_URL}/99999")
        assert resp.status_code == 404

    async def test_get_after_update_returns_updated_data(self, client):
        """After updating, GET returns the new values."""
        created = await _create_template(client)
        tid = created["id"]

        await client.put(f"{BASE_URL}/{tid}", json={"name": "Updated Name"})

        resp = await client.get(f"{BASE_URL}/{tid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    async def test_get_returns_all_fields(self, client):
        """GET by ID response includes every expected field."""
        created = await _create_template(client)
        resp = await client.get(f"{BASE_URL}/{created['id']}")
        body = resp.json()
        for field in ("id", "name", "content", "variable_tips", "is_active",
                       "created_at", "updated_at"):
            assert field in body, f"Missing field: {field}"


# ═══════════════════════════════════════════════════════════════════════════
# PUT /api/prompt-templates/{id} — Update template
# ═══════════════════════════════════════════════════════════════════════════


class TestUpdateTemplate:
    """PUT /api/prompt-templates/{id}"""

    async def test_update_name_only(self, client):
        """Updating only name leaves content and is_active unchanged."""
        created = await _create_template(client)
        tid = created["id"]

        resp = await client.put(f"{BASE_URL}/{tid}", json={"name": "New Name"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "New Name"
        assert body["content"] == VALID_TEMPLATE["content"]
        assert body["is_active"] == VALID_TEMPLATE["is_active"]

    async def test_update_content_only(self, client):
        """Updating only content leaves name unchanged."""
        created = await _create_template(client)
        tid = created["id"]

        resp = await client.put(f"{BASE_URL}/{tid}", json={"content": "Brand new content"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["content"] == "Brand new content"
        assert body["name"] == VALID_TEMPLATE["name"]

    async def test_update_variable_tips(self, client):
        """Variable tips can be replaced entirely."""
        created = await _create_template(client)
        tid = created["id"]

        new_tips = {"foo": "bar", "baz": "qux"}
        resp = await client.put(f"{BASE_URL}/{tid}", json={"variable_tips": new_tips})
        assert resp.status_code == 200
        assert resp.json()["variable_tips"] == new_tips

    async def test_update_is_active_toggle(self, client):
        """is_active can be toggled from True to False and back."""
        created = await _create_template(client)
        tid = created["id"]
        assert created["is_active"] is True

        resp1 = await client.put(f"{BASE_URL}/{tid}", json={"is_active": False})
        assert resp1.status_code == 200
        assert resp1.json()["is_active"] is False

        resp2 = await client.put(f"{BASE_URL}/{tid}", json={"is_active": True})
        assert resp2.status_code == 200
        assert resp2.json()["is_active"] is True

    async def test_update_nonexistent_template_returns_404(self, client):
        """PUT on a non-existent ID returns 404."""
        resp = await client.put(f"{BASE_URL}/99999", json={"name": "Ghost"})
        assert resp.status_code == 404

    async def test_partial_update_preserves_other_fields(self, client):
        """Sending a single field does not null out other fields."""
        tips = {"key": "value"}
        payload = {**VALID_TEMPLATE, "variable_tips": tips, "is_active": False}
        created = await _create_template(client, payload)
        tid = created["id"]

        resp = await client.put(f"{BASE_URL}/{tid}", json={"name": "Only Name Changed"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Only Name Changed"
        assert body["content"] == VALID_TEMPLATE["content"]
        assert body["variable_tips"] == tips
        assert body["is_active"] is False

    async def test_update_all_fields_at_once(self, client):
        """All fields can be updated in a single PUT."""
        created = await _create_template(client)
        tid = created["id"]

        update_payload = {
            "name": "All New",
            "content": "Completely rewritten.",
            "variable_tips": {"new_var": "new tip"},
            "is_active": False,
        }
        resp = await client.put(f"{BASE_URL}/{tid}", json=update_payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "All New"
        assert body["content"] == "Completely rewritten."
        assert body["variable_tips"] == {"new_var": "new tip"}
        assert body["is_active"] is False


# ═══════════════════════════════════════════════════════════════════════════
# DELETE /api/prompt-templates/{id} — Delete template
# ═══════════════════════════════════════════════════════════════════════════


class TestDeleteTemplate:
    """DELETE /api/prompt-templates/{id}"""

    async def test_delete_existing_template(self, client):
        """Deleting an existing template returns success and removes it."""
        created = await _create_template(client)
        tid = created["id"]

        resp = await client.delete(f"{BASE_URL}/{tid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

        # Confirm it's gone
        get_resp = await client.get(f"{BASE_URL}/{tid}")
        assert get_resp.status_code == 404

    async def test_delete_nonexistent_template_returns_404(self, client):
        """Deleting a non-existent ID returns 404."""
        resp = await client.delete(f"{BASE_URL}/99999")
        assert resp.status_code == 404

    async def test_delete_removes_from_list(self, client):
        """A deleted template no longer appears in the list endpoint."""
        t1 = await _create_template(client, {"name": "Keep", "content": "Stay"})
        t2 = await _create_template(client, {"name": "Remove", "content": "Gone"})

        await client.delete(f"{BASE_URL}/{t2['id']}")

        data = (await client.get(BASE_URL)).json()
        ids = [t["id"] for t in data]
        assert t1["id"] in ids
        assert t2["id"] not in ids


# ═══════════════════════════════════════════════════════════════════════════
# Full CRUD lifecycle
# ═══════════════════════════════════════════════════════════════════════════


class TestFullCRUDLifecycle:
    """End-to-end CRUD round-trips."""

    async def test_create_read_update_read_delete_read(self, client):
        """Full lifecycle: create → get → update → get → delete → get(404)."""
        # Create
        created = await _create_template(client)
        tid = created["id"]

        # Read
        body = (await client.get(f"{BASE_URL}/{tid}")).json()
        assert body["name"] == VALID_TEMPLATE["name"]

        # Update
        resp = await client.put(
            f"{BASE_URL}/{tid}",
            json={"name": "Updated", "content": "New content"},
        )
        assert resp.status_code == 200

        # Read after update
        body = (await client.get(f"{BASE_URL}/{tid}")).json()
        assert body["name"] == "Updated"
        assert body["content"] == "New content"
        # original variable_tips preserved since we didn't update it
        assert body["variable_tips"] == VALID_TEMPLATE["variable_tips"]

        # Delete
        del_resp = await client.delete(f"{BASE_URL}/{tid}")
        assert del_resp.status_code == 200

        # Read after delete
        get_resp = await client.get(f"{BASE_URL}/{tid}")
        assert get_resp.status_code == 404

    async def test_create_multiple_delete_one_list_remaining(self, client):
        """Create three, delete one, list shows the remaining two."""
        t1 = await _create_template(client, {"name": "Alpha", "content": "A"})
        t2 = await _create_template(client, {"name": "Beta", "content": "B"})
        t3 = await _create_template(client, {"name": "Gamma", "content": "C"})

        # Delete the middle one
        await client.delete(f"{BASE_URL}/{t2['id']}")

        data = (await client.get(BASE_URL)).json()
        assert len(data) == 2
        names = {t["name"] for t in data}
        assert names == {"Alpha", "Gamma"}

    async def test_double_delete_returns_404(self, client):
        """Deleting the same template twice returns 404 on the second call."""
        created = await _create_template(client)
        tid = created["id"]

        resp1 = await client.delete(f"{BASE_URL}/{tid}")
        assert resp1.status_code == 200

        resp2 = await client.delete(f"{BASE_URL}/{tid}")
        assert resp2.status_code == 404
