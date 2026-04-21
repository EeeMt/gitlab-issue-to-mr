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

    def test_analytics_page_loads(self, class_page: Page):
        """Test that the analytics page loads without errors."""
        class_page.goto("/analytics")
        class_page.wait_for_selector(".analytics-page")
        expect(class_page.locator(".analytics-page")).to_be_visible()

    def test_analytics_hero_is_visible(self, class_page: Page):
        """Test that the page hero/header area is rendered."""
        class_page.goto("/analytics")
        class_page.wait_for_selector(".analytics-page__hero")
        expect(class_page.locator(".analytics-page__hero")).to_be_visible()

    def test_analytics_page_title_is_visible(self, class_page: Page):
        """Test that the analytics page title is rendered."""
        class_page.goto("/analytics")
        class_page.wait_for_selector(".analytics-page__title")
        expect(class_page.locator(".analytics-page__title")).to_be_visible()

    def test_analytics_refresh_button_present(self, class_page: Page):
        """Test that a refresh button is present on the analytics page."""
        class_page.goto("/analytics")
        class_page.wait_for_selector(".analytics-page__hero")
        refresh_button = class_page.get_by_role("button", name="Refresh")
        expect(refresh_button).to_be_visible()

    def test_analytics_refresh_button_clickable(self, class_page: Page):
        """Test that clicking the refresh button does not cause an error."""
        class_page.goto("/analytics")
        class_page.wait_for_selector(".analytics-page__hero")
        refresh_button = class_page.get_by_role("button", name="Refresh")
        refresh_button.click()
        class_page.wait_for_timeout(500)
        expect(class_page.locator(".analytics-page")).to_be_visible()

    def test_analytics_page_has_no_errors_on_load(self, class_page: Page):
        """Test that the analytics page loads without showing any error states."""
        class_page.goto("/analytics")
        class_page.wait_for_selector(".analytics-page__hero")
        # The page container should be visible without any crash
        expect(class_page.locator(".analytics-page")).to_be_visible()


@pytest.mark.analytics
class TestAnalyticsContent:
    """Tests for analytics page content and data cards."""

    def test_analytics_summary_cards_visible(self, class_page: Page):
        """Test that summary cards are visible after data loads."""
        class_page.goto("/analytics")
        # Summary cards appear after first API response (v-if="hasLoadedOnce")
        class_page.wait_for_selector(".analytics-summary-card", timeout=10000)
        expect(class_page.locator(".analytics-summary-card").first).to_be_visible()

    def test_analytics_has_multiple_summary_cards(self, class_page: Page):
        """Test that several summary cards are displayed."""
        class_page.goto("/analytics")
        class_page.wait_for_selector(".analytics-summary-card", timeout=10000)
        summary_cards = class_page.locator(".analytics-summary-card")
        assert summary_cards.count() > 1, "Expected multiple analytics summary cards"

    def test_analytics_content_cards_present(self, class_page: Page):
        """Test that analytics content cards (charts) are present."""
        class_page.goto("/analytics")
        class_page.wait_for_selector(".analytics-card", timeout=10000)
        expect(class_page.locator(".analytics-card").first).to_be_visible()

    def test_analytics_card_headers_visible(self, class_page: Page):
        """Test that analytics card headers are rendered."""
        class_page.goto("/analytics")
        class_page.wait_for_selector(".analytics-card__header", timeout=10000)
        card_header = class_page.locator(".analytics-card__header").first
        expect(card_header).to_be_visible()

    def test_analytics_card_has_title(self, class_page: Page):
        """Test that analytics content cards have title text."""
        class_page.goto("/analytics")
        class_page.wait_for_selector(".analytics-card__title", timeout=10000)
        card_title = class_page.locator(".analytics-card__title").first
        expect(card_title).to_be_visible()

    def test_analytics_summary_card_has_label(self, class_page: Page):
        """Test that analytics summary cards have label elements."""
        class_page.goto("/analytics")
        class_page.wait_for_selector(".analytics-summary-card", timeout=10000)
        label = class_page.locator(".analytics-summary-card__label").first
        expect(label).to_be_visible()

    def test_analytics_summary_card_has_value(self, class_page: Page):
        """Test that analytics summary cards display a value."""
        class_page.goto("/analytics")
        class_page.wait_for_selector(".analytics-summary-card", timeout=10000)
        value = class_page.locator(".analytics-summary-card__value").first
        expect(value).to_be_visible()
