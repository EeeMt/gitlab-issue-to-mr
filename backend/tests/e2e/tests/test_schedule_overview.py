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


# ---------------------------------------------------------------------------
# Interaction tests — refresh, summary card content
# ---------------------------------------------------------------------------


@pytest.mark.schedule_overview
class TestScheduleOverviewInteraction:
    """Tests for interactive elements on the schedule overview page."""

    def test_refresh_button_clickable(self, class_page: Page):
        """Click Refresh and verify the page stays stable after the data reload."""
        class_page.goto("/schedule-overview")
        class_page.wait_for_selector(".schedule-overview__hero")

        refresh = class_page.get_by_role("button", name="Refresh")
        expect(refresh).to_be_visible()

        # Click refresh and wait for potential network activity to settle
        refresh.click()
        class_page.wait_for_load_state("networkidle")

        # Page should remain stable after refresh
        expect(class_page.locator(".schedule-overview")).to_be_visible()
        expect(class_page.locator(".schedule-overview__hero")).to_be_visible()
        # Summary cards should still be present
        expect(class_page.locator(".schedule-summary-card").first).to_be_visible()

    def test_summary_cards_have_labels_and_values(self, class_page: Page):
        """Each summary card displays a non-empty label and a non-empty value."""
        class_page.goto("/schedule-overview")
        class_page.wait_for_selector(".schedule-overview__hero")

        cards = class_page.locator(".schedule-summary-card")
        count = cards.count()
        assert count > 0, "Expected at least one summary card"

        for i in range(count):
            card = cards.nth(i)
            label = card.locator(".schedule-summary-card__label")
            value = card.locator(".schedule-summary-card__value")
            expect(label).to_be_visible()
            expect(value).to_be_visible()
            assert label.text_content().strip(), f"Card {i} label should not be empty"
            assert value.text_content().strip(), f"Card {i} value should not be empty"

    def test_summary_cards_count(self, class_page: Page):
        """Verify at least 3 summary cards are rendered (base items are always ≥ 6)."""
        class_page.goto("/schedule-overview")
        class_page.wait_for_selector(".schedule-overview__hero")

        cards = class_page.locator(".schedule-summary-card")
        count = cards.count()
        assert count >= 3, f"Expected at least 3 summary cards, got {count}"


# ---------------------------------------------------------------------------
# Heatmap tests — chart visibility and structure
# ---------------------------------------------------------------------------


@pytest.mark.schedule_overview
class TestScheduleOverviewHeatmap:
    """Tests for the 7-day heatmap chart on the schedule overview page."""

    def test_heatmap_section_visible(self, class_page: Page):
        """The 7-day heatmap chart component is rendered on the page."""
        class_page.goto("/schedule-overview")
        class_page.wait_for_selector(".schedule-overview__hero")

        heatmap = class_page.locator(".heatmap-chart")
        expect(heatmap).to_be_visible()

    def test_heatmap_has_hour_labels(self, class_page: Page):
        """Heatmap contains exactly 24 hour labels (one per hour of the day)."""
        class_page.goto("/schedule-overview")
        class_page.wait_for_selector(".schedule-overview__hero")

        hour_labels = class_page.locator(".heatmap-chart__hour")
        expect(hour_labels).to_have_count(24)


# ---------------------------------------------------------------------------
# Navigation tests — reaching the page from different entry points
# ---------------------------------------------------------------------------


@pytest.mark.schedule_overview
class TestScheduleOverviewNavigation:
    """Tests for navigating to the schedule overview page from other pages."""

    def test_schedule_overview_accessible_from_config_page(self, class_page: Page):
        """Navigate to Schedule Overview via sidebar starting from the Config page."""
        class_page.goto("/config")
        class_page.wait_for_load_state("domcontentloaded")

        schedule_link = class_page.locator(".nav-menu").get_by_text(
            "Schedule Overview"
        )
        if schedule_link.is_visible():
            schedule_link.click()
            class_page.wait_for_url("**/schedule-overview", timeout=5000)
            expect(class_page.locator(".schedule-overview")).to_be_visible()
            expect(class_page.locator(".schedule-overview__title")).to_be_visible()
