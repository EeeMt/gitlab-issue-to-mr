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

import re

import pytest
from playwright.sync_api import Page, expect


def _wait_for_config_tab(page: Page):
    """Wait for the config tabs container to be rendered."""
    page.wait_for_selector(".config-tabs", timeout=10000)


@pytest.mark.config_tabs
class TestConfigPageLoad:
    """Tests for the config page basic structure."""

    def test_config_page_loads(self, class_page: Page):
        """Test that the config page loads and the tabs container is visible."""
        class_page.goto("/config")
        _wait_for_config_tab(class_page)
        expect(class_page.locator(".config-tabs")).to_be_visible()

    def test_config_page_hero_is_visible(self, class_page: Page):
        """Test that the config page hero/header is rendered."""
        class_page.goto("/config")
        class_page.wait_for_selector(".config-page__hero")
        expect(class_page.locator(".config-page__hero")).to_be_visible()

    def test_config_tabs_container_visible(self, class_page: Page):
        """Test that the tabs container is present on the config page."""
        class_page.goto("/config?tab=runtime")
        _wait_for_config_tab(class_page)
        expect(class_page.locator(".config-tabs")).to_be_visible()


@pytest.mark.config_tabs
class TestConfigRuntimeTab:
    """Tests for the Runtime settings tab."""

    def test_runtime_tab_loads(self, class_page: Page):
        """Test that navigating to the runtime tab renders the form."""
        class_page.goto("/config?tab=runtime")
        _wait_for_config_tab(class_page)
        # Config form cards should appear
        expect(class_page.locator(".config-form-card").first).to_be_visible()

    def test_runtime_tab_has_save_button(self, class_page: Page):
        """Test that the runtime tab has a Save changes button."""
        class_page.goto("/config?tab=runtime")
        _wait_for_config_tab(class_page)
        save_button = class_page.get_by_role("button", name="Save changes").first
        expect(save_button).to_be_visible()

    def test_runtime_tab_has_revert_button(self, class_page: Page):
        """Test that the runtime tab has a Revert changes button."""
        class_page.goto("/config?tab=runtime")
        _wait_for_config_tab(class_page)
        revert_button = class_page.get_by_role("button", name="Revert changes").first
        expect(revert_button).to_be_visible()

    def test_runtime_tab_has_form_inputs(self, class_page: Page):
        """Test that the runtime tab form contains input fields."""
        class_page.goto("/config?tab=runtime")
        _wait_for_config_tab(class_page)
        expect(class_page.locator(".config-section-form").first).to_be_visible()


@pytest.mark.config_tabs
class TestConfigGitLabTab:
    """Tests for the GitLab settings tab."""

    def test_gitlab_tab_loads(self, class_page: Page):
        """Test that navigating to the gitlab tab renders the form."""
        class_page.goto("/config?tab=gitlab")
        _wait_for_config_tab(class_page)
        expect(class_page.locator(".config-form-card").first).to_be_visible()

    def test_gitlab_tab_has_save_button(self, class_page: Page):
        """Test that the GitLab tab has a Save changes button."""
        class_page.goto("/config?tab=gitlab")
        _wait_for_config_tab(class_page)
        save_button = class_page.get_by_role("button", name="Save changes").first
        expect(save_button).to_be_visible()

    def test_gitlab_tab_has_test_connection_button(self, class_page: Page):
        """Test that the GitLab tab has a Test GitLab connection button."""
        class_page.goto("/config?tab=gitlab")
        _wait_for_config_tab(class_page)
        test_button = class_page.get_by_role("button", name="Test GitLab connection")
        expect(test_button).to_be_visible()

    def test_gitlab_tab_has_invalidate_cache_button(self, class_page: Page):
        """Test that the GitLab tab has an Invalidate project cache button."""
        class_page.goto("/config?tab=gitlab")
        _wait_for_config_tab(class_page)
        cache_button = class_page.get_by_role("button", name="Invalidate project cache")
        expect(cache_button).to_be_visible()

    def test_gitlab_tab_has_revert_button(self, class_page: Page):
        """Test that the GitLab tab has a Revert changes button."""
        class_page.goto("/config?tab=gitlab")
        _wait_for_config_tab(class_page)
        revert_button = class_page.get_by_role("button", name="Revert changes").first
        expect(revert_button).to_be_visible()


