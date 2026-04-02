"""
Sessions Page E2E Tests

Tests for the Sessions management page including:
- Page load and structure
- Summary cards display
- Sessions list rendering
- Current session identification
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.sessions
class TestSessionsPage:
    """Tests for the sessions page structure and basic rendering."""

    def test_sessions_page_loads(self, logged_in_page: Page, reset_database):
        """Test that the sessions page loads without errors."""
        logged_in_page.goto("/sessions")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.locator(".sessions-page")).to_be_visible()

    def test_sessions_page_title_is_visible(self, logged_in_page: Page, reset_database):
        """Test that the page title is rendered."""
        logged_in_page.goto("/sessions")
        logged_in_page.wait_for_selector(".sessions-page__title")
        expect(logged_in_page.locator(".sessions-page__title")).to_be_visible()

    def test_sessions_hero_is_visible(self, logged_in_page: Page, reset_database):
        """Test that the hero/header area is visible."""
        logged_in_page.goto("/sessions")
        logged_in_page.wait_for_selector(".sessions-page__hero")
        expect(logged_in_page.locator(".sessions-page__hero")).to_be_visible()

    def test_sessions_summary_cards_displayed(self, logged_in_page: Page, reset_database):
        """Test that summary cards are visible after the page loads data."""
        logged_in_page.goto("/sessions")
        # Summary cards appear after the first API response (v-if="hasLoadedOnce")
        logged_in_page.wait_for_selector(".sessions-summary-card", timeout=10000)
        expect(logged_in_page.locator(".sessions-summary-card").first).to_be_visible()

    def test_sessions_reload_button_present(self, logged_in_page: Page, reset_database):
        """Test that the reload sessions button is present."""
        logged_in_page.goto("/sessions")
        logged_in_page.wait_for_selector(".sessions-page__title")
        reload_button = logged_in_page.get_by_role("button", name="Reload sessions")
        expect(reload_button).to_be_visible()

    def test_sessions_reload_button_triggers_refresh(self, logged_in_page: Page, reset_database):
        """Test that clicking reload button does not cause an error."""
        logged_in_page.goto("/sessions")
        logged_in_page.wait_for_selector(".sessions-summary-card", timeout=10000)
        reload_button = logged_in_page.get_by_role("button", name="Reload sessions")
        reload_button.click()
        # After click the page should still show the sessions container
        logged_in_page.wait_for_timeout(500)
        expect(logged_in_page.locator(".sessions-page")).to_be_visible()


@pytest.mark.sessions
class TestSessionsList:
    """Tests for the sessions list content."""

    def test_sessions_grid_exists_after_load(self, logged_in_page: Page, reset_database):
        """Test that the sessions grid container appears after data loads."""
        logged_in_page.goto("/sessions")
        # The grid appears only when sessions exist (v-if="hasLoadedOnce && sessions.length")
        logged_in_page.wait_for_selector(".sessions-summary-card", timeout=10000)
        # The current session should always be there
        grid = logged_in_page.locator(".sessions-grid")
        expect(grid).to_be_visible()

    def test_at_least_one_session_card_visible(self, logged_in_page: Page, reset_database):
        """Test that at least one session card is visible (the current session)."""
        logged_in_page.goto("/sessions")
        logged_in_page.wait_for_selector(".sessions-grid", timeout=10000)
        session_cards = logged_in_page.locator(".sessions-card")
        expect(session_cards.first).to_be_visible()

    def test_session_card_has_title(self, logged_in_page: Page, reset_database):
        """Test that session cards have a title element."""
        logged_in_page.goto("/sessions")
        logged_in_page.wait_for_selector(".sessions-grid", timeout=10000)
        session_title = logged_in_page.locator(".sessions-card__title").first
        expect(session_title).to_be_visible()

    def test_current_session_is_marked(self, logged_in_page: Page, reset_database):
        """
        Test that the current session is visually identified.

        NaiveUI n-tag elements are used to mark the current session.
        We look for a tag containing 'current' text or an n-tag near a session card.
        """
        logged_in_page.goto("/sessions")
        logged_in_page.wait_for_selector(".sessions-grid", timeout=10000)
        # Find a tag within session cards that indicates the current session
        current_tag = logged_in_page.locator(".sessions-card .n-tag").first
        expect(current_tag).to_be_visible()

    def test_revoke_button_present_on_session_card(self, logged_in_page: Page, reset_database):
        """Test that session cards have a revoke button."""
        logged_in_page.goto("/sessions")
        logged_in_page.wait_for_selector(".sessions-grid", timeout=10000)
        revoke_button = logged_in_page.locator(".sessions-card").first.get_by_role(
            "button", name="Revoke"
        )
        expect(revoke_button).to_be_visible()
