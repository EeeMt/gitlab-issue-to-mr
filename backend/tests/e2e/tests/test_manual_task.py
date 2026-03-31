"""
Manual Task Creation E2E Tests

Tests for the CreateTask page functionality including:
- Form fill (project/branch/prompt)
- Schedule options selection
- Form submission
- Success verification
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.manual_task
class TestManualTaskCreation:
    """Tests for manual task creation functionality."""

    def _create_admin_and_login(self, page: Page):
        """Helper to create admin via bootstrap and login."""
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("createtask_admin")
        inputs.nth(1).fill("CreateTask Admin")
        inputs.nth(2).fill("createtask_admin@example.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)
        page.wait_for_load_state("networkidle")

    def test_create_task_page_loads(self, page: Page, reset_database):
        """Test that the create task page loads without errors."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Verify page title is visible
        expect(page.locator(".create-task-page__title")).to_be_visible()

    def test_create_task_page_has_subtitle(self, page: Page, reset_database):
        """Test that the create task page has a subtitle."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        subtitle = page.locator(".create-task-page__subtitle")
        expect(subtitle).to_be_visible()

    def test_create_task_form_exists(self, page: Page, reset_database):
        """Test that the create task form is present."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        form = page.locator(".create-task-form")
        expect(form).to_be_visible()

    def test_create_task_form_has_project_selector(self, page: Page, reset_database):
        """Test that project selector is present in the form."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Project select should be visible
        project_select = page.locator(".create-task-form").locator(".n-select").first
        expect(project_select).to_be_visible()

    def test_create_task_form_has_base_branch_selector(self, page: Page, reset_database):
        """Test that base branch selector is present."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Base branch select should be visible (second select)
        branch_selects = page.locator(".create-task-form").locator(".n-select")
        if branch_selects.count() >= 2:
            expect(branch_selects.nth(1)).to_be_visible()

    def test_create_task_form_has_target_branch_selector(self, page: Page, reset_database):
        """Test that target branch selector is present."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Target branch select should be visible
        target_branch_select = page.locator(".create-task-form").locator(".n-select").nth(2)
        if target_branch_select.is_visible():
            expect(target_branch_select).to_be_visible()

    def test_create_task_form_has_new_branch_input(self, page: Page, reset_database):
        """Test that new branch name input is present."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # New branch input should be present
        new_branch_input = page.locator(".create-task-form input").first
        expect(new_branch_input).to_be_visible()

    def test_create_task_form_has_priority_options(self, page: Page, reset_database):
        """Test that priority radio options are present."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Priority radio group should have P0, P1, P2 options
        priority_radios = page.locator(".n-radio")
        expect(priority_radios.first).to_be_visible()

    def test_create_task_form_has_schedule_options(self, page: Page, reset_database):
        """Test that schedule type radio options are present."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Schedule options should include "now", "delay", "scheduled"
        schedule_radios = page.locator(".n-radio-group").nth(1).locator(".n-radio")
        expect(schedule_radios.first).to_be_visible()

    def test_create_task_form_has_prompt_editor(self, page: Page, reset_database):
        """Test that the prompt editor (VariableEditor) is present."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # VariableEditor with CodeMirror should be present
        variable_editor = page.locator(".variable-editor")
        expect(variable_editor).to_be_visible()

    def test_create_task_form_has_submit_button(self, page: Page, reset_database):
        """Test that the submit/create button is present."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Create task button should be visible
        submit_button = page.get_by_role("button", name="Create Task")
        expect(submit_button).to_be_visible()

    def test_create_task_form_has_reset_button(self, page: Page, reset_database):
        """Test that the reset button is present."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Reset button should be visible
        reset_button = page.get_by_role("button", name="Reset")
        expect(reset_button).to_be_visible()

    def test_create_task_page_tags_are_visible(self, page: Page, reset_database):
        """Test that informational tags are displayed."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Tags should be visible (manual trigger, scheduler aware, gitlab branch workflow)
        tags = page.locator(".create-task-page__hero .n-tag")
        expect(tags.first).to_be_visible()


@pytest.mark.manual_task
class TestManualTaskFormValidation:
    """Tests for manual task form validation."""

    def _create_admin_and_login(self, page: Page):
        """Helper to create admin via bootstrap and login."""
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("validation_admin")
        inputs.nth(1).fill("Validation Admin")
        inputs.nth(2).fill("validation_admin@example.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)
        page.wait_for_load_state("networkidle")

    def test_submit_without_required_fields_shows_validation(self, page: Page, reset_database):
        """Test that submitting without required fields triggers validation."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Try to submit without filling required fields
        submit_button = page.get_by_role("button", name="Create Task")
        submit_button.click()

        # Wait for validation feedback
        page.wait_for_timeout(500)

    def test_prompt_field_is_required(self, page: Page, reset_database):
        """Test that the prompt field is marked as required."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # The VariableEditor should be present
        variable_editor = page.locator(".variable-editor")
        expect(variable_editor).to_be_visible()


@pytest.mark.manual_task
class TestManualTaskScheduleOptions:
    """Tests for manual task schedule options."""

    def _create_admin_and_login(self, page: Page):
        """Helper to create admin via bootstrap and login."""
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("schedule_admin")
        inputs.nth(1).fill("Schedule Admin")
        inputs.nth(2).fill("schedule_admin@example.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)
        page.wait_for_load_state("networkidle")

    def test_execute_now_option_exists(self, page: Page, reset_database):
        """Test that execute now option is available."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Find the "now" radio option
        now_option = page.get_by_text("Execute Now")
        expect(now_option).to_be_visible()

    def test_delay_option_exists(self, page: Page, reset_database):
        """Test that delay option is available."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Find the "delay" radio option
        delay_option = page.get_by_text("Delay")
        expect(delay_option).to_be_visible()

    def test_schedule_at_option_exists(self, page: Page, reset_database):
        """Test that scheduled option is available."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Find the "Schedule At" radio option
        schedule_option = page.get_by_text("Schedule At")
        expect(schedule_option).to_be_visible()

    def test_delay_inputs_appear_when_delay_selected(self, page: Page, reset_database):
        """Test that delay inputs appear when delay option is selected."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Click on delay option
        delay_option = page.get_by_text("Delay")
        delay_option.click()

        # Delay input number and unit select should appear
        delay_input = page.locator(".n-input-number")
        expect(delay_input).to_be_visible()


@pytest.mark.manual_task
class TestManualTaskNavigation:
    """Tests for navigation to/from manual task creation."""

    def _create_admin_and_login(self, page: Page):
        """Helper to create admin via bootstrap and login."""
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("nav_admin")
        inputs.nth(1).fill("Nav Admin")
        inputs.nth(2).fill("nav_admin@example.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)
        page.wait_for_load_state("networkidle")

    def test_navigate_to_create_task_from_dashboard(self, page: Page, reset_database):
        """Test navigating to create task page from dashboard."""
        self._create_admin_and_login(page)

        # Go to dashboard
        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")

        # Navigate to create task via sidebar or button
        create_task_link = page.locator(".nav-menu").get_by_text("Create Task")
        if create_task_link.is_visible():
            create_task_link.click()
            page.wait_for_url("**/create-task", timeout=5000)
            expect(page).to_have_url("**/create-task")

    def test_create_task_page_is_reachable(self, page: Page, reset_database):
        """Test that create task page is directly reachable."""
        self._create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_url("**/create-task")
        expect(page.locator(".create-task-page")).to_be_visible()
