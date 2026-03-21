"""
Pytest configuration and fixtures for E2E tests.

This module provides shared fixtures for Playwright-based E2E tests.
"""

import os
import pytest
from typing import Generator

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
            # Optional: Add GPU acceleration args for faster rendering
            # "--enable-accelerated-2d-canvas",
            # "--enable-gpu-rasterization",
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


@pytest.fixture(scope="function")
def authenticated_page(page):
    """
    Provide a page that is pre-authenticated if possible.

    This fixture can be extended to handle session persistence
    or OIDC authentication flows.
    """
    # TODO: Implement authentication if needed
    # For now, just return the page as-is
    return page


@pytest.fixture(scope="function")
def reset_database(postgres_url):
    """
    Reset the database to uninitialized state before test.

    This fixture ensures the system is in a clean state for testing
    bootstrap flow by:
    1. Clearing all users (except potential system reserved users)
    2. Resetting system_bootstrap to uninitialized state
    """
    import psycopg2

    conn = psycopg2.connect(postgres_url)
    conn.autocommit = True
    cursor = conn.cursor()

    try:
        # Reset system_bootstrap to uninitialized state
        cursor.execute("""
            UPDATE system_bootstrap
            SET initialized = FALSE,
                initial_admin_user_id = NULL,
                initialized_at = NULL
            WHERE id = 1
        """)

        # Delete all users to allow fresh bootstrap
        cursor.execute("DELETE FROM users")

        # Reset alembic_version to head of initial migration (017)
        # to ensure clean state
        cursor.execute("""
            UPDATE alembic_version
            SET version_num = '017_add_local_auth_bootstrap'
        """)

        yield

    finally:
        cursor.close()
        conn.close()


@pytest.fixture(scope="session")
def postgres_url() -> str:
    """
    Get the PostgreSQL connection URL for database operations.

    Can be overridden via E2E_POSTGRES_URL environment variable.
    Default: postgresql://gimr:gimr@postgres:5432/gimr
    """
    return os.environ.get(
        "E2E_POSTGRES_URL",
        "postgresql://gimr:gimr@postgres:5432/gimr"
    )


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
