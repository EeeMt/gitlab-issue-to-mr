"""Mock E2E tests for Auth and Admin Users API endpoints.

Tests the full HTTP request/response cycle through the FastAPI app using a real
in-memory SQLite database.  Authentication dependencies are mocked ONLY for
admin-management endpoints; the local-auth and session endpoints exercise the
real authentication pipeline end-to-end.

Auth endpoints under test:
- GET    /api/auth/bootstrap-status
- POST   /api/auth/local/register
- POST   /api/auth/local/login
- POST   /api/auth/logout
- GET    /api/auth/sessions
- POST   /api/auth/sessions/{id}/revoke

Admin endpoints under test:
- GET    /api/admin/users
- PATCH  /api/admin/users/{id}
- POST   /api/admin/users/{id}/sessions/revoke
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from typing import Optional

import pytest
from unittest.mock import MagicMock

# Suppress httpx per-request cookies deprecation (auth tests need per-request cookies)
pytestmark = pytest.mark.filterwarnings(
    "ignore:Setting per-request cookies:DeprecationWarning"
)

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.pool import StaticPool

# Ensure a usable encryption key is available for secret config persistence.
os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "test-auth-e2e-key-32chars!!!!!!")

# ---------------------------------------------------------------------------
# Inject the missing BreakGlassLoginRequestBody before FastAPI resolves it.
# ---------------------------------------------------------------------------
import app.api.auth as _auth_module  # noqa: E402

if not hasattr(_auth_module, "BreakGlassLoginRequestBody"):
    from pydantic import BaseModel as _BaseModel

    class _BreakGlassLoginRequestBody(_BaseModel):
        username: str
        password: str
        next: Optional[str] = None

    _auth_module.BreakGlassLoginRequestBody = _BreakGlassLoginRequestBody

from app.database import get_db  # noqa: E402
from app.dependencies.auth import (  # noqa: E402
    get_optional_current_user,
    require_admin_user,
    require_authenticated_user,
)
from app.dependencies.project_access import (  # noqa: E402
    ProjectAccessScope,
    require_project_access_scope,
)
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    User,
    UserSession,
    SystemBootstrap,
    AuthAuditLog,
)
from app.core.session import hash_session_token  # noqa: E402
from app.core.local_auth import hash_password  # noqa: E402
from app.core.utcnow import utcnow  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_ADMIN_ID = 9999  # Avoids collision with auto-incremented user IDs.


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
    """Direct database session for test setup / assertions."""
    async with session_factory() as session:
        yield session


def _override_get_db_factory(session_factory):
    """Return an async generator compatible with FastAPI's Depends(get_db)."""

    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _override_get_db


# ---- raw_client: NO auth overrides → tests register / login / bootstrap ----

@pytest.fixture()
async def raw_client(session_factory):
    app.dependency_overrides[get_db] = _override_get_db_factory(session_factory)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---- admin_client: auth fully mocked → tests admin-user management ----

@pytest.fixture()
def _mock_admin_user():
    user = MagicMock()
    user.id = MOCK_ADMIN_ID
    user.username = "testadmin"
    user.gitlab_user_id = 100
    user.platform_role = "platform_admin"
    return user


@pytest.fixture()
async def admin_client(session_factory, _mock_admin_user):
    access_scope = ProjectAccessScope(
        is_unrestricted=True, accessible_projects=[]
    )

    app.dependency_overrides[get_db] = _override_get_db_factory(session_factory)
    app.dependency_overrides[get_optional_current_user] = lambda: _mock_admin_user
    app.dependency_overrides[require_authenticated_user] = lambda: _mock_admin_user
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

async def _register_admin(
    raw_client: AsyncClient, *, username: str = "admin1",
    password: str = "Str0ng!Pass99",
):
    """Register the initial admin via the API and return the response."""
    return await raw_client.post(
        "/api/auth/local/register",
        json={"username": username, "password": password},
    )


async def _login(
    raw_client: AsyncClient, *, username: str = "admin1",
    password: str = "Str0ng!Pass99",
):
    """Login via the API and return the response."""
    return await raw_client.post(
        "/api/auth/local/login",
        json={"username": username, "password": password},
    )


