"""
Issue List E2E Tests

Tests for the Issue List page (/issues) including:
- Page loads and layout
- Create button navigation
- Status filter
- Issue appears after creation
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.issue_list
class TestIssueListPage:
    """Tests for issue list page layout."""

    def test_issue_list_page_loads(self, class_page: Page):
        class_page.goto("/issues")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("issue-list-page")).to_be_visible()

    def test_issue_list_header_visible(self, class_page: Page):
        class_page.goto("/issues")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("issue-list-header")).to_be_visible()

    def test_issue_list_table_visible(self, class_page: Page):
        class_page.goto("/issues")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("issue-list-table")).to_be_visible()

    def test_create_button_visible(self, class_page: Page):
        class_page.goto("/issues")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("issue-list-create-button")).to_be_visible()

    def test_status_filter_visible(self, class_page: Page):
        class_page.goto("/issues")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("issue-list-status-filter")).to_be_visible()


@pytest.mark.issue_list
class TestIssueListNavigation:
    """Tests for issue list navigation."""

    def test_create_button_navigates_to_create_issue(self, logged_in_page: Page):
        logged_in_page.goto("/issues")
        logged_in_page.wait_for_load_state("domcontentloaded")
        logged_in_page.get_by_test_id("issue-list-create-button").click()
        logged_in_page.wait_for_url("**/issues/create", timeout=5000)
        assert "/issues/create" in logged_in_page.url
