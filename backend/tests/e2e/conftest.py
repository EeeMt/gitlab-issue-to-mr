"""
Pytest configuration and fixtures for E2E tests.

This module provides shared fixtures for Playwright-based E2E tests.
Tests that need authentication should call login_as_admin() in their setup.
"""

import hashlib
import os
import re
import pytest
import httpx as _httpx

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


# Configure pytest-playwright
# Note: pytest-playwright auto-registers via entry points, no need to list here


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """
    Configure browser launch arguments.

    Add custom arguments for headless mode and CI environments.
    """
    return {
        **browser_type_launch_args,
        "args": [
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
        ],
    }


@pytest.fixture(scope="session")
def base_url() -> str:
    """
    Get the base URL for the application under test.

    Can be overridden via E2E_BASE_URL environment variable.
    Default: http://nginx (docker-compose service name)
    """
    return os.environ.get("E2E_BASE_URL", "http://nginx")


@pytest.fixture(scope="session")
def backend_url() -> str:
    """
    Get the backend API URL for direct API calls.

    Can be overridden via E2E_BACKEND_URL environment variable.
    Default: http://backend (docker-compose service name)
    """
    return os.environ.get("E2E_BACKEND_URL", "http://backend:8000")


@pytest.fixture(scope="session")
def gitlab_url() -> str:
    """
    Get the GitLab URL for authentication flows.

    Can be overridden via E2E_GITLAB_URL environment variable.
    """
    return os.environ.get("E2E_GITLAB_URL", "http://gitlab:8080")


@pytest.fixture(scope="session")
def postgres_url() -> str:
    """
    Get the PostgreSQL connection URL for database operations.

    Can be overridden via E2E_POSTGRES_URL environment variable.
    Default: postgresql://codify:codify@postgres:5432/codify
    """
    return os.environ.get(
        "E2E_POSTGRES_URL",
        "postgresql://codify:codify_password@postgres:5432/codify"
    )


# Reusable DB reset function
def _hash_password_for_test(password: str, worker_id: str) -> str:
    """
    Generate a PBKDF2-HMAC-SHA256 hash compatible with the backend's verify logic.

    Uses a deterministic salt and a single iteration for speed; the backend
    reads the iteration count and salt from the stored hash string so any
    valid pbkdf2_sha256$<iter>$<salt>$<digest> value works.
    """
    salt = f"test_salt_{worker_id}"
    iterations = 1
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def _reset_db(cursor, clear_sessions=True):
    """
    Reset database state.

    In xdist mode: no-op.  Each test gets a fresh browser context with a new
    session cookie via ``_api_login()``.  Clearing sessions would invalidate
    the module-scoped ``class_page`` cookie used by read-only tests in the
    same file.  The per-worker admin user and system_bootstrap are left
    intact for the same reason.

    In non-xdist mode: performs a full reset (original behaviour).

    Args:
        cursor: Database cursor
        clear_sessions: If True, delete sessions. If False, keep sessions.
    """
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "")
    if worker_id:
        # xdist: no-op — each test creates a fresh browser context/session.
        pass
    else:
        # Non-xdist: full reset (original behavior)
        try:
            if clear_sessions:
                cursor.execute("DELETE FROM user_sessions")
            cursor.execute("DELETE FROM users")
            cursor.execute("""
                UPDATE system_bootstrap
                SET initialized = FALSE,
                    initial_admin_user_id = NULL,
                    initialized_at = NULL
                WHERE id = 1
            """)
        except Exception as e:
            print(f"Reset warning: {e}")


@pytest.fixture(scope="session")
def db_cursor(postgres_url):
    """
    Session-scoped database cursor for efficient DB operations.
    """
    conn = psycopg2.connect(postgres_url)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()

    yield cursor

    cursor.close()
    conn.close()


