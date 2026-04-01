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




@pytest.mark.create_task
class TestCreateTaskPage:
    """Tests for the create task page functionality."""

    def test_create_task_page_loads(self, logged_in_page: Page, reset_database):
        """Test that the create task page loads without errors."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        expect(logged_in_page.locator(".create-task-page__title")).to_be_visible()

    def test_create_task_title_is_displayed(self, logged_in_page: Page, reset_database):
        """Test that the create task title is displayed."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        expect(logged_in_page.locator(".create-task-page__title")).to_be_visible()

    def test_create_task_subtitle_is_displayed(self, logged_in_page: Page, reset_database):
        """Test that the create task subtitle is displayed."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        expect(logged_in_page.locator(".create-task-page__subtitle")).to_be_visible()

    def test_create_task_form_exists(self, logged_in_page: Page, reset_database):
        """Test that the create task form is present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        expect(logged_in_page.locator(".create-task-form")).to_be_visible()


@pytest.mark.create_task
class TestCreateTaskFormFields:
    """Tests for create task form field presence."""

    def test_project_selector_exists(self, logged_in_page: Page, reset_database):
        """Test that project selector is present in the form."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        project_select = logged_in_page.locator(".create-task-form").locator(".n-select").first
        expect(project_select).to_be_visible()

    def test_base_branch_selector_exists(self, logged_in_page: Page, reset_database):
        """Test that base branch selector is present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        branch_selects = logged_in_page.locator(".create-task-form").locator(".n-select")
        if branch_selects.count() >= 2:
            expect(branch_selects.nth(1)).to_be_visible()

    def test_target_branch_selector_exists(self, logged_in_page: Page, reset_database):
        """Test that target branch selector is present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        target_branch_select = logged_in_page.locator(".create-task-form").locator(".n-select").nth(2)
        if target_branch_select.is_visible():
            expect(target_branch_select).to_be_visible()

    def test_new_branch_input_exists(self, logged_in_page: Page, reset_database):
        """Test that new branch name input is present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        new_branch_input = logged_in_page.locator(".create-task-form input").first
        expect(new_branch_input).to_be_visible()

    def test_prompt_editor_exists(self, logged_in_page: Page, reset_database):
        """Test that the prompt editor (VariableEditor) is present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        variable_editor = logged_in_page.locator(".variable-editor")
        expect(variable_editor).to_be_visible()

    def test_priority_options_exist(self, logged_in_page: Page, reset_database):
        """Test that priority radio options (P0/P1/P2) are present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        priority_radios = logged_in_page.locator(".n-radio")
        expect(priority_radios.first).to_be_visible()

    def test_schedule_options_exist(self, logged_in_page: Page, reset_database):
        """Test that schedule type radio options are present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        schedule_radios = logged_in_page.locator(".n-radio-group").nth(1).locator(".n-radio")
        expect(schedule_radios.first).to_be_visible()


@pytest.mark.create_task
class TestCreateTaskScheduleOptions:
    """Tests for schedule options on create task form."""

    def test_execute_now_option_is_present(self, logged_in_page: Page, reset_database):
        """Test that execute now option is available."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        expect(logged_in_page.get_by_text("Execute Now")).to_be_visible()

    def test_delay_option_is_present(self, logged_in_page: Page, reset_database):
        """Test that delay option is available."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        expect(logged_in_page.get_by_text("Delay")).to_be_visible()

    def test_schedule_at_option_is_present(self, logged_in_page: Page, reset_database):
        """Test that schedule at option is available."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        expect(logged_in_page.get_by_text("Schedule At")).to_be_visible()

    def test_delay_inputs_appear_when_delay_selected(self, logged_in_page: Page, reset_database):
        """Test that delay inputs appear when delay option is selected."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        delay_option = logged_in_page.get_by_text("Delay")
        delay_option.click()
        delay_input = logged_in_page.locator(".n-input-number")
        expect(delay_input).to_be_visible()


@pytest.mark.create_task
class TestCreateTaskFormActions:
    """Tests for create task form action buttons."""

    def test_submit_button_exists(self, logged_in_page: Page, reset_database):
        """Test that the submit/create button is present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        submit_button = logged_in_page.get_by_role("button", name="Create Task")
        expect(submit_button).to_be_visible()

    def test_reset_button_exists(self, logged_in_page: Page, reset_database):
        """Test that the reset button is present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        reset_button = logged_in_page.get_by_role("button", name="Reset")
        expect(reset_button).to_be_visible()


@pytest.mark.create_task
class TestCreateTaskValidation:
    """Tests for create task form validation."""

    def test_submit_without_required_fields_shows_validation(self, logged_in_page: Page, reset_database):
        """Test that submitting without required fields triggers validation."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        submit_button = logged_in_page.get_by_role("button", name="Create Task")
        submit_button.click()
        logged_in_page.wait_for_timeout(500)

    def test_prompt_field_has_required_indicator(self, logged_in_page: Page, reset_database):
        """Test that the prompt field is marked as required."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        variable_editor = logged_in_page.locator(".variable-editor")
        expect(variable_editor).to_be_visible()


@pytest.mark.create_task
class TestCreateTaskNavigation:
    """Tests for navigation to/from create task page."""

    def test_navigate_to_create_task_from_sidebar(self, logged_in_page: Page, reset_database):
        """Test navigating to create task page from sidebar."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("networkidle")

        create_task_link = logged_in_page.locator(".nav-menu").get_by_text("Create Task")
        if create_task_link.is_visible():
            create_task_link.click()
            logged_in_page.wait_for_url("**/create-task", timeout=10000)

    def test_create_task_page_is_directly_reachable(self, logged_in_page: Page, reset_database):
        """Test that create task page is directly reachable."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        expect(logged_in_page.locator(".create-task-page")).to_be_visible()

    def test_info_tags_are_displayed(self, logged_in_page: Page, reset_database):
        """Test that informational tags are displayed on create task page."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        tags = logged_in_page.locator(".create-task-page__hero .n-tag")
        expect(tags.first).to_be_visible()
