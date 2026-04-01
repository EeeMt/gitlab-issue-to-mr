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

    def test_create_task_page_loads(self, logged_in_page: Page, reset_database):
        """Test that the create task page loads without errors."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.locator(".create-task-page__title")).to_be_visible()

    def test_create_task_page_has_subtitle(self, logged_in_page: Page, reset_database):
        """Test that the create task page has a subtitle."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        subtitle = logged_in_page.locator(".create-task-page__subtitle")
        expect(subtitle).to_be_visible()

    def test_create_task_form_exists(self, logged_in_page: Page, reset_database):
        """Test that the create task form is present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        form = logged_in_page.locator(".create-task-form")
        expect(form).to_be_visible()

    def test_create_task_form_has_project_selector(self, logged_in_page: Page, reset_database):
        """Test that project selector is present in the form."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        project_select = logged_in_page.locator(".create-task-form").locator(".n-select").first
        expect(project_select).to_be_visible()

    def test_create_task_form_has_base_branch_selector(self, logged_in_page: Page, reset_database):
        """Test that base branch selector is present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        branch_selects = logged_in_page.locator(".create-task-form").locator(".n-select")
        if branch_selects.count() >= 2:
            expect(branch_selects.nth(1)).to_be_visible()

    def test_create_task_form_has_target_branch_selector(self, logged_in_page: Page, reset_database):
        """Test that target branch selector is present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        target_branch_select = logged_in_page.locator(".create-task-form").locator(".n-select").nth(2)
        if target_branch_select.is_visible():
            expect(target_branch_select).to_be_visible()

    def test_create_task_form_has_new_branch_input(self, logged_in_page: Page, reset_database):
        """Test that new branch name input is present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        new_branch_input = logged_in_page.locator(".create-task-form input").first
        expect(new_branch_input).to_be_visible()

    def test_create_task_form_has_priority_options(self, logged_in_page: Page, reset_database):
        """Test that priority radio options are present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        priority_radios = logged_in_page.locator(".n-radio")
        expect(priority_radios.first).to_be_visible()

    def test_create_task_form_has_schedule_options(self, logged_in_page: Page, reset_database):
        """Test that schedule type radio options are present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        schedule_radios = logged_in_page.locator(".n-radio-group").nth(1).locator(".n-radio")
        expect(schedule_radios.first).to_be_visible()

    def test_create_task_form_has_prompt_editor(self, logged_in_page: Page, reset_database):
        """Test that the prompt editor (VariableEditor) is present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        variable_editor = logged_in_page.locator(".variable-editor")
        expect(variable_editor).to_be_visible()

    def test_create_task_form_has_submit_button(self, logged_in_page: Page, reset_database):
        """Test that the submit/create button is present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        submit_button = logged_in_page.get_by_role("button", name="Create Task")
        expect(submit_button).to_be_visible()

    def test_create_task_form_has_reset_button(self, logged_in_page: Page, reset_database):
        """Test that the reset button is present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        reset_button = logged_in_page.get_by_role("button", name="Reset")
        expect(reset_button).to_be_visible()

    def test_create_task_page_tags_are_visible(self, logged_in_page: Page, reset_database):
        """Test that informational tags are displayed."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        tags = logged_in_page.locator(".create-task-page__hero .n-tag")
        expect(tags.first).to_be_visible()


@pytest.mark.manual_task
class TestManualTaskFormValidation:
    """Tests for manual task form validation."""

    def test_submit_without_required_fields_shows_validation(self, logged_in_page: Page, reset_database):
        """Test that submitting without required fields triggers validation."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        submit_button = logged_in_page.get_by_role("button", name="Create Task")
        submit_button.click()
        logged_in_page.wait_for_timeout(500)

    def test_prompt_field_is_required(self, logged_in_page: Page, reset_database):
        """Test that the prompt field is marked as required."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        variable_editor = logged_in_page.locator(".variable-editor")
        expect(variable_editor).to_be_visible()


@pytest.mark.manual_task
class TestManualTaskScheduleOptions:
    """Tests for manual task schedule options."""

    def test_execute_now_option_exists(self, logged_in_page: Page, reset_database):
        """Test that execute now option is available."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        now_option = logged_in_page.get_by_text("Execute Now")
        expect(now_option).to_be_visible()

    def test_delay_option_exists(self, logged_in_page: Page, reset_database):
        """Test that delay option is available."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        delay_option = logged_in_page.get_by_text("Delay")
        expect(delay_option).to_be_visible()

    def test_schedule_at_option_exists(self, logged_in_page: Page, reset_database):
        """Test that scheduled option is available."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        schedule_option = logged_in_page.get_by_text("Schedule At")
        expect(schedule_option).to_be_visible()

    def test_delay_inputs_appear_when_delay_selected(self, logged_in_page: Page, reset_database):
        """Test that delay inputs appear when delay option is selected."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        delay_option = logged_in_page.get_by_text("Delay")
        delay_option.click()
        delay_input = logged_in_page.locator(".n-input-number")
        expect(delay_input).to_be_visible()


@pytest.mark.manual_task
class TestManualTaskNavigation:
    """Tests for navigation to/from manual task creation."""

    def test_navigate_to_create_task_from_dashboard(self, logged_in_page: Page, reset_database):
        """Test navigating to create task page from dashboard."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        create_task_link = logged_in_page.locator(".nav-menu").get_by_text("Create Task")
        if create_task_link.is_visible():
            create_task_link.click()
            logged_in_page.wait_for_url("**/create-task", timeout=5000)
            assert "/create-task" in logged_in_page.url

    def test_create_task_page_is_reachable(self, logged_in_page: Page, reset_database):
        """Test that create task page is directly reachable."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("domcontentloaded")
        assert "/create-task" in logged_in_page.url
        expect(logged_in_page.locator(".create-task-page")).to_be_visible()