@pytest.fixture(scope="session")
def worker_admin_setup(db_cursor, backend_url):
    """
    Session-scoped fixture that creates a per-worker admin user when running
    under pytest-xdist.

    Each xdist worker gets its own ``test_admin_<worker_id>`` account inserted
    directly into the database (idempotent ON CONFLICT DO NOTHING).  This
    avoids the cross-worker contention that would arise if all workers shared
    a single user and the ``reset_database`` fixture deleted it.

    In non-xdist mode (``PYTEST_XDIST_WORKER`` unset) this fixture is a no-op
    so existing serial behaviour is unchanged.
    """
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "")
    if not worker_id:
        yield
        return

    password = "SecurePass123!"
    username = f"test_admin_{worker_id}"

    # Ensure the system is initialized. Multiple workers may race here; a 403
    # response simply means another worker already initialized it — that's fine.
    db_cursor.execute("SELECT initialized FROM system_bootstrap WHERE id = 1")
    row = db_cursor.fetchone()
    if not row or not row[0]:
        with _httpx.Client(timeout=15) as c:
            c.post(
                f"{backend_url}/api/auth/local/register",
                json={
                    "username": "test_admin_master",
                    "display_name": "Master Admin",
                    "email": "master@test.example.com",
                    "password": password,
                },
            )
        # 200/201 = we initialized it; 403 = another worker beat us. Both OK.

    # Insert this worker's dedicated admin user (idempotent)
    password_hash = _hash_password_for_test(password, worker_id)
    db_cursor.execute(
        """
        INSERT INTO users (
            username, display_name, email, auth_provider, local_password_hash,
            platform_role, platform_role_source, state, created_at, updated_at
        )
        VALUES (%s, %s, %s, 'local', %s, 'platform_admin', 'bootstrap', 'active', NOW(), NOW())
        ON CONFLICT (username) DO NOTHING
        """,
        (username, f"Test Admin {worker_id}", f"{username}@test.example.com", password_hash),
    )

    yield


@pytest.fixture(scope="function")
def reset_database(db_cursor):
    """
    Reset the database to uninitialized state before and after each test.
    Sessions are cleared to ensure clean auth state for each test.
    """
    _reset_db(db_cursor, clear_sessions=True)  # Reset before test

    try:
        yield
    finally:
        _reset_db(db_cursor, clear_sessions=True)  # Reset after test


def _api_login(backend_url: str, base_url_str: str) -> dict:
    """
    Fast API-based login — skips the browser UI bootstrap flow entirely.

    In xdist mode the system is already initialized and each worker has its
    own ``test_admin_<worker_id>`` account, so we call the login endpoint
    directly with those credentials.

    In non-xdist mode (original behaviour) we attempt to register first
    (succeeds when system is uninitialized after a DB reset) then fall back
    to regular login if the system is already initialized.

    The returned storage_state dict can be passed directly to
    ``browser.new_context(storage_state=...)`` so the browser context starts
    with an authenticated session cookie.
    """
    from urllib.parse import urlparse

    parsed = urlparse(base_url_str)
    cookie_domain = parsed.hostname or "nginx"

    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "")

    with _httpx.Client(timeout=10) as client:
        if worker_id:
            # xdist: system is initialized; use worker-specific credentials
            username = f"test_admin_{worker_id}"
            resp = client.post(
                f"{backend_url}/api/auth/local/login",
                json={"username": username, "password": "SecurePass123!"},
            )
        else:
            # Non-xdist: register if uninitialized, login otherwise
            resp = client.post(
                f"{backend_url}/api/auth/local/register",
                json={
                    "username": "test_admin",
                    "display_name": "Test Admin",
                    "email": "test_admin@example.com",
                    "password": "SecurePass123!",
                },
            )
            if resp.status_code == 403:
                resp = client.post(
                    f"{backend_url}/api/auth/local/login",
                    json={"username": "test_admin", "password": "SecurePass123!"},
                )

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"API login failed: {resp.status_code} {resp.text[:200]}")

    session_token = resp.cookies.get("codify_session")
    if not session_token:
        raise RuntimeError(
            f"No codify_session cookie in API login response. "
            f"Status: {resp.status_code}, Cookies: {dict(resp.cookies)}"
        )

    return {
        "cookies": [
            {
                "name": "codify_session",
                "value": session_token,
                "domain": cookie_domain,
                "path": "/",
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            }
        ],
        "origins": [],
    }


@pytest.fixture(scope="function")
def logged_in_page(request, browser, base_url, backend_url, db_cursor, reset_database, worker_admin_setup):
    """
    Create a logged-in page for a test using fast API-based authentication.

    Instead of driving the browser through the bootstrap/login UI (slow),
    we call the backend auth API directly to obtain a session cookie and
    inject it into a fresh browser context via Playwright's storage_state.
    Each test still gets an isolated context; the DB is reset beforehand by
    the reset_database dependency.

    Video recording is enabled when the E2E_RECORD_VIDEO environment variable
    is set (any non-empty value).  Videos are written to /videos/ inside the
    container (mount deploy/e2e-videos → /videos via docker-compose) and
    renamed to <test_name>_<worker_id>.webm after each test.
    """
    storage_state = _api_login(backend_url, base_url)

    record_video = bool(os.environ.get("E2E_RECORD_VIDEO"))
    context_kwargs: dict = dict(base_url=base_url, storage_state=storage_state)
    if record_video:
        os.makedirs("/videos", exist_ok=True)
        context_kwargs["record_video_dir"] = "/videos"
        context_kwargs["record_video_size"] = {"width": 1280, "height": 720}

    context = browser.new_context(**context_kwargs)
    page = context.new_page()

    yield page

    if record_video and page.video:
        # Capture path BEFORE close; after close the file is fully written.
        video_tmp_path = page.video.path()
        context.close()
        test_name = re.sub(r"[^\w\-]", "_", request.node.name)
        worker_id = os.environ.get("PYTEST_XDIST_WORKER", "main")
        new_path = f"/videos/{test_name}_{worker_id}.webm"
        try:
            os.rename(video_tmp_path, new_path)
        except OSError:
            pass  # Keep UUID name if rename fails (e.g. cross-device move)
    else:
        context.close()