@pytest.mark.config_tabs
class TestConfigAuthTab:
    """Tests for the Authentication settings tab."""

    def test_auth_tab_loads(self, class_page: Page):
        """Test that navigating to the auth tab renders the form."""
        class_page.goto("/config?tab=auth")
        _wait_for_config_tab(class_page)
        expect(class_page.locator(".config-form-card").first).to_be_visible()

    def test_auth_tab_has_save_button(self, class_page: Page):
        """Test that the auth tab has a Save changes button."""
        class_page.goto("/config?tab=auth")
        _wait_for_config_tab(class_page)
        save_button = class_page.get_by_role("button", name="Save changes").first
        expect(save_button).to_be_visible()

    def test_auth_tab_has_test_oidc_button(self, class_page: Page):
        """Test that the auth tab has a Test OIDC connection button."""
        class_page.goto("/config?tab=auth")
        _wait_for_config_tab(class_page)
        test_oidc_button = class_page.get_by_role("button", name="Test OIDC connection")
        expect(test_oidc_button).to_be_visible()

    def test_auth_tab_has_revert_button(self, class_page: Page):
        """Test that the auth tab has a Revert changes button."""
        class_page.goto("/config?tab=auth")
        _wait_for_config_tab(class_page)
        revert_button = class_page.get_by_role("button", name="Revert changes").first
        expect(revert_button).to_be_visible()

    def test_auth_tab_has_form_inputs(self, class_page: Page):
        """Test that the auth tab form contains OIDC configuration fields."""
        class_page.goto("/config?tab=auth")
        _wait_for_config_tab(class_page)
        expect(class_page.locator("#oidc-settings")).to_be_visible()


@pytest.mark.config_tabs
class TestConfigMaintenanceTab:
    """Tests for the Maintenance settings tab."""

    def test_maintenance_tab_loads(self, class_page: Page):
        """Test that navigating to the maintenance tab renders the panel."""
        class_page.goto("/config?tab=maintenance")
        _wait_for_config_tab(class_page)
        expect(class_page.locator("#config-actions")).to_be_visible()

    def test_maintenance_tab_has_reload_button(self, class_page: Page):
        """Test that the maintenance tab has a Reload button."""
        class_page.goto("/config?tab=maintenance")
        _wait_for_config_tab(class_page)
        reload_button = class_page.get_by_role("button", name="Reload")
        expect(reload_button).to_be_visible()

    def test_maintenance_tab_has_reset_button(self, class_page: Page):
        """Test that the maintenance tab has a Reset to env/defaults button."""
        class_page.goto("/config?tab=maintenance")
        _wait_for_config_tab(class_page)
        reset_button = class_page.get_by_role("button", name="Reset to env/defaults")
        expect(reset_button).to_be_visible()


@pytest.mark.config_tabs
class TestConfigWorkerTab:
    """Tests for the Worker settings tab."""

    def test_worker_tab_loads(self, class_page: Page):
        """Test that navigating to the worker tab renders the form."""
        class_page.goto("/config?tab=worker")
        _wait_for_config_tab(class_page)
        expect(class_page.locator(".config-form-card").first).to_be_visible()

    def test_worker_tab_has_save_button(self, class_page: Page):
        """Test that the worker tab has a Save button for AI provider settings."""
        class_page.goto("/config?tab=worker")
        _wait_for_config_tab(class_page)
        save_button = class_page.get_by_role("button", name="Save changes").first
        expect(save_button).to_be_visible()

    def test_worker_tab_has_form_section(self, class_page: Page):
        """Test that the worker tab displays a configuration form section."""
        class_page.goto("/config?tab=worker")
        _wait_for_config_tab(class_page)
        expect(class_page.locator(".config-section-form").first).to_be_visible()


