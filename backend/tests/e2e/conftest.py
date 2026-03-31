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
    Reset the database to uninitialized state before test, then restore original state after test.

    This fixture ensures the system is in a clean state for testing bootstrap flow by:
    1. Saving current database state (system_bootstrap, users, alembic_version)
    2. Resetting system_bootstrap to uninitialized state and clearing users
    3. Running test
    4. Restoring original database state
    """
    import psycopg2

    conn = psycopg2.connect(postgres_url)
    conn.autocommit = True
    cursor = conn.cursor()

    # Step 1: Save current state BEFORE reset
    saved_state = {}

    cursor.execute("SELECT version_num FROM alembic_version")
    saved_state['alembic_version'] = cursor.fetchone()[0]

    cursor.execute("SELECT initialized, initial_admin_user_id, initialized_at FROM system_bootstrap WHERE id = 1")
    row = cursor.fetchone()
    saved_state['system_bootstrap'] = {
        'initialized': row[0],
        'initial_admin_user_id': row[1],
        'initialized_at': row[2]
    }

    cursor.execute("""
        SELECT id, username, display_name, email, local_password_hash, platform_role,
               gitlab_user_id, oidc_sub, avatar_url, state, last_login_at,
               created_at, updated_at, platform_role_source, auth_provider
        FROM users
    """)
    saved_state['users'] = []
    for row in cursor.fetchall():
        saved_state['users'].append({
            'id': row[0],
            'username': row[1],
            'display_name': row[2],
            'email': row[3],
            'local_password_hash': row[4],
            'platform_role': row[5],
            'gitlab_user_id': row[6],
            'oidc_sub': row[7],
            'avatar_url': row[8],
            'state': row[9],
            'last_login_at': row[10],
            'created_at': row[11],
            'updated_at': row[12],
            'platform_role_source': row[13],
            'auth_provider': row[14],
        })

    # Step 2: Reset database for clean test state
    cursor.execute("""
        UPDATE system_bootstrap
        SET initialized = FALSE,
            initial_admin_user_id = NULL,
            initialized_at = NULL
        WHERE id = 1
    """)
    cursor.execute("DELETE FROM users")

    try:
        yield
    finally:
        # Step 3: Restore original state after test
        # Delete any users created during test first
        cursor.execute("DELETE FROM users")

        # Restore alembic_version
        cursor.execute(f"UPDATE alembic_version SET version_num = '{saved_state['alembic_version']}'")

        # Restore users
        for user in saved_state['users']:
            cursor.execute("""
                INSERT INTO users (id, username, display_name, email, local_password_hash, platform_role,
                                  gitlab_user_id, oidc_sub, avatar_url, state, last_login_at,
                                  created_at, updated_at, platform_role_source, auth_provider)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                user['id'],
                user['username'],
                user['display_name'],
                user['email'],
                user['local_password_hash'],
                user['platform_role'],
                user['gitlab_user_id'],
                user['oidc_sub'],
                user['avatar_url'],
                user['state'],
                user['last_login_at'],
                user['created_at'],
                user['updated_at'],
                user['platform_role_source'],
                user['auth_provider']
            ))

        # Restore system_bootstrap state
        cursor.execute("""
            UPDATE system_bootstrap
            SET initialized = %s,
                initial_admin_user_id = %s,
                initialized_at = %s
            WHERE id = 1
        """, (
            saved_state['system_bootstrap']['initialized'],
            saved_state['system_bootstrap']['initial_admin_user_id'],
            saved_state['system_bootstrap']['initialized_at']
        ))

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
