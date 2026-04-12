"""
Create Issue E2E Tests

Tests for the Create Issue page (/issues/create) including:
- Page loads and form layout
- Form fields present
- /create-task redirect
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.create_issue
class TestCreateIssuePage:
    """Tests for create issue page layout."""

    def test_page_loads(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("create-issue-page")).to_be_visible()

    def test_header_visible(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("create-issue-header")).to_be_visible()

    def test_form_visible(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("create-issue-form")).to_be_visible()

    def test_project_select_visible(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("create-issue-project")).to_be_visible()

    def test_title_input_visible(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("create-issue-title")).to_be_visible()

    def test_description_textarea_visible(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("create-issue-description")).to_be_visible()

    def test_submit_button_visible(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("create-issue-submit")).to_be_visible()


@pytest.mark.create_issue
class TestCreateIssueRedirect:
    """Tests for /create-task redirect."""

    def test_create_task_redirects_to_create_issue(self, logged_in_page: Page):
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_url("**/issues/create", timeout=5000)
        assert "/issues/create" in logged_in_page.url
