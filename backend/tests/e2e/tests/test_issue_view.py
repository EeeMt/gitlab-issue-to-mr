"""
Issue View E2E Tests

Tests for the Issue View page (/issues/:id) including:
- Page loads with created issue
- Layout sections visible
- Create task form
"""

import pytest
from playwright.sync_api import Page, expect
from conftest import api_create_issue, api_get_first_project


@pytest.fixture
def test_issue_id(logged_in_page, backend_url):
    """Create a test issue and return its ID."""
    cookies = {c["name"]: c["value"] for c in logged_in_page.context.cookies()}
    project = api_get_first_project(backend_url, cookies)
    issue = api_create_issue(backend_url, cookies, project["id"], title="E2E IssueView Test")
    return issue["id"]


@pytest.mark.issue_view
class TestIssueViewPage:
    """Tests for issue view page layout."""

    def test_page_loads(self, logged_in_page: Page, test_issue_id: int):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-view-page")).to_be_visible()

    def test_header_visible(self, logged_in_page: Page, test_issue_id: int):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-view-header")).to_be_visible()

    def test_metadata_card_visible(self, logged_in_page: Page, test_issue_id: int):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-metadata-card")).to_be_visible()

    def test_description_card_visible(self, logged_in_page: Page, test_issue_id: int):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-description-card")).to_be_visible()

    def test_tasks_card_visible(self, logged_in_page: Page, test_issue_id: int):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-tasks-card")).to_be_visible()

    def test_create_task_card_visible(self, logged_in_page: Page, test_issue_id: int):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-create-task-card")).to_be_visible()


@pytest.mark.issue_view
class TestIssueViewActions:
    """Tests for issue view action buttons."""

    def test_close_button_visible(self, logged_in_page: Page, test_issue_id: int):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-close-button")).to_be_visible()

    def test_task_prompt_visible(self, logged_in_page: Page, test_issue_id: int):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-task-prompt")).to_be_visible()

    def test_create_task_button_visible(self, logged_in_page: Page, test_issue_id: int):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-create-task-button")).to_be_visible()
