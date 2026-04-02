"""
Config Tabs E2E Tests

Tests for the Configuration page tabs including:
- Page load and tabs container rendering
- Runtime settings tab: Save/Revert buttons
- GitLab settings tab: Save, Test connection, Invalidate cache buttons
- Auth settings tab: Save, Test OIDC buttons
- Maintenance tab: Reload, Reset buttons
- Worker tab: Save button
"""

import pytest
from playwright.sync_api import Page, expect


def _wait_for_config_tab(page: Page):
    """Wait for the config tabs container to be rendered."""
    page.wait_for_selector(".config-tabs", timeout=10000)


@pytest.mark.config_tabs
class TestConfigPageLoad:
    """Tests for the config page basic structure."""

    def test_config_page_loads(self, logged_in_page: Page, reset_database):
        """Test that the config page loads and the tabs container is visible."""
        logged_in_page.goto("/config")
        _wait_for_config_tab(logged_in_page)
        expect(logged_in_page.locator(".config-tabs")).to_be_visible()

    def test_config_page_hero_is_visible(self, logged_in_page: Page, reset_database):
        """Test that the config page hero/header is rendered."""
        logged_in_page.goto("/config")
        logged_in_page.wait_for_selector(".config-page__hero")
        expect(logged_in_page.locator(".config-page__hero")).to_be_visible()

    def test_config_tabs_container_visible(self, logged_in_page: Page, reset_database):
        """Test that the tabs container is present on the config page."""
        logged_in_page.goto("/config?tab=runtime")
        _wait_for_config_tab(logged_in_page)
        expect(logged_in_page.locator(".config-tabs")).to_be_visible()


@pytest.mark.config_tabs
class TestConfigRuntimeTab:
    """Tests for the Runtime settings tab."""

    def test_runtime_tab_loads(self, logged_in_page: Page, reset_database):
        """Test that navigating to the runtime tab renders the form."""
        logged_in_page.goto("/config?tab=runtime")
        _wait_for_config_tab(logged_in_page)
        # Config form cards should appear
        expect(logged_in_page.locator(".config-form-card").first).to_be_visible()

    def test_runtime_tab_has_save_button(self, logged_in_page: Page, reset_database):
        """Test that the runtime tab has a Save changes button."""
        logged_in_page.goto("/config?tab=runtime")
        _wait_for_config_tab(logged_in_page)
        save_button = logged_in_page.get_by_role("button", name="Save changes").first
        expect(save_button).to_be_visible()

    def test_runtime_tab_has_revert_button(self, logged_in_page: Page, reset_database):
        """Test that the runtime tab has a Revert changes button."""
        logged_in_page.goto("/config?tab=runtime")
        _wait_for_config_tab(logged_in_page)
        revert_button = logged_in_page.get_by_role("button", name="Revert changes").first
        expect(revert_button).to_be_visible()

    def test_runtime_tab_has_form_inputs(self, logged_in_page: Page, reset_database):
        """Test that the runtime tab form contains input fields."""
        logged_in_page.goto("/config?tab=runtime")
        _wait_for_config_tab(logged_in_page)
        expect(logged_in_page.locator(".config-section-form").first).to_be_visible()


@pytest.mark.config_tabs
class TestConfigGitLabTab:
    """Tests for the GitLab settings tab."""

    def test_gitlab_tab_loads(self, logged_in_page: Page, reset_database):
        """Test that navigating to the gitlab tab renders the form."""
        logged_in_page.goto("/config?tab=gitlab")
        _wait_for_config_tab(logged_in_page)
        expect(logged_in_page.locator(".config-form-card").first).to_be_visible()

    def test_gitlab_tab_has_save_button(self, logged_in_page: Page, reset_database):
        """Test that the GitLab tab has a Save changes button."""
        logged_in_page.goto("/config?tab=gitlab")
        _wait_for_config_tab(logged_in_page)
        save_button = logged_in_page.get_by_role("button", name="Save changes").first
        expect(save_button).to_be_visible()

    def test_gitlab_tab_has_test_connection_button(self, logged_in_page: Page, reset_database):
        """Test that the GitLab tab has a Test GitLab connection button."""
        logged_in_page.goto("/config?tab=gitlab")
        _wait_for_config_tab(logged_in_page)
        test_button = logged_in_page.get_by_role("button", name="Test GitLab connection")
        expect(test_button).to_be_visible()

    def test_gitlab_tab_has_invalidate_cache_button(self, logged_in_page: Page, reset_database):
        """Test that the GitLab tab has an Invalidate project cache button."""
        logged_in_page.goto("/config?tab=gitlab")
        _wait_for_config_tab(logged_in_page)
        cache_button = logged_in_page.get_by_role("button", name="Invalidate project cache")
        expect(cache_button).to_be_visible()

    def test_gitlab_tab_has_revert_button(self, logged_in_page: Page, reset_database):
        """Test that the GitLab tab has a Revert changes button."""
        logged_in_page.goto("/config?tab=gitlab")
        _wait_for_config_tab(logged_in_page)
        revert_button = logged_in_page.get_by_role("button", name="Revert changes").first
        expect(revert_button).to_be_visible()


