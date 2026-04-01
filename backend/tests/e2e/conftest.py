"""
Pytest configuration and fixtures for E2E tests.

This module provides shared fixtures for Playwright-based E2E tests.
Tests that need authentication should call login_as_admin() in their setup.
"""

import os
import re
import pytest

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
    Default: postgresql://gimr:gimr@postgres:5432/gimr
    """
    return os.environ.get(
        "E2E_POSTGRES_URL",
        "postgresql://gimr:gimr_password@postgres:5432/gimr"
    )


# Reusable DB reset function
def _reset_db(cursor, clear_sessions=True):
    """
    Reset database to uninitialized state.

    Args:
        cursor: Database cursor
        clear_sessions: If True, delete sessions. If False, keep sessions.
    """
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


@pytest.fixture(scope="function")
def logged_in_page(browser, base_url, db_cursor, reset_database):
    """
    Create a logged-in page for a test.

    Each test gets a fresh authenticated page from a new browser context.
    The reset_database fixture ensures a clean state before login.
    """
    context = browser.new_context(base_url=base_url)
    page = context.new_page()

    _do_login(page)

    yield page

    context.close()


def _do_login(page):
    """
    Internal helper to perform login via bootstrap or existing admin.
    """
    page.goto("/bootstrap")
    page.wait_for_load_state("domcontentloaded")

    # Wait for Vue app to fully render
    page.wait_for_timeout(500)

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
        page.wait_for_function("() => window.location.pathname === '/dashboard'", timeout=15000)
    elif page.locator(".login-card").is_visible(timeout=5000):
        # System already initialized - reveal password login if needed
        login_form = page.locator(".login-form").filter(has=page.locator("input"))
        if login_form.count() == 0 or not login_form.first.is_visible():
            toggle_button = page.locator(".login-card__password-toggle button")
            if toggle_button.count() > 0 and toggle_button.first.is_visible():
                toggle_button.first.click()
                page.wait_for_timeout(300)

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
        page.wait_for_function("() => window.location.pathname === '/dashboard'", timeout=15000)
    else:
        # Check if we're already on dashboard (session exists)
        if "/dashboard" in page.url:
            return
        # Otherwise, wait a bit more and check again
        page.wait_for_timeout(1000)
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
                page.wait_for_function("() => window.location.pathname === '/dashboard'", timeout=15000)

    page.wait_for_load_state("domcontentloaded")


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
        "markers", "manual_task: mark test as a manual task creation test"
    )
    config.addinivalue_line(
        "markers", "create_task: mark test as a create task page test"
    )
    config.addinivalue_line(
        "markers", "task_view: mark test as a task view page test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )


def pytest_report_header(config):
    """
    Add custom header to pytest report.
    """
    return [
        f"Base URL: {os.environ.get('E2E_BASE_URL', 'http://nginx')}",
        f"Backend URL: {os.environ.get('E2E_BACKEND_URL', 'http://backend:8000')}",
        f"GitLab URL: {os.environ.get('E2E_GITLAB_URL', 'http://gitlab:8080')}",
    ]
