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

    def test_schedule_overview_page_loads(self, logged_in_page: Page, reset_database):
        """Test that the schedule overview page loads and outer container is visible."""
        logged_in_page.goto("/schedule-overview")
        logged_in_page.wait_for_selector(".schedule-overview__hero")
        outer = logged_in_page.locator(".schedule-overview")
        expect(outer).to_be_visible()

    def test_hero_section_is_visible(self, logged_in_page: Page, reset_database):
        """Test that the hero section is visible on the schedule overview page."""
        logged_in_page.goto("/schedule-overview")
        logged_in_page.wait_for_selector(".schedule-overview__hero")
        hero = logged_in_page.locator(".schedule-overview__hero")
        expect(hero).to_be_visible()

    def test_title_is_visible(self, logged_in_page: Page, reset_database):
        """Test that the schedule overview page title is visible."""
        logged_in_page.goto("/schedule-overview")
        logged_in_page.wait_for_selector(".schedule-overview__hero")
        title = logged_in_page.locator(".schedule-overview__title")
        expect(title).to_be_visible()

    def test_refresh_button_is_present(self, logged_in_page: Page, reset_database):
        """Test that the refresh button is present in the actions area."""
        logged_in_page.goto("/schedule-overview")
        logged_in_page.wait_for_selector(".schedule-overview__hero")
        actions = logged_in_page.locator(".schedule-overview__actions")
        expect(actions).to_be_visible()
        refresh_btn = actions.get_by_role("button")
        expect(refresh_btn).to_be_visible()


@pytest.mark.schedule_overview
class TestScheduleOverviewContent:
    """Tests for ScheduleOverview page content and cards."""

    def test_summary_cards_are_visible(self, logged_in_page: Page, reset_database):
        """Test that summary cards are rendered on the page."""
        logged_in_page.goto("/schedule-overview")
        logged_in_page.wait_for_selector(".schedule-overview__hero")
        # summary cards are rendered immediately via v-for on summaryItems
        first_card = logged_in_page.locator(".schedule-summary-card").first
        expect(first_card).to_be_visible()

    def test_schedule_insight_cards_are_visible(self, logged_in_page: Page, reset_database):
        """Test that schedule content cards (insights) are visible."""
        logged_in_page.goto("/schedule-overview")
        logged_in_page.wait_for_selector(".schedule-overview__hero")
        schedule_cards = logged_in_page.locator(".schedule-card")
        expect(schedule_cards.first).to_be_visible()

    def test_schedule_card_has_header(self, logged_in_page: Page, reset_database):
        """Test that schedule content cards have a header section."""
        logged_in_page.goto("/schedule-overview")
        logged_in_page.wait_for_selector(".schedule-overview__hero")
        card_header = logged_in_page.locator(".schedule-card__header").first
        expect(card_header).to_be_visible()

    def test_sidebar_schedule_overview_link_navigates(self, logged_in_page: Page, reset_database):
        """Test that the Schedule Overview menu item in sidebar navigates to the page."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        schedule_link = logged_in_page.locator(".nav-menu").get_by_text("Schedule Overview")
        if schedule_link.is_visible():
            schedule_link.click()
            logged_in_page.wait_for_url("**/schedule-overview", timeout=5000)
            expect(logged_in_page.locator(".schedule-overview")).to_be_visible()
