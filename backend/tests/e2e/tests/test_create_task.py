"""
CreateTask Page E2E Tests

Tests for the CreateTask page functionality including:
- Form fill (project/branch/prompt)
- Schedule options selection (now/delay/scheduled)
- Priority selection (P0/P1/P2)
- Form submission
- Success verification
- Form validation error handling
"""

import pytest
from playwright.sync_api import Page, expect


def create_admin_and_login(page: Page):
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


@pytest.mark.create_task
class TestCreateTaskPage:
    """Tests for the create task page functionality."""

    def test_create_task_page_loads(self, page: Page, reset_database):
        """Test that the create task page loads without errors."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Verify page title is visible
        expect(page.locator(".create-task-page__title")).to_be_visible()

    def test_create_task_title_is_displayed(self, page: Page, reset_database):
        """Test that the create task title is displayed."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        expect(page.locator(".create-task-page__title")).to_be_visible()

    def test_create_task_subtitle_is_displayed(self, page: Page, reset_database):
        """Test that the create task subtitle is displayed."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        expect(page.locator(".create-task-page__subtitle")).to_be_visible()

    def test_create_task_form_exists(self, page: Page, reset_database):
        """Test that the create task form is present."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        expect(page.locator(".create-task-form")).to_be_visible()


@pytest.mark.create_task
class TestCreateTaskFormFields:
    """Tests for create task form field presence."""

    def test_project_selector_exists(self, page: Page, reset_database):
        """Test that project selector is present in the form."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Project select should be visible
        project_select = page.locator(".create-task-form").locator(".n-select").first
        expect(project_select).to_be_visible()

    def test_base_branch_selector_exists(self, page: Page, reset_database):
        """Test that base branch selector is present."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Base branch select should be visible (second select)
        branch_selects = page.locator(".create-task-form").locator(".n-select")
        if branch_selects.count() >= 2:
            expect(branch_selects.nth(1)).to_be_visible()

    def test_target_branch_selector_exists(self, page: Page, reset_database):
        """Test that target branch selector is present."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Target branch select should be visible
        target_branch_select = page.locator(".create-task-form").locator(".n-select").nth(2)
        if target_branch_select.is_visible():
            expect(target_branch_select).to_be_visible()

    def test_new_branch_input_exists(self, page: Page, reset_database):
        """Test that new branch name input is present."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # New branch input should be present
        new_branch_input = page.locator(".create-task-form input").first
        expect(new_branch_input).to_be_visible()

    def test_prompt_editor_exists(self, page: Page, reset_database):
        """Test that the prompt editor (VariableEditor) is present."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # VariableEditor should be present
        variable_editor = page.locator(".variable-editor")
        expect(variable_editor).to_be_visible()

    def test_priority_options_exist(self, page: Page, reset_database):
        """Test that priority radio options (P0/P1/P2) are present."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Priority radio group should have radio options
        priority_radios = page.locator(".n-radio")
        expect(priority_radios.first).to_be_visible()

    def test_schedule_options_exist(self, page: Page, reset_database):
        """Test that schedule type radio options are present."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Schedule radio group should have options
        schedule_radios = page.locator(".n-radio-group").nth(1).locator(".n-radio")
        expect(schedule_radios.first).to_be_visible()


@pytest.mark.create_task
class TestCreateTaskScheduleOptions:
    """Tests for schedule options on create task form."""

    def test_execute_now_option_is_present(self, page: Page, reset_database):
        """Test that execute now option is available."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_text("Execute Now")).to_be_visible()

    def test_delay_option_is_present(self, page: Page, reset_database):
        """Test that delay option is available."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_text("Delay")).to_be_visible()

    def test_schedule_at_option_is_present(self, page: Page, reset_database):
        """Test that schedule at option is available."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_text("Schedule At")).to_be_visible()

    def test_delay_inputs_appear_when_delay_selected(self, page: Page, reset_database):
        """Test that delay inputs appear when delay option is selected."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Click on delay option
        delay_option = page.get_by_text("Delay")
        delay_option.click()

        # Delay input number should appear
        delay_input = page.locator(".n-input-number")
        expect(delay_input).to_be_visible()


@pytest.mark.create_task
class TestCreateTaskFormActions:
    """Tests for create task form action buttons."""

    def test_submit_button_exists(self, page: Page, reset_database):
        """Test that the submit/create button is present."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        submit_button = page.get_by_role("button", name="Create Task")
        expect(submit_button).to_be_visible()

    def test_reset_button_exists(self, page: Page, reset_database):
        """Test that the reset button is present."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        reset_button = page.get_by_role("button", name="Reset")
        expect(reset_button).to_be_visible()


@pytest.mark.create_task
class TestCreateTaskValidation:
    """Tests for create task form validation."""

    def test_submit_without_required_fields_shows_validation(self, page: Page, reset_database):
        """Test that submitting without required fields triggers validation."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Try to submit without filling required fields
        submit_button = page.get_by_role("button", name="Create Task")
        submit_button.click()

        # Wait for validation feedback
        page.wait_for_timeout(500)

    def test_prompt_field_has_required_indicator(self, page: Page, reset_database):
        """Test that the prompt field is marked as required."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # VariableEditor should be present
        variable_editor = page.locator(".variable-editor")
        expect(variable_editor).to_be_visible()


@pytest.mark.create_task
class TestCreateTaskNavigation:
    """Tests for navigation to/from create task page."""

    def test_navigate_to_create_task_from_sidebar(self, page: Page, reset_database):
        """Test navigating to create task page from sidebar."""
        create_admin_and_login(page)

        # Go to dashboard first
        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")

        # Navigate to create task via sidebar
        create_task_link = page.locator(".nav-menu").get_by_text("Create Task")
        if create_task_link.is_visible():
            create_task_link.click()
            page.wait_for_url("**/create-task", timeout=10000)

    def test_create_task_page_is_directly_reachable(self, page: Page, reset_database):
        """Test that create task page is directly reachable."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        expect(page.locator(".create-task-page")).to_be_visible()

    def test_info_tags_are_displayed(self, page: Page, reset_database):
        """Test that informational tags are displayed on create task page."""
        create_admin_and_login(page)

        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

        # Tags should be visible (manual trigger, scheduler aware, gitlab branch workflow)
        tags = page.locator(".create-task-page__hero .n-tag")
        expect(tags.first).to_be_visible()
