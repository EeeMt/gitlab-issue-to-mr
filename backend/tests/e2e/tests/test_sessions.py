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

    def test_sessions_page_loads(self, class_page: Page):
        """Test that the sessions page loads without errors."""
        class_page.goto("/sessions")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.locator(".sessions-page")).to_be_visible()

    def test_sessions_page_title_is_visible(self, class_page: Page):
        """Test that the page title is rendered."""
        class_page.goto("/sessions")
        class_page.wait_for_selector(".sessions-page__title")
        expect(class_page.locator(".sessions-page__title")).to_be_visible()

    def test_sessions_hero_is_visible(self, class_page: Page):
        """Test that the hero/header area is visible."""
        class_page.goto("/sessions")
        class_page.wait_for_selector(".sessions-page__hero")
        expect(class_page.locator(".sessions-page__hero")).to_be_visible()

    def test_sessions_summary_cards_displayed(self, class_page: Page):
        """Test that summary cards are visible after the page loads data."""
        class_page.goto("/sessions")
        # Summary cards appear after the first API response (v-if="hasLoadedOnce")
        class_page.wait_for_selector(".sessions-summary-card", timeout=10000)
        expect(class_page.locator(".sessions-summary-card").first).to_be_visible()

    def test_sessions_reload_button_present(self, class_page: Page):
        """Test that the reload sessions button is present."""
        class_page.goto("/sessions")
        class_page.wait_for_selector(".sessions-page__title")
        reload_button = class_page.get_by_role("button", name="Reload sessions")
        expect(reload_button).to_be_visible()

    def test_sessions_reload_button_triggers_refresh(self, class_page: Page):
        """Test that clicking reload button does not cause an error."""
        class_page.goto("/sessions")
        class_page.wait_for_selector(".sessions-summary-card", timeout=10000)
        reload_button = class_page.get_by_role("button", name="Reload sessions")
        reload_button.click()
        # After click the page should still show the sessions container
        class_page.wait_for_timeout(500)
        expect(class_page.locator(".sessions-page")).to_be_visible()


@pytest.mark.sessions
class TestSessionsList:
    """Tests for the sessions list content."""

    def test_sessions_grid_exists_after_load(self, class_page: Page):
        """Test that the sessions grid container appears after data loads."""
        class_page.goto("/sessions")
        # The grid appears only when sessions exist (v-if="hasLoadedOnce && sessions.length")
        class_page.wait_for_selector(".sessions-summary-card", timeout=10000)
        # The current session should always be there
        grid = class_page.locator(".sessions-grid")
        expect(grid).to_be_visible()

    def test_at_least_one_session_card_visible(self, class_page: Page):
        """Test that at least one session card is visible (the current session)."""
        class_page.goto("/sessions")
        class_page.wait_for_selector(".sessions-grid", timeout=10000)
        session_cards = class_page.locator(".sessions-card")
        expect(session_cards.first).to_be_visible()

    def test_session_card_has_title(self, class_page: Page):
        """Test that session cards have a title element."""
        class_page.goto("/sessions")
        class_page.wait_for_selector(".sessions-grid", timeout=10000)
        session_title = class_page.locator(".sessions-card__title").first
        expect(session_title).to_be_visible()

    def test_current_session_is_marked(self, class_page: Page):
        """
        Test that the current session is visually identified.

        NaiveUI n-tag elements are used to mark the current session.
        We look for a tag containing 'current' text or an n-tag near a session card.
        """
        class_page.goto("/sessions")
        class_page.wait_for_selector(".sessions-grid", timeout=10000)
        # Find a tag within session cards that indicates the current session
        current_tag = class_page.locator(".sessions-card .n-tag").first
        expect(current_tag).to_be_visible()

    def test_revoke_button_present_on_session_card(self, class_page: Page):
        """Test that session cards have a revoke button."""
        class_page.goto("/sessions")
        class_page.wait_for_selector(".sessions-grid", timeout=10000)
        revoke_button = class_page.locator(".sessions-card").first.get_by_role(
            "button", name="Revoke"
        )
        expect(revoke_button).to_be_visible()
