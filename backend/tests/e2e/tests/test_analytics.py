"""
Analytics Page E2E Tests

Tests for the Analytics page including:
- Page load and structure
- Hero/header rendering
- Summary card display
- Analytics content cards (charts)
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.analytics
class TestAnalyticsPage:
    """Tests for the analytics page structure and basic rendering."""

    def test_analytics_page_loads(self, logged_in_page: Page, reset_database):
        """Test that the analytics page loads without errors."""
        logged_in_page.goto("/analytics")
        logged_in_page.wait_for_selector(".analytics-page")
        expect(logged_in_page.locator(".analytics-page")).to_be_visible()

    def test_analytics_hero_is_visible(self, logged_in_page: Page, reset_database):
        """Test that the page hero/header area is rendered."""
        logged_in_page.goto("/analytics")
        logged_in_page.wait_for_selector(".analytics-page__hero")
        expect(logged_in_page.locator(".analytics-page__hero")).to_be_visible()

    def test_analytics_page_title_is_visible(self, logged_in_page: Page, reset_database):
        """Test that the analytics page title is rendered."""
        logged_in_page.goto("/analytics")
        logged_in_page.wait_for_selector(".analytics-page__title")
        expect(logged_in_page.locator(".analytics-page__title")).to_be_visible()

    def test_analytics_refresh_button_present(self, logged_in_page: Page, reset_database):
        """Test that a refresh button is present on the analytics page."""
        logged_in_page.goto("/analytics")
        logged_in_page.wait_for_selector(".analytics-page__hero")
        refresh_button = logged_in_page.get_by_role("button", name="Refresh")
        expect(refresh_button).to_be_visible()

    def test_analytics_refresh_button_clickable(self, logged_in_page: Page, reset_database):
        """Test that clicking the refresh button does not cause an error."""
        logged_in_page.goto("/analytics")
        logged_in_page.wait_for_selector(".analytics-page__hero")
        refresh_button = logged_in_page.get_by_role("button", name="Refresh")
        refresh_button.click()
        logged_in_page.wait_for_timeout(500)
        expect(logged_in_page.locator(".analytics-page")).to_be_visible()

    def test_analytics_page_has_no_errors_on_load(self, logged_in_page: Page, reset_database):
        """Test that the analytics page loads without showing any error states."""
        logged_in_page.goto("/analytics")
        logged_in_page.wait_for_selector(".analytics-page__hero")
        # The page container should be visible without any crash
        expect(logged_in_page.locator(".analytics-page")).to_be_visible()


@pytest.mark.analytics
class TestAnalyticsContent:
    """Tests for analytics page content and data cards."""

    def test_analytics_summary_cards_visible(self, logged_in_page: Page, reset_database):
        """Test that summary cards are visible after data loads."""
        logged_in_page.goto("/analytics")
        # Summary cards appear after first API response (v-if="hasLoadedOnce")
        logged_in_page.wait_for_selector(".analytics-summary-card", timeout=10000)
        expect(logged_in_page.locator(".analytics-summary-card").first).to_be_visible()

    def test_analytics_has_multiple_summary_cards(self, logged_in_page: Page, reset_database):
        """Test that several summary cards are displayed."""
        logged_in_page.goto("/analytics")
        logged_in_page.wait_for_selector(".analytics-summary-card", timeout=10000)
        summary_cards = logged_in_page.locator(".analytics-summary-card")
        assert summary_cards.count() > 1, "Expected multiple analytics summary cards"

    def test_analytics_content_cards_present(self, logged_in_page: Page, reset_database):
        """Test that analytics content cards (charts) are present."""
        logged_in_page.goto("/analytics")
        logged_in_page.wait_for_selector(".analytics-card", timeout=10000)
        expect(logged_in_page.locator(".analytics-card").first).to_be_visible()

    def test_analytics_card_headers_visible(self, logged_in_page: Page, reset_database):
        """Test that analytics card headers are rendered."""
        logged_in_page.goto("/analytics")
        logged_in_page.wait_for_selector(".analytics-card__header", timeout=10000)
        card_header = logged_in_page.locator(".analytics-card__header").first
        expect(card_header).to_be_visible()

    def test_analytics_card_has_title(self, logged_in_page: Page, reset_database):
        """Test that analytics content cards have title text."""
        logged_in_page.goto("/analytics")
        logged_in_page.wait_for_selector(".analytics-card__title", timeout=10000)
        card_title = logged_in_page.locator(".analytics-card__title").first
        expect(card_title).to_be_visible()

    def test_analytics_summary_card_has_label(self, logged_in_page: Page, reset_database):
        """Test that analytics summary cards have label elements."""
        logged_in_page.goto("/analytics")
        logged_in_page.wait_for_selector(".analytics-summary-card", timeout=10000)
        label = logged_in_page.locator(".analytics-summary-card__label").first
        expect(label).to_be_visible()

    def test_analytics_summary_card_has_value(self, logged_in_page: Page, reset_database):
        """Test that analytics summary cards display a value."""
        logged_in_page.goto("/analytics")
        logged_in_page.wait_for_selector(".analytics-summary-card", timeout=10000)
        value = logged_in_page.locator(".analytics-summary-card__value").first
        expect(value).to_be_visible()