@pytest.mark.config_tabs
class TestConfigAuthTab:
    """Tests for the Authentication settings tab."""

    def test_auth_tab_loads(self, logged_in_page: Page, reset_database):
        """Test that navigating to the auth tab renders the form."""
        logged_in_page.goto("/config?tab=auth")
        _wait_for_config_tab(logged_in_page)
        expect(logged_in_page.locator(".config-form-card").first).to_be_visible()

    def test_auth_tab_has_save_button(self, logged_in_page: Page, reset_database):
        """Test that the auth tab has a Save changes button."""
        logged_in_page.goto("/config?tab=auth")
        _wait_for_config_tab(logged_in_page)
        save_button = logged_in_page.get_by_role("button", name="Save changes").first
        expect(save_button).to_be_visible()

    def test_auth_tab_has_test_oidc_button(self, logged_in_page: Page, reset_database):
        """Test that the auth tab has a Test OIDC connection button."""
        logged_in_page.goto("/config?tab=auth")
        _wait_for_config_tab(logged_in_page)
        test_oidc_button = logged_in_page.get_by_role("button", name="Test OIDC connection")
        expect(test_oidc_button).to_be_visible()

    def test_auth_tab_has_revert_button(self, logged_in_page: Page, reset_database):
        """Test that the auth tab has a Revert changes button."""
        logged_in_page.goto("/config?tab=auth")
        _wait_for_config_tab(logged_in_page)
        revert_button = logged_in_page.get_by_role("button", name="Revert changes").first
        expect(revert_button).to_be_visible()

    def test_auth_tab_has_form_inputs(self, logged_in_page: Page, reset_database):
        """Test that the auth tab form contains OIDC configuration fields."""
        logged_in_page.goto("/config?tab=auth")
        _wait_for_config_tab(logged_in_page)
        expect(logged_in_page.locator("#oidc-settings")).to_be_visible()


@pytest.mark.config_tabs
class TestConfigMaintenanceTab:
    """Tests for the Maintenance settings tab."""

    def test_maintenance_tab_loads(self, logged_in_page: Page, reset_database):
        """Test that navigating to the maintenance tab renders the panel."""
        logged_in_page.goto("/config?tab=maintenance")
        _wait_for_config_tab(logged_in_page)
        expect(logged_in_page.locator("#config-actions")).to_be_visible()

    def test_maintenance_tab_has_reload_button(self, logged_in_page: Page, reset_database):
        """Test that the maintenance tab has a Reload button."""
        logged_in_page.goto("/config?tab=maintenance")
        _wait_for_config_tab(logged_in_page)
        reload_button = logged_in_page.get_by_role("button", name="Reload")
        expect(reload_button).to_be_visible()

    def test_maintenance_tab_has_reset_button(self, logged_in_page: Page, reset_database):
        """Test that the maintenance tab has a Reset to env/defaults button."""
        logged_in_page.goto("/config?tab=maintenance")
        _wait_for_config_tab(logged_in_page)
        reset_button = logged_in_page.get_by_role("button", name="Reset to env/defaults")
        expect(reset_button).to_be_visible()


@pytest.mark.config_tabs
class TestConfigWorkerTab:
    """Tests for the Worker settings tab."""

    def test_worker_tab_loads(self, logged_in_page: Page, reset_database):
        """Test that navigating to the worker tab renders the form."""
        logged_in_page.goto("/config?tab=worker")
        _wait_for_config_tab(logged_in_page)
        expect(logged_in_page.locator(".config-form-card").first).to_be_visible()

    def test_worker_tab_has_save_button(self, logged_in_page: Page, reset_database):
        """Test that the worker tab has a Save button for AI provider settings."""
        logged_in_page.goto("/config?tab=worker")
        _wait_for_config_tab(logged_in_page)
        save_button = logged_in_page.get_by_role("button", name="Save changes").first
        expect(save_button).to_be_visible()

    def test_worker_tab_has_form_section(self, logged_in_page: Page, reset_database):
        """Test that the worker tab displays a configuration form section."""
        logged_in_page.goto("/config?tab=worker")
        _wait_for_config_tab(logged_in_page)
        expect(logged_in_page.locator(".config-section-form").first).to_be_visible()
