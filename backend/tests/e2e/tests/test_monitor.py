"""
Monitor Page E2E Tests

Tests for the Monitor (system monitoring) page including:
- Page load and structure
- Summary card display
- Monitor tabs (runtime + debug)
- Active tasks and recent activity cards
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.monitor
class TestMonitorPage:
    """Tests for the monitor page structure and basic rendering."""

    def test_monitor_page_loads(self, class_page: Page):
        """Test that the monitor page loads without errors."""
        class_page.goto("/monitor")
        class_page.wait_for_selector(".monitor-page")
        expect(class_page.locator(".monitor-page")).to_be_visible()

    def test_monitor_hero_is_visible(self, class_page: Page):
        """Test that the page hero/header area is rendered."""
        class_page.goto("/monitor")
        class_page.wait_for_selector(".monitor-page__hero")
        expect(class_page.locator(".monitor-page__hero")).to_be_visible()

    def test_monitor_refresh_button_present(self, class_page: Page):
        """Test that a refresh button is present on the monitor page."""
        class_page.goto("/monitor")
        class_page.wait_for_selector(".monitor-page__hero")
        refresh_button = class_page.get_by_role("button", name="Refresh")
        expect(refresh_button).to_be_visible()

    def test_monitor_refresh_button_clickable(self, class_page: Page):
        """Test that clicking the refresh button does not cause an error."""
        class_page.goto("/monitor")
        class_page.wait_for_selector(".monitor-page__hero")
        refresh_button = class_page.get_by_role("button", name="Refresh")
        refresh_button.click()
        class_page.wait_for_timeout(500)
        # Page should still be stable after refresh
        expect(class_page.locator(".monitor-page")).to_be_visible()


@pytest.mark.monitor
class TestMonitorContent:
    """Tests for monitor page content and data cards."""

    def test_monitor_tabs_visible(self, class_page: Page):
        """Test that the monitor tabs container is rendered."""
        class_page.goto("/monitor")
        class_page.wait_for_selector(".monitor-tabs", timeout=10000)
        expect(class_page.locator(".monitor-tabs")).to_be_visible()

    def test_monitor_summary_cards_visible(self, class_page: Page):
        """Test that summary cards are displayed in the overview section."""
        class_page.goto("/monitor")
        class_page.wait_for_selector(".monitor-summary-card", timeout=10000)
        expect(class_page.locator(".monitor-summary-card").first).to_be_visible()

    def test_monitor_has_multiple_summary_cards(self, class_page: Page):
        """Test that several summary cards are present in the overview."""
        class_page.goto("/monitor")
        class_page.wait_for_selector(".monitor-summary-card", timeout=10000)
        summary_cards = class_page.locator(".monitor-summary-card")
        assert summary_cards.count() > 1, "Expected multiple summary cards on the monitor page"

    def test_monitor_content_cards_present(self, class_page: Page):
        """Test that monitor content cards (active tasks, recent activity) are rendered."""
        class_page.goto("/monitor")
        class_page.wait_for_selector(".monitor-card", timeout=10000)
        expect(class_page.locator(".monitor-card").first).to_be_visible()

    def test_monitor_active_tasks_card_visible(self, class_page: Page):
        """Test that the active tasks card header is visible."""
        class_page.goto("/monitor")
        class_page.wait_for_selector(".monitor-card__header", timeout=10000)
        card_header = class_page.locator(".monitor-card__header").first
        expect(card_header).to_be_visible()

    def test_monitor_card_has_title(self, class_page: Page):
        """Test that monitor cards display a title."""
        class_page.goto("/monitor")
        class_page.wait_for_selector(".monitor-card__title", timeout=10000)
        card_title = class_page.locator(".monitor-card__title").first
        expect(card_title).to_be_visible()

    def test_monitor_runtime_tab_active_by_default(self, class_page: Page):
        """Test that the runtime tab is selected when first loading the monitor page."""
        class_page.goto("/monitor")
        class_page.wait_for_selector(".monitor-tabs", timeout=10000)
        # The runtime tab pane should be visible (it is the default active tab)
        runtime_cards = class_page.locator(".monitor-summary-card")
        expect(runtime_cards.first).to_be_visible()
