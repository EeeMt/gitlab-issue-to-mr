"""
Pytest configuration and fixtures for E2E tests.

This module provides shared fixtures for Playwright-based E2E tests.
Tests that need authentication should call login_as_admin() in their setup.
"""

import os
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


@pytest.fixture(scope="session")
def setup_database(postgres_url):
    """
    Initialize the database connection for the test session.

    Creates a connection that will be used to reset state between tests.
    """
    conn = psycopg2.connect(postgres_url)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()

    yield cursor

    cursor.close()
    conn.close()


@pytest.fixture(scope="function")
def reset_database(postgres_url):
    """
    Reset the database to uninitialized state before and after each test.

    This fixture creates its own database connection to avoid cursor state issues.
    """
    conn = psycopg2.connect(postgres_url)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()

    def reset_state():
        try:
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

    reset_state()  # Reset before test

    try:
        yield
    finally:
        reset_state()  # Reset after test
        cursor.close()
        conn.close()


@pytest.fixture(scope="function")
def page(browser, base_url):
    """
    Create a new browser page for testing.

    Each test gets a fresh page with no authentication state.
    Tests that need authentication should call login_as_admin(page) in their setup.
    """
    context = browser.new_context(base_url=base_url)
    page = context.new_page()

    yield page

    context.close()


@pytest.fixture
def logged_in_page(page, reset_database):
    """
    Create a page that is logged in as admin.

    This fixture:
    1. Uses the reset_database fixture to ensure clean state
    2. Logs in via bootstrap or existing admin credentials
    3. Returns the authenticated page

    Use this fixture instead of `page` when tests need authentication.
    """
    _do_login(page)
    return page


def _do_login(page):
    """
    Internal helper to perform login via bootstrap or existing admin.
    """
    page.goto("/bootstrap")
    page.wait_for_load_state("networkidle")

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
        page.wait_for_url("**/dashboard", timeout=15000)
    elif page.locator(".login-form").is_visible(timeout=5000):
        # System already initialized - login with existing admin
        inputs = page.locator(".login-form input")
        inputs.nth(0).fill("test_admin")
        inputs.nth(1).fill("SecurePass123!")
        page.get_by_role("button", name="Login").click()
        page.wait_for_url("**/dashboard", timeout=15000)

    page.wait_for_load_state("networkidle")


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