# ---------------------------------------------------------------------------
# Functional tests — tab navigation, form interactions, save/revert, actions
# ---------------------------------------------------------------------------

def _navigate_to_tab(page: Page, tab_name: str):
    """Navigate to a specific config tab and wait for content to render."""
    page.goto(f"/config?tab={tab_name}")
    page.wait_for_load_state("networkidle")
    _wait_for_config_tab(page)
    page.wait_for_timeout(500)  # Let tab panel content render


def _get_runtime_task_timeout_input(page: Page):
    """Locate the Task Timeout number input inside the Runtime settings form."""
    return page.locator(
        "#runtime-settings .n-form-item:has-text('Task Timeout') .n-input-number input"
    )


@pytest.mark.config_tabs
class TestConfigTabNavigation:
    """Tests for config tab navigation and URL query parameter behaviour."""

    def test_tab_url_param_selects_correct_tab(self, class_page: Page):
        """Navigate to /config?tab=gitlab and verify the GitLab tab is active."""
        _navigate_to_tab(class_page, "gitlab")
        # The active tab has the NaiveUI class that indicates selection
        gitlab_tab = class_page.locator(".n-tabs-tab").filter(has_text="GitLab")
        expect(gitlab_tab).to_have_class(re.compile(r"\bn-tabs-tab--active\b"))
        # GitLab-specific content should be visible
        expect(class_page.locator("#gitlab-settings")).to_be_visible()

    def test_switching_tabs_shows_correct_content(self, class_page: Page):
        """Click through several tabs and verify each panel renders correctly."""
        _navigate_to_tab(class_page, "runtime")
        expect(class_page.locator("#runtime-settings")).to_be_visible()

        # Click GitLab tab
        class_page.locator(".n-tabs-tab").filter(has_text="GitLab").click()
        class_page.wait_for_timeout(500)
        expect(class_page.locator("#gitlab-settings")).to_be_visible()

        # Click Maintenance tab
        class_page.locator(".n-tabs-tab").filter(has_text="Maintenance").click()
        class_page.wait_for_timeout(500)
        expect(class_page.locator("#config-actions")).to_be_visible()

        # Click Authentication tab
        class_page.locator(".n-tabs-tab").filter(has_text="Authentication").click()
        class_page.wait_for_timeout(500)
        expect(class_page.locator("#oidc-settings")).to_be_visible()