@pytest.fixture(scope="module")
def class_page(browser, base_url, backend_url, worker_admin_setup):
    """
    Module-scoped authenticated page for read-only E2E tests.

    Creates one browser context per test module (file) with a pre-authenticated
    session. Reused across ALL test classes and functions in the module to
    eliminate per-test login and context creation overhead.

    Tests must call page.goto(url) themselves. No DB reset is performed
    between tests — suitable only for read-only tests that don't create
    or modify application data, and that don't leave persistent browser
    state (e.g. changed viewport size) without resetting it.

    Use this instead of ``logged_in_page`` + ``reset_database`` for tests
    that only navigate and assert UI structure.
    """
    storage_state = _api_login(backend_url, base_url)
    context = browser.new_context(base_url=base_url, storage_state=storage_state)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture(scope="function")
def fresh_page(browser, base_url, backend_url, worker_admin_setup):
    """
    Function-scoped authenticated page WITHOUT database reset.

    Creates a fresh browser context with API-based login for each test,
    but does NOT call reset_database. Use for destructive tests (e.g. logout)
    that must not invalidate the module-scoped ``class_page`` session shared
    by other tests in the same file.
    """
    storage_state = _api_login(backend_url, base_url)
    context = browser.new_context(base_url=base_url, storage_state=storage_state)
    page = context.new_page()
    yield page
    context.close()