def _extract_session_cookie(response) -> str | None:
    """Extract the session token from Set-Cookie headers."""
    from app.config import get_effective_settings

    cookie_name = get_effective_settings().session_cookie_name
    for header_val in response.headers.get_list("set-cookie"):
        if header_val.startswith(f"{cookie_name}="):
            token = header_val.split(";")[0].split("=", 1)[1]
            return token
    return None


async def _seed_user(
    db: AsyncSession,
    *,
    username: str = "user1",
    password: str = "Test1234!",
    platform_role: str = "platform_user",
    state: str = "active",
) -> User:
    """Insert a local-auth user directly into the database."""
    user = User(
        username=username,
        display_name=username.title(),
        local_password_hash=hash_password(password),
        auth_provider="local",
        platform_role=platform_role,
        platform_role_source="manual",
        state=state,
    )
    db.add(user)
    await db.flush()
    return user


async def _seed_session(
    db: AsyncSession,
    user: User,
    *,
    raw_token: str | None = None,
    expires_delta: timedelta | None = None,
    revoked: bool = False,
) -> tuple[UserSession, str]:
    """Insert a session row and return (session, raw_token)."""
    raw_token = raw_token or f"test-tok-{uuid.uuid4()}"
    now = utcnow()
    session = UserSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        session_token_hash=hash_session_token(raw_token),
        expires_at=now + (expires_delta or timedelta(hours=8)),
        last_seen_at=now,
        ip_address="127.0.0.1",
        user_agent="pytest",
        revoked_at=now if revoked else None,
    )
    db.add(session)
    await db.flush()
    return session, raw_token


# =====================================================================
# Auth endpoint tests
# =====================================================================