@pytest.mark.config_tabs
class TestRuntimeConfigFunctional:
    """Functional tests for runtime configuration save, revert, and form interaction."""

    def test_runtime_form_dirty_enables_save(self, logged_in_page: Page):
        """Modify a form field and verify Save/Revert buttons become enabled."""
        _navigate_to_tab(logged_in_page, "runtime")

        # Save and Revert should start disabled (form is clean)
        save_btn = logged_in_page.locator(
            "#runtime-settings"
        ).get_by_role("button", name="Save changes")
        revert_btn = logged_in_page.locator(
            "#runtime-settings"
        ).get_by_role("button", name="Revert changes")
        expect(save_btn).to_be_disabled()
        expect(revert_btn).to_be_disabled()

        # Modify the Task Timeout field to make the form dirty
        timeout_input = _get_runtime_task_timeout_input(logged_in_page)
        original_value = timeout_input.input_value()
        timeout_input.fill(str(int(original_value or "3600") + 1))

        # Now both buttons should be enabled
        expect(save_btn).to_be_enabled(timeout=3000)
        expect(revert_btn).to_be_enabled(timeout=3000)

    def test_runtime_revert_restores_original(self, logged_in_page: Page):
        """Modify a field, click Revert, and verify the value is restored and buttons disabled."""
        _navigate_to_tab(logged_in_page, "runtime")

        timeout_input = _get_runtime_task_timeout_input(logged_in_page)
        original_value = timeout_input.input_value()

        # Modify the field
        new_value = str(int(original_value or "3600") + 100)
        timeout_input.fill(new_value)

        save_btn = logged_in_page.locator(
            "#runtime-settings"
        ).get_by_role("button", name="Save changes")
        expect(save_btn).to_be_enabled(timeout=3000)

        # Click Revert
        revert_btn = logged_in_page.locator(
            "#runtime-settings"
        ).get_by_role("button", name="Revert changes")
        revert_btn.click()

        # Field should be back to original value, buttons disabled again
        expect(timeout_input).to_have_value(original_value, timeout=3000)
        expect(save_btn).to_be_disabled(timeout=3000)
        expect(revert_btn).to_be_disabled(timeout=3000)

    def test_runtime_save_persists_value(self, logged_in_page: Page):
        """Modify Task Timeout, Save, reload page, verify persisted, then revert to original."""
        _navigate_to_tab(logged_in_page, "runtime")

        timeout_input = _get_runtime_task_timeout_input(logged_in_page)
        original_value = timeout_input.input_value()

        # Choose a new value that is different from the original
        new_value = str(int(original_value or "3600") + 10)

        try:
            # Modify and save
            timeout_input.fill(new_value)
            save_btn = logged_in_page.locator(
                "#runtime-settings"
            ).get_by_role("button", name="Save changes")
            expect(save_btn).to_be_enabled(timeout=3000)
            save_btn.click()

            # Expect success notification
            expect(
                logged_in_page.locator(".n-message").filter(has_text="Configuration saved")
            ).to_be_visible(timeout=5000)

            # Save button should be disabled again (form is clean)
            expect(save_btn).to_be_disabled(timeout=5000)

            # Reload the page and verify the new value persisted
            _navigate_to_tab(logged_in_page, "runtime")
            timeout_input = _get_runtime_task_timeout_input(logged_in_page)
            expect(timeout_input).to_have_value(new_value, timeout=5000)
        finally:
            # Always revert to original value to avoid polluting other tests
            _navigate_to_tab(logged_in_page, "runtime")
            timeout_input = _get_runtime_task_timeout_input(logged_in_page)
            current = timeout_input.input_value()
            if current != original_value:
                timeout_input.fill(original_value)
                save_btn = logged_in_page.locator(
                    "#runtime-settings"
                ).get_by_role("button", name="Save changes")
                expect(save_btn).to_be_enabled(timeout=3000)
                save_btn.click()
                # Wait for save to complete
                expect(save_btn).to_be_disabled(timeout=5000)


@pytest.mark.config_tabs
class TestGitLabConfigFunctional:
    """Functional tests for GitLab settings action buttons."""

    def test_gitlab_test_connection_shows_result(self, logged_in_page: Page):
        """Click 'Test GitLab connection' and verify a result message appears."""
        _navigate_to_tab(logged_in_page, "gitlab")

        test_btn = logged_in_page.get_by_role("button", name="Test GitLab connection")
        expect(test_btn).to_be_visible()
        test_btn.click()

        # Either a success or error alert should appear within the GitLab settings card.
        # The component renders an <n-alert> with class config-actions__alert
        # OR a Naive UI toast (.n-message) on success/failure.
        result_indicator = logged_in_page.locator(
            "#gitlab-settings .n-alert, "
            ".n-message"
        ).first
        expect(result_indicator).to_be_visible(timeout=15000)

    def test_gitlab_invalidate_cache_shows_feedback(self, logged_in_page: Page):
        """Click 'Invalidate project cache' and verify a feedback message appears."""
        _navigate_to_tab(logged_in_page, "gitlab")

        cache_btn = logged_in_page.get_by_role("button", name="Invalidate project cache")
        expect(cache_btn).to_be_visible()
        cache_btn.click()

        # Should show either a success toast or an error toast
        feedback = logged_in_page.locator(".n-message").first
        expect(feedback).to_be_visible(timeout=10000)