def _do_login(page):
    """
    Internal helper to perform login via bootstrap or existing admin.
    """
    page.goto("/bootstrap")
    page.wait_for_load_state("domcontentloaded")

    if page.locator(".bootstrap-card").is_visible(timeout=5000):
        # System not initialized - create admin via bootstrap
        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("test_admin")
        inputs.nth(1).fill("Test Admin")
        inputs.nth(2).fill("test_admin@example.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("SecurePass123!")
        password_inputs.nth(1).fill("SecurePass123!")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_function("() => window.location.pathname === '/dashboard'", timeout=10000)
    elif page.locator(".login-card").is_visible(timeout=5000):
        # System already initialized - reveal password login if needed
        login_form = page.locator(".login-form").filter(has=page.locator("input"))
        if login_form.count() == 0 or not login_form.first.is_visible():
            toggle_button = page.locator(".login-card__password-toggle button")
            if toggle_button.count() > 0 and toggle_button.first.is_visible():
                toggle_button.first.click()

        inputs = page.locator(".login-form input")
        if inputs.count() >= 2:
            inputs.nth(0).fill("test_admin")
            inputs.nth(1).fill("SecurePass123!")
        else:
            username_input = page.locator("input[autocomplete='username']").first
            password_input = page.locator("input[autocomplete='current-password']").first
            username_input.fill("test_admin")
            password_input.fill("SecurePass123!")

        submit_button = page.get_by_role("button", name=re.compile(r"Sign In|Login", re.I)).first
        submit_button.click()
        page.wait_for_function("() => window.location.pathname === '/dashboard'", timeout=10000)
    else:
        # Check if we're already on dashboard (session exists)
        if "/dashboard" in page.url:
            return
        # Otherwise, wait a bit more and check again
        page.wait_for_timeout(500)
        if "/dashboard" not in page.url:
            # Final check - reload and try bootstrap flow
            page.reload()
            page.wait_for_load_state("domcontentloaded")
            if page.locator(".bootstrap-card").is_visible(timeout=5000):
                inputs = page.locator(".bootstrap-form input")
                inputs.nth(0).fill("test_admin")
                inputs.nth(1).fill("Test Admin")
                inputs.nth(2).fill("test_admin@example.com")
                password_inputs = page.locator("input[type='password']")
                password_inputs.nth(0).fill("SecurePass123!")
                password_inputs.nth(1).fill("SecurePass123!")
                page.get_by_role("button", name="Create Admin").click()
                page.wait_for_function("() => window.location.pathname === '/dashboard'", timeout=10000)


def pytest_configure(config):
    """
    Pytest hook called after command line options have been parsed.

    Register custom markers here.
    """
    config.addinivalue_line(
        "markers", "auth: mark test as an authentication flow test"
    )
    config.addinivalue_line(
        "markers", "bootstrap: mark test as a bootstrap page test"
    )
    config.addinivalue_line(
        "markers", "dashboard: mark test as a dashboard test"
    )
    config.addinivalue_line(
        "markers", "navigation: mark test as a navigation test"
    )
    config.addinivalue_line(
        "markers", "task_details: mark test as a task detail view test"
    )
    config.addinivalue_line(
        "markers", "issue_list: mark test as an issue list page test"
    )
    config.addinivalue_line(
        "markers", "create_issue: mark test as a create issue page test"
    )
    config.addinivalue_line(
        "markers", "issue_view: mark test as an issue view page test"
    )
    config.addinivalue_line(
        "markers", "task_view: mark test as a task view page test"
    )
    config.addinivalue_line(
        "markers", "task_list: mark test as a task list page test"
    )
    config.addinivalue_line(
        "markers", "schedule_overview: mark test as a schedule overview test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "serial: tests that require serial execution (modify shared DB state)"
    )


def pytest_collection_modifyitems(config, items):
    """Assign xdist_group to serial-marked tests.

    Serial-marked tests are assigned xdist_group("serial") so they all run
    on the same worker sequentially when using --dist=loadgroup.

    Note: Bootstrap tests handle their own skip via module-level
    ``pytest.skip(allow_module_level=True)`` when ``PYTEST_XDIST_WORKER``
    is set, which is more reliable than hook-based deselection.
    """
    for item in items:
        if item.get_closest_marker("serial"):
            item.add_marker(pytest.mark.xdist_group("serial"))


def pytest_report_header(config):
    """
    Add custom header to pytest report.
    """
    return [
        f"Base URL: {os.environ.get('E2E_BASE_URL', 'http://nginx')}",
        f"Backend URL: {os.environ.get('E2E_BACKEND_URL', 'http://backend:8000')}",
        f"GitLab URL: {os.environ.get('E2E_GITLAB_URL', 'http://gitlab:8080')}",
    ]


def api_get_first_project(backend_url: str, cookies: dict) -> dict:
    """Get the first available project. Skips test if none available."""
    with _httpx.Client(base_url=backend_url, timeout=15, cookies=cookies) as client:
        resp = client.get("/api/projects")
        if resp.status_code != 200:
            pytest.skip(f"Cannot fetch projects: {resp.status_code}")
        projects = resp.json()
        if not projects:
            pytest.skip("No GitLab projects available")
        return projects[0]


def api_create_issue(backend_url: str, cookies: dict, project_id: int, title: str = "E2E Test Issue", description: str = None) -> dict:
    """Create a test issue via the API and return the response JSON."""
    if description is None:
        description = f"E2E test issue: {title}"
    with _httpx.Client(base_url=backend_url, timeout=15, cookies=cookies) as client:
        resp = client.post(
            "/api/issues",
            json={
                "title": title,
                "description": description,
                "project_id": project_id,
            },
        )
        assert resp.status_code in (200, 201), f"Failed to create issue: {resp.status_code} {resp.text}"
        return resp.json()


def api_create_task(backend_url: str, cookies: dict, issue_id: int, prompt: str = "E2E test task", priority: int = 2, scheduled_datetime: str = None) -> dict:
    """Create a test task under an issue via the API and return the response JSON."""
    from datetime import datetime, timezone, timedelta
    payload = {
        "issue_id": issue_id,
        "user_prompt": prompt,
        "priority": priority,
    }
    if scheduled_datetime is None:
        # Schedule far in the future so it stays pending
        future = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
        payload["scheduled_datetime"] = future
    else:
        payload["scheduled_datetime"] = scheduled_datetime

    with _httpx.Client(base_url=backend_url, timeout=15, cookies=cookies) as client:
        resp = client.post("/api/tasks", json=payload)
        assert resp.status_code in (200, 201), f"Failed to create task: {resp.status_code} {resp.text}"
        return resp.json()


def _get_cookies(page) -> dict:
    """Extract cookies as dict from a Playwright page context."""
    return {c["name"]: c["value"] for c in page.context.cookies()}