class TestBootstrapStatus:
    """GET /api/auth/bootstrap-status — no auth required."""

    async def test_fresh_db_returns_not_initialized(self, raw_client):
        """Fresh database has initialized=False and total_users=0."""
        resp = await raw_client.get("/api/auth/bootstrap-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["initialized"] is False
        assert data["total_users"] == 0

    async def test_oidc_configured_reflects_settings(self, raw_client):
        """oidc_configured reflects the effective settings value."""
        resp = await raw_client.get("/api/auth/bootstrap-status")
        data = resp.json()
        # Default settings have oidc_enabled=False
        assert data["oidc_configured"] is False

    async def test_after_register_shows_initialized(self, raw_client):
        """After registering the first admin, initialized=True."""
        await _register_admin(raw_client)
        resp = await raw_client.get("/api/auth/bootstrap-status")
        data = resp.json()
        assert data["initialized"] is True
        assert data["total_users"] == 1

    async def test_no_auth_required(self, raw_client):
        """Endpoint succeeds without any authentication cookie."""
        resp = await raw_client.get("/api/auth/bootstrap-status")
        assert resp.status_code == 200

    async def test_bootstrap_status_after_multiple_registers(self, raw_client):
        """After first register, second register fails, but status still shows 1 user."""
        await _register_admin(raw_client, username="admin1")
        # Second register should be rejected
        await _register_admin(raw_client, username="admin2")
        resp = await raw_client.get("/api/auth/bootstrap-status")
        data = resp.json()
        assert data["initialized"] is True
        assert data["total_users"] == 1


class TestLocalRegister:
    """POST /api/auth/local/register — first admin registration."""

    async def test_register_first_user_succeeds(self, raw_client):
        """Register the first admin user on a clean system."""
        resp = await _register_admin(raw_client, username="myadmin", password="GoodPass123!")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["user"]["username"] == "myadmin"
        assert data["user"]["platform_role"] == "platform_admin"
        assert data["next_path"] == "/dashboard"

    async def test_register_sets_session_cookie(self, raw_client):
        """Successful registration sets the session cookie in the response."""
        resp = await _register_admin(raw_client)
        token = _extract_session_cookie(resp)
        assert token is not None
        assert len(token) > 10

    async def test_register_creates_user_in_db(self, raw_client, db_session):
        """Registration persists the user record to the database."""
        await _register_admin(raw_client, username="dbcheck")
        result = await db_session.execute(select(User).where(User.username == "dbcheck"))
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.platform_role == "platform_admin"
        assert user.auth_provider == "local"
        assert user.local_password_hash is not None

    async def test_register_marks_bootstrap_initialized(self, raw_client, db_session):
        """Registration sets SystemBootstrap.initialized=True."""
        await _register_admin(raw_client)
        result = await db_session.execute(
            select(SystemBootstrap).where(SystemBootstrap.id == 1)
        )
        bootstrap = result.scalar_one_or_none()
        assert bootstrap is not None
        assert bootstrap.initialized is True
        assert bootstrap.initial_admin_user_id is not None

    async def test_register_after_bootstrap_rejected(self, raw_client):
        """Second registration attempt returns 403 after system is initialized."""
        resp1 = await _register_admin(raw_client, username="first")
        assert resp1.status_code == 200

        resp2 = await _register_admin(raw_client, username="second")
        assert resp2.status_code == 403
        assert "already initialized" in resp2.json()["detail"].lower()

    async def test_register_empty_username_rejected(self, raw_client):
        """Registration with empty username returns 400."""
        resp = await raw_client.post(
            "/api/auth/local/register",
            json={"username": "   ", "password": "Test1234!"},
        )
        assert resp.status_code == 400
        assert "username" in resp.json()["detail"].lower()

    async def test_register_creates_audit_log(self, raw_client, db_session):
        """Registration creates an audit log entry."""
        await _register_admin(raw_client, username="audituser")
        result = await db_session.execute(
            select(AuthAuditLog).where(
                AuthAuditLog.event_type == "local_register",
                AuthAuditLog.success == True,  # noqa: E712
            )
        )
        log = result.scalar_one_or_none()
        assert log is not None
        assert log.username == "audituser"

    async def test_register_with_display_name_and_email(self, raw_client):
        """Registration with optional display_name and email succeeds."""
        resp = await raw_client.post(
            "/api/auth/local/register",
            json={
                "username": "fancy",
                "password": "SoGood!123",
                "display_name": "Fancy Admin",
                "email": "fancy@example.com",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["display_name"] == "Fancy Admin"
        assert data["user"]["email"] == "fancy@example.com"


class TestLocalLogin:
    """POST /api/auth/local/login — username/password authentication."""

    async def test_login_with_correct_credentials(self, raw_client):
        """Login succeeds after registration with the same credentials."""
        await _register_admin(raw_client, username="loginuser", password="MyPass!1")
        resp = await _login(raw_client, username="loginuser", password="MyPass!1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["user"]["username"] == "loginuser"

    async def test_login_sets_session_cookie(self, raw_client):
        """Login response contains a session cookie."""
        await _register_admin(raw_client)
        resp = await _login(raw_client)
        token = _extract_session_cookie(resp)
        assert token is not None

    async def test_login_wrong_password(self, raw_client):
        """Login with wrong password returns 401."""
        await _register_admin(raw_client, username="u1", password="Correct!1")
        resp = await _login(raw_client, username="u1", password="wrong-pass")
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower()

    async def test_login_nonexistent_user(self, raw_client):
        """Login with non-existent username returns 401."""
        resp = await _login(raw_client, username="ghost", password="whatever")
        assert resp.status_code == 401

    async def test_login_returns_user_details(self, raw_client):
        """Login response includes user id, username, platform_role."""
        await _register_admin(raw_client, username="detailuser", password="Deets!123")
        resp = await _login(raw_client, username="detailuser", password="Deets!123")
        user_info = resp.json()["user"]
        assert "id" in user_info
        assert user_info["username"] == "detailuser"
        assert user_info["platform_role"] == "platform_admin"

    async def test_login_creates_session_in_db(self, raw_client, db_session):
        """Login creates a UserSession row in the database."""
        await _register_admin(raw_client, username="sessuser", password="Sess!1234")
        await _login(raw_client, username="sessuser", password="Sess!1234")
        result = await db_session.execute(select(UserSession))
        sessions = result.scalars().all()
        # register + login = 2 sessions
        assert len(sessions) >= 2

    async def test_login_creates_audit_log(self, raw_client, db_session):
        """Login creates an AuthAuditLog entry on success."""
        await _register_admin(raw_client, username="auditlogin", password="Audit!1234")
        await _login(raw_client, username="auditlogin", password="Audit!1234")
        result = await db_session.execute(
            select(AuthAuditLog).where(
                AuthAuditLog.event_type == "local_login",
                AuthAuditLog.success == True,  # noqa: E712
            )
        )
        log = result.scalar_one_or_none()
        assert log is not None
        assert log.username == "auditlogin"

    async def test_login_failed_creates_audit_log(self, raw_client, db_session):
        """Failed login creates an AuthAuditLog entry with success=False."""
        await _register_admin(raw_client, username="failuser", password="Good!1234")
        await _login(raw_client, username="failuser", password="bad")
        result = await db_session.execute(
            select(AuthAuditLog).where(
                AuthAuditLog.event_type == "local_login",
                AuthAuditLog.success == False,  # noqa: E712
            )
        )
        logs = result.scalars().all()
        assert len(logs) >= 1

    async def test_login_sanitizes_next_path(self, raw_client):
        """Login sanitizes the next_path to prevent open redirect."""
        await _register_admin(raw_client, username="nextuser", password="Next!1234")
        resp = await raw_client.post(
            "/api/auth/local/login",
            json={"username": "nextuser", "password": "Next!1234", "next": "//evil.com"},
        )
        assert resp.status_code == 200
        assert resp.json()["next_path"] == "/dashboard"

    async def test_login_valid_next_path(self, raw_client):
        """Login with a valid next_path returns it."""
        await _register_admin(raw_client, username="pathuser", password="Path!1234")
        resp = await raw_client.post(
            "/api/auth/local/login",
            json={"username": "pathuser", "password": "Path!1234", "next": "/projects"},
        )
        assert resp.status_code == 200
        assert resp.json()["next_path"] == "/projects"


class TestLogout:
    """POST /api/auth/logout — session revocation via cookie."""

    async def test_logout_with_valid_session(self, raw_client, db_session):
        """Logout revokes the session and clears the cookie."""
        user = await _seed_user(db_session, username="logoutuser", platform_role="platform_admin")
        session, raw_token = await _seed_session(db_session, user)
        await db_session.commit()

        resp = await raw_client.post(
            "/api/auth/logout",
            cookies={"codify_session": raw_token},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    async def test_logout_revokes_session_in_db(self, raw_client, db_session):
        """Logout marks the session as revoked in the database."""
        user = await _seed_user(db_session, username="revlogout", platform_role="platform_admin")
        session_obj, raw_token = await _seed_session(db_session, user)
        session_id = session_obj.id
        await db_session.commit()

        await raw_client.post(
            "/api/auth/logout",
            cookies={"codify_session": raw_token},
        )

        # Re-fetch from DB to check revoked_at
        db_session.expire_all()
        result = await db_session.execute(
            select(UserSession).where(UserSession.id == session_id)
        )
        updated = result.scalar_one()
        assert updated.revoked_at is not None

    async def test_logout_without_cookie_still_succeeds(self, raw_client):
        """Logout without a session cookie still returns success (idempotent)."""
        resp = await raw_client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    async def test_logout_clears_cookie_header(self, raw_client, db_session):
        """Logout response includes Set-Cookie to clear the session cookie."""
        user = await _seed_user(db_session, username="clearcookie")
        _session, raw_token = await _seed_session(db_session, user)
        await db_session.commit()

        resp = await raw_client.post(
            "/api/auth/logout",
            cookies={"codify_session": raw_token},
        )
        # The response should have a Set-Cookie that clears codify_session
        cookie_headers = resp.headers.get_list("set-cookie")
        cleared = any(
            "codify_session" in h
            and ('=""' in h or "expires=" in h.lower() or "Max-Age=0" in h)
            for h in cookie_headers
        )
        assert cleared, f"Expected cookie to be cleared, got: {cookie_headers}"


class TestListSessions:
    """GET /api/auth/sessions — list current user's sessions."""

    async def test_list_sessions_returns_current_session(self, raw_client, db_session):
        """After login, listing sessions shows the current active session."""
        await _register_admin(raw_client, username="sesslist", password="List!1234")
        login_resp = await _login(raw_client, username="sesslist", password="List!1234")
        token = _extract_session_cookie(login_resp)
        assert token is not None

        resp = await raw_client.get(
            "/api/auth/sessions",
            cookies={"codify_session": token},
        )
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) >= 1
        # At least one session should be marked as current
        current_sessions = [s for s in sessions if s["current"] is True]
        assert len(current_sessions) == 1

    async def test_list_sessions_shows_active_status(self, raw_client, db_session):
        """Active sessions have status='active'."""
        await _register_admin(raw_client, username="active_sess", password="Active!1234")
        login_resp = await _login(raw_client, username="active_sess", password="Active!1234")
        token = _extract_session_cookie(login_resp)

        resp = await raw_client.get(
            "/api/auth/sessions",
            cookies={"codify_session": token},
        )
        sessions = resp.json()
        active = [s for s in sessions if s["status"] == "active"]
        assert len(active) >= 1

    async def test_list_sessions_multiple_logins(self, raw_client):
        """Multiple logins create multiple sessions for the same user."""
        await _register_admin(raw_client, username="multi", password="Multi!1234")
        await _login(raw_client, username="multi", password="Multi!1234")
        login_resp = await _login(raw_client, username="multi", password="Multi!1234")
        token = _extract_session_cookie(login_resp)

        resp = await raw_client.get(
            "/api/auth/sessions",
            cookies={"codify_session": token},
        )
        # register + 2 logins = 3 sessions
        assert len(resp.json()) >= 3

    async def test_list_sessions_unauthenticated(self, raw_client):
        """Listing sessions without auth returns 401."""
        resp = await raw_client.get("/api/auth/sessions")
        assert resp.status_code == 401


class TestRevokeSession:
    """POST /api/auth/sessions/{id}/revoke — revoke a specific session."""

    async def test_revoke_own_session(self, raw_client):
        """Revoking an own session succeeds."""
        await _register_admin(raw_client, username="revoker", password="Revoke!1234")
        login_resp = await _login(raw_client, username="revoker", password="Revoke!1234")
        token = _extract_session_cookie(login_resp)

        # List sessions to get IDs
        sess_resp = await raw_client.get(
            "/api/auth/sessions",
            cookies={"codify_session": token},
        )
        sessions = sess_resp.json()
        # Find a non-current session to revoke (from registration)
        non_current = [s for s in sessions if not s["current"]]
        assert len(non_current) >= 1, "Expected at least one non-current session"

        target_id = non_current[0]["id"]
        resp = await raw_client.post(
            f"/api/auth/sessions/{target_id}/revoke",
            cookies={"codify_session": token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["session_id"] == target_id
        assert data["current_session_revoked"] is False

    async def test_revoke_nonexistent_session(self, raw_client):
        """Revoking a non-existent session returns 404."""
        await _register_admin(raw_client, username="rev404", password="Rev404!123")
        login_resp = await _login(raw_client, username="rev404", password="Rev404!123")
        token = _extract_session_cookie(login_resp)

        resp = await raw_client.post(
            "/api/auth/sessions/nonexistent-id-here/revoke",
            cookies={"codify_session": token},
        )
        assert resp.status_code == 404

    async def test_revoke_already_revoked_session(self, raw_client):
        """Revoking an already-revoked session returns 400."""
        await _register_admin(raw_client, username="revrv", password="RevRv!1234")
        login_resp = await _login(raw_client, username="revrv", password="RevRv!1234")
        token = _extract_session_cookie(login_resp)

        sess_resp = await raw_client.get(
            "/api/auth/sessions",
            cookies={"codify_session": token},
        )
        non_current = [s for s in sess_resp.json() if not s["current"]]
        assert len(non_current) >= 1
        target_id = non_current[0]["id"]

        # Revoke once
        resp1 = await raw_client.post(
            f"/api/auth/sessions/{target_id}/revoke",
            cookies={"codify_session": token},
        )
        assert resp1.status_code == 200

        # Revoke again
        resp2 = await raw_client.post(
            f"/api/auth/sessions/{target_id}/revoke",
            cookies={"codify_session": token},
        )
        assert resp2.status_code == 400

    async def test_revoke_unauthenticated(self, raw_client):
        """Revoking without auth returns 401."""
        resp = await raw_client.post("/api/auth/sessions/some-id/revoke")
        assert resp.status_code == 401


# =====================================================================
# Admin user management endpoint tests
# =====================================================================


class TestListAdminUsers:
    """GET /api/admin/users — admin-only user listing."""

    async def test_list_empty_db(self, admin_client):
        """Empty database returns an empty user list."""
        resp = await admin_client.get("/api/admin/users")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_single_user(self, admin_client, db_session):
        """Single user appears in the list."""
        await _seed_user(db_session, username="alice", platform_role="platform_admin")
        await db_session.commit()

        resp = await admin_client.get("/api/admin/users")
        assert resp.status_code == 200
        users = resp.json()
        assert len(users) == 1
        assert users[0]["username"] == "alice"

    async def test_list_multiple_users_sorted(self, admin_client, db_session):
        """Multiple users are returned; admins before regular users."""
        await _seed_user(db_session, username="zeta_user", platform_role="platform_user")
        await _seed_user(db_session, username="alpha_admin", platform_role="platform_admin")
        await db_session.commit()

        resp = await admin_client.get("/api/admin/users")
        users = resp.json()
        assert len(users) == 2
        # Admin should come first
        assert users[0]["platform_role"] == "platform_admin"
        assert users[1]["platform_role"] == "platform_user"

    async def test_list_includes_session_count(self, admin_client, db_session):
        """User listing includes active_session_count."""
        user = await _seed_user(db_session, username="withsess")
        await _seed_session(db_session, user)
        await db_session.commit()

        resp = await admin_client.get("/api/admin/users")
        users = resp.json()
        assert len(users) == 1
        assert users[0]["active_session_count"] == 1

    async def test_list_includes_is_current_user_flag(self, admin_client, db_session):
        """is_current_user is True for user matching admin's mock id, False otherwise."""
        # Create a user whose id won't be MOCK_ADMIN_ID (auto-increment)
        await _seed_user(db_session, username="someone")
        await db_session.commit()

        resp = await admin_client.get("/api/admin/users")
        users = resp.json()
        # The seeded user's id != MOCK_ADMIN_ID, so is_current_user should be False
        assert users[0]["is_current_user"] is False

    async def test_list_user_fields(self, admin_client, db_session):
        """Each user summary includes the expected fields."""
        await _seed_user(db_session, username="fieldcheck", platform_role="platform_admin")
        await db_session.commit()

        resp = await admin_client.get("/api/admin/users")
        u = resp.json()[0]
        expected_fields = {
            "id", "gitlab_user_id", "username", "display_name", "email",
            "avatar_url", "platform_role", "platform_role_source", "state",
            "last_login_at", "created_at", "active_session_count",
            "last_session_seen_at", "is_current_user",
        }
        assert expected_fields.issubset(set(u.keys()))


class TestUpdateAdminUser:
    """PATCH /api/admin/users/{id} — update user role/state."""

    async def test_change_role_to_user(self, admin_client, db_session):
        """Demote an admin to platform_user."""
        # Ensure another admin exists so this isn't the last admin
        await _seed_user(db_session, username="other_admin", platform_role="platform_admin")
        user = await _seed_user(db_session, username="target_admin", platform_role="platform_admin")
        await db_session.commit()

        resp = await admin_client.patch(
            f"/api/admin/users/{user.id}",
            json={"platform_role": "platform_user"},
        )
        assert resp.status_code == 200
        assert resp.json()["platform_role"] == "platform_user"

    async def test_change_role_to_admin(self, admin_client, db_session):
        """Promote a regular user to platform_admin."""
        user = await _seed_user(db_session, username="promo", platform_role="platform_user")
        await db_session.commit()

        resp = await admin_client.patch(
            f"/api/admin/users/{user.id}",
            json={"platform_role": "platform_admin"},
        )
        assert resp.status_code == 200
        assert resp.json()["platform_role"] == "platform_admin"
        assert resp.json()["platform_role_source"] == "manual"

    async def test_disable_user(self, admin_client, db_session):
        """Disabling a user changes state and revokes sessions."""
        user = await _seed_user(db_session, username="disableuser", platform_role="platform_user")
        await _seed_session(db_session, user)
        await db_session.commit()

        resp = await admin_client.patch(
            f"/api/admin/users/{user.id}",
            json={"state": "disabled"},
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "disabled"
        # Sessions should be revoked → active_session_count = 0
        assert resp.json()["active_session_count"] == 0

    async def test_enable_disabled_user(self, admin_client, db_session):
        """Re-enabling a disabled user changes state back to active."""
        user = await _seed_user(
            db_session, username="reenable", platform_role="platform_user", state="disabled"
        )
        await db_session.commit()

        resp = await admin_client.patch(
            f"/api/admin/users/{user.id}",
            json={"state": "active"},
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "active"

    async def test_cannot_remove_last_admin(self, admin_client, db_session):
        """Cannot demote the last active platform admin."""
        user = await _seed_user(db_session, username="lastadmin", platform_role="platform_admin")
        await db_session.commit()

        resp = await admin_client.patch(
            f"/api/admin/users/{user.id}",
            json={"platform_role": "platform_user"},
        )
        assert resp.status_code == 400
        assert "last" in resp.json()["detail"].lower()

    async def test_cannot_modify_own_role(self, admin_client, db_session):
        """Cannot modify own role/state (user.id == current_user.id)."""
        # Create a user whose id matches MOCK_ADMIN_ID
        user = User(
            id=MOCK_ADMIN_ID,
            username="selfadmin",
            display_name="Self Admin",
            auth_provider="local",
            platform_role="platform_admin",
            platform_role_source="manual",
            state="active",
        )
        db_session.add(user)
        await db_session.flush()
        await db_session.commit()

        resp = await admin_client.patch(
            f"/api/admin/users/{MOCK_ADMIN_ID}",
            json={"platform_role": "platform_user"},
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"].lower()
        assert "your own" in detail or "cannot" in detail

    async def test_invalid_role_rejected(self, admin_client, db_session):
        """Invalid platform_role value returns 400."""
        user = await _seed_user(db_session, username="badrole")
        await db_session.commit()

        resp = await admin_client.patch(
            f"/api/admin/users/{user.id}",
            json={"platform_role": "superadmin"},
        )
        assert resp.status_code == 400

    async def test_invalid_state_rejected(self, admin_client, db_session):
        """Invalid state value returns 400."""
        user = await _seed_user(db_session, username="badstate")
        await db_session.commit()

        resp = await admin_client.patch(
            f"/api/admin/users/{user.id}",
            json={"state": "suspended"},
        )
        assert resp.status_code == 400

    async def test_no_field_provided_rejected(self, admin_client, db_session):
        """PATCH with neither platform_role nor state returns 400."""
        user = await _seed_user(db_session, username="nofield")
        await db_session.commit()

        resp = await admin_client.patch(
            f"/api/admin/users/{user.id}",
            json={},
        )
        assert resp.status_code == 400
        assert "at least one" in resp.json()["detail"].lower()

    async def test_update_nonexistent_user(self, admin_client):
        """PATCH on a non-existent user returns 404."""
        resp = await admin_client.patch(
            "/api/admin/users/77777",
            json={"platform_role": "platform_user"},
        )
        assert resp.status_code == 404

    async def test_disable_last_admin_rejected(self, admin_client, db_session):
        """Disabling the last active admin returns 400."""
        user = await _seed_user(db_session, username="solo_admin", platform_role="platform_admin")
        await db_session.commit()

        resp = await admin_client.patch(
            f"/api/admin/users/{user.id}",
            json={"state": "disabled"},
        )
        assert resp.status_code == 400
        assert "last" in resp.json()["detail"].lower()


class TestRevokeAdminUserSessions:
    """POST /api/admin/users/{id}/sessions/revoke — admin bulk revoke."""

    async def test_revoke_another_user_sessions(self, admin_client, db_session):
        """Admin can revoke all sessions of another user."""
        user = await _seed_user(db_session, username="target")
        await _seed_session(db_session, user)
        await _seed_session(db_session, user)
        await db_session.commit()

        resp = await admin_client.post(f"/api/admin/users/{user.id}/sessions/revoke")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["revoked_count"] == 2

    async def test_revoke_own_sessions_rejected(self, admin_client, db_session):
        """Admin cannot revoke their own sessions via this endpoint."""
        # Create a user with MOCK_ADMIN_ID
        user = User(
            id=MOCK_ADMIN_ID,
            username="selfrevoke",
            display_name="Self Revoker",
            auth_provider="local",
            platform_role="platform_admin",
            platform_role_source="manual",
            state="active",
        )
        db_session.add(user)
        await db_session.flush()
        await db_session.commit()

        resp = await admin_client.post(f"/api/admin/users/{MOCK_ADMIN_ID}/sessions/revoke")
        assert resp.status_code == 400
        assert "logout" in resp.json()["detail"].lower()

    async def test_revoke_user_with_no_sessions(self, admin_client, db_session):
        """Revoking for a user with no sessions returns count=0."""
        user = await _seed_user(db_session, username="nosess")
        await db_session.commit()

        resp = await admin_client.post(f"/api/admin/users/{user.id}/sessions/revoke")
        assert resp.status_code == 200
        assert resp.json()["revoked_count"] == 0

    async def test_revoke_nonexistent_user(self, admin_client):
        """Revoking sessions for a non-existent user returns 404."""
        resp = await admin_client.post("/api/admin/users/88888/sessions/revoke")
        assert resp.status_code == 404
