"""
Pytest configuration and fixtures for E2E tests.

This module provides shared fixtures for Playwright-based E2E tests.
Uses transaction-based state management for reliable test isolation.
"""

import os
import pytest
from typing import Generator

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


@pytest.fixture(scope="function")
def reset_database(postgres_url):
    """
    Reset the database to uninitialized state before test using transaction savepoints.

    This fixture ensures:
    1. Database starts in uninitialized state for each test
    2. State changes are rolled back after test completes
    3. No side effects between tests

    Uses PostgreSQL SAVEPOINT mechanism for efficient state management.
    """
    # Connect to PostgreSQL
    conn = psycopg2.connect(postgres_url)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()

    # Check if system is already uninitialized
    cursor.execute("SELECT initialized FROM system_bootstrap WHERE id = 1")
    row = cursor.fetchone()
    was_uninitialized = row is None or not row[0]

    if not was_uninitialized:
        # Save current state for restoration later
        cursor.execute("SELECT id, username, display_name, email, local_password_hash, platform_role, "
                       "gitlab_user_id, oidc_sub, avatar_url, state, last_login_at, "
                       "created_at, updated_at, platform_role_source, auth_provider "
                       "FROM users")
        saved_users = cursor.fetchall()

        # Reset to uninitialized state
        cursor.execute("""
            UPDATE system_bootstrap
            SET initialized = FALSE,
                initial_admin_user_id = NULL,
                initialized_at = NULL
            WHERE id = 1
        """)
        cursor.execute("DELETE FROM users")

    # Create a savepoint
    cursor.execute("SAVEPOINT e2e_test_sp")

    try:
        yield
    finally:
        # Rollback to savepoint (undoes all changes made during test)
        cursor.execute("ROLLBACK TO SAVEPOINT e2e_test_sp")

        if not was_uninitialized:
            # Restore users
            for user in saved_users:
                cursor.execute("""
                    INSERT INTO users (id, username, display_name, email, local_password_hash, platform_role,
                                      gitlab_user_id, oidc_sub, avatar_url, state, last_login_at,
                                      created_at, updated_at, platform_role_source, auth_provider)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        username = EXCLUDED.username,
                        display_name = EXCLUDED.display_name,
                        email = EXCLUDED.email,
                        local_password_hash = EXCLUDED.local_password_hash,
                        platform_role = EXCLUDED.platform_role,
                        gitlab_user_id = EXCLUDED.gitlab_user_id,
                        oidc_sub = EXCLUDED.oidc_sub,
                        avatar_url = EXCLUDED.avatar_url,
                        state = EXCLUDED.state,
                        last_login_at = EXCLUDED.last_login_at,
                        updated_at = EXCLUDED.updated_at,
                        platform_role_source = EXCLUDED.platform_role_source,
                        auth_provider = EXCLUDED.auth_provider
                """, user)

    cursor.close()
    conn.close()


@pytest.fixture(scope="function")
def clean_database(postgres_url):
    """
    Provide a completely clean database for tests that don't need bootstrap flow.

    This fixture ensures all tables are clean before the test.
    Use this for tests that create their own data.
    """
    conn = psycopg2.connect(postgres_url)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()

    try:
        yield
    finally:
        # Rollback any transaction
        cursor.execute("ROLLBACK")
        cursor.close()
        conn.close()


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