@pytest.mark.config_tabs
class TestMaintenanceFunctional:
    """Functional tests for Maintenance panel actions."""

    def test_maintenance_reload_config(self, logged_in_page: Page):
        """Click Reload and verify the page does not error out (config reloads silently)."""
        _navigate_to_tab(logged_in_page, "maintenance")

        reload_btn = logged_in_page.get_by_role("button", name="Reload")
        expect(reload_btn).to_be_visible()
        expect(reload_btn).to_be_enabled()

        reload_btn.click()

        # Reload silently re-fetches config — after it finishes the button
        # should still be visible and enabled (no crash, no error).
        # Wait a moment for the network round-trip.
        logged_in_page.wait_for_load_state("networkidle")
        expect(reload_btn).to_be_visible(timeout=10000)
        expect(reload_btn).to_be_enabled(timeout=10000)

        # Verify the maintenance panel is still intact (no error overlay)
        expect(logged_in_page.locator("#config-actions")).to_be_visible()

    def test_maintenance_reset_shows_success(self, logged_in_page: Page):
        """Click 'Reset to env/defaults' and verify a success message appears."""
        _navigate_to_tab(logged_in_page, "maintenance")

        reset_btn = logged_in_page.get_by_role("button", name="Reset to env/defaults")
        expect(reset_btn).to_be_visible()
        reset_btn.click()

        # Reset triggers an API call and shows a success toast on completion
        expect(
            logged_in_page.locator(".n-message").filter(
                has_text="reset to env/default"
            )
        ).to_be_visible(timeout=10000)


@pytest.mark.config_tabs
class TestPromptTemplatesFunctional:
    """Functional test for prompt template create-then-delete lifecycle."""

    def test_prompt_template_create_and_delete(self, logged_in_page: Page):
        """Create a prompt template, verify it appears, then delete it to clean up."""
        template_name = "E2E Functional Test Template"
        template_content = "Review the {{files}} for issues"

        _navigate_to_tab(logged_in_page, "prompt-templates")
        # Wait for the Create Template button to be ready
        create_btn = logged_in_page.get_by_role("button", name="Create Template")
        expect(create_btn).to_be_visible(timeout=10000)

        # --- Create ---
        create_btn.click()
        editor = logged_in_page.locator(".prompt-template-editor")
        expect(editor).to_be_visible(timeout=5000)

        # Fill name
        name_input = logged_in_page.locator(".prompt-template-editor input").first
        name_input.fill(template_name)

        # Fill content via CodeMirror
        cm_content = logged_in_page.locator(".variable-editor .cm-content")
        cm_content.click()
        cm_content.fill(template_content)

        # Save the template
        logged_in_page.locator(
            ".prompt-template-editor__actions"
        ).get_by_role("button", name="Save").click()

        # Wait for editor to close (save succeeded)
        logged_in_page.wait_for_selector(
            ".prompt-template-editor", state="detached", timeout=5000
        )

        # Verify it appears in the list
        expect(
            logged_in_page.get_by_text(template_name).first
        ).to_be_visible(timeout=5000)

        # --- Delete (cleanup) --- target the row containing our template
        template_row = logged_in_page.locator(
            f".n-data-table tr:has-text('{template_name}')"
        )
        delete_btn = template_row.get_by_role("button", name="Delete")
        delete_btn.click()

        # Confirm in the popconfirm popover
        confirm_btn = logged_in_page.locator(".n-popover").get_by_role(
            "button", name="Delete"
        )
        expect(confirm_btn).to_be_visible(timeout=5000)
        confirm_btn.click()

        # Wait for the template to disappear
        logged_in_page.get_by_text(template_name).wait_for(
            state="detached", timeout=5000
        )
        expect(logged_in_page.get_by_text(template_name)).to_have_count(0)
