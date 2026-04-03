"""
ScheduleOverview E2E Tests

Tests for the ScheduleOverview page functionality including:
- Page structure and hero section
- Summary cards display
- Content cards (schedule cards)
- Refresh button presence
- Sidebar navigation link
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.schedule_overview
class TestScheduleOverviewPage:
    """Tests for the ScheduleOverview page structure."""

    def test_schedule_overview_page_loads(self, class_page: Page):
        """Test that the schedule overview page loads and outer container is visible."""
        class_page.goto("/schedule-overview")
        class_page.wait_for_selector(".schedule-overview__hero")
        outer = class_page.locator(".schedule-overview")
        expect(outer).to_be_visible()

    def test_hero_section_is_visible(self, class_page: Page):
        """Test that the hero section is visible on the schedule overview page."""
        class_page.goto("/schedule-overview")
        class_page.wait_for_selector(".schedule-overview__hero")
        hero = class_page.locator(".schedule-overview__hero")
        expect(hero).to_be_visible()

    def test_title_is_visible(self, class_page: Page):
        """Test that the schedule overview page title is visible."""
        class_page.goto("/schedule-overview")
        class_page.wait_for_selector(".schedule-overview__hero")
        title = class_page.locator(".schedule-overview__title")
        expect(title).to_be_visible()

    def test_refresh_button_is_present(self, class_page: Page):
        """Test that the refresh button is present in the actions area."""
        class_page.goto("/schedule-overview")
        class_page.wait_for_selector(".schedule-overview__hero")
        actions = class_page.locator(".schedule-overview__actions")
        expect(actions).to_be_visible()
        refresh_btn = actions.get_by_role("button")
        expect(refresh_btn).to_be_visible()


@pytest.mark.schedule_overview
class TestScheduleOverviewContent:
    """Tests for ScheduleOverview page content and cards."""

    def test_summary_cards_are_visible(self, class_page: Page):
        """Test that summary cards are rendered on the page."""
        class_page.goto("/schedule-overview")
        class_page.wait_for_selector(".schedule-overview__hero")
        # summary cards are rendered immediately via v-for on summaryItems
        first_card = class_page.locator(".schedule-summary-card").first
        expect(first_card).to_be_visible()

    def test_schedule_insight_cards_are_visible(self, class_page: Page):
        """Test that schedule content cards (insights) are visible."""
        class_page.goto("/schedule-overview")
        class_page.wait_for_selector(".schedule-overview__hero")
        schedule_cards = class_page.locator(".schedule-card")
        expect(schedule_cards.first).to_be_visible()

    def test_schedule_card_has_header(self, class_page: Page):
        """Test that schedule content cards have a header section."""
        class_page.goto("/schedule-overview")
        class_page.wait_for_selector(".schedule-overview__hero")
        card_header = class_page.locator(".schedule-card__header").first
        expect(card_header).to_be_visible()

    def test_sidebar_schedule_overview_link_navigates(self, class_page: Page):
        """Test that the Schedule Overview menu item in sidebar navigates to the page."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        schedule_link = class_page.locator(".nav-menu").get_by_text("Schedule Overview")
        if schedule_link.is_visible():
            schedule_link.click()
            class_page.wait_for_url("**/schedule-overview", timeout=5000)
            expect(class_page.locator(".schedule-overview")).to_be_visible()
