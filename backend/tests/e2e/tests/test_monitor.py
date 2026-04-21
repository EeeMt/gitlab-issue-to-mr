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


# ---------------------------------------------------------------------------
#  Helper: navigate to Monitor and wait for tabs to be interactive
# ---------------------------------------------------------------------------

def _goto_monitor(page: Page) -> None:
    """Navigate to the Monitor page and wait for the tabs container."""
    page.goto("/monitor")
    page.wait_for_selector(".monitor-tabs", timeout=10000)


def _switch_to_tab(page: Page, tab_name: str) -> None:
    """Click the Naive UI tab whose label *contains* ``tab_name``.

    Naive UI renders each tab with the CSS class ``n-tabs-tab``.
    We locate the tab by its visible text and click it, then give the
    animated transition a moment to settle.
    """
    tab = page.locator(".n-tabs-tab").filter(has_text=tab_name)
    expect(tab.first).to_be_visible(timeout=5000)
    tab.first.click()
    page.wait_for_timeout(600)


# ===================================================================
#  Tab Switching Tests
# ===================================================================


@pytest.mark.monitor
class TestMonitorTabSwitching:
    """Verify that the three monitor tabs (Runtime / Debug / Health) can be
    activated and that switching between them keeps the page stable."""

    def test_debug_tab_accessible(self, class_page: Page):
        """Clicking the Debug tab makes debug-specific content visible."""
        _goto_monitor(class_page)

        # The debug tab label is "Container Debugging" (en) – match substring
        _switch_to_tab(class_page, "Debug")

        # After switching, the containers card should appear (always present
        # in the debug pane even if the list is empty).
        containers_card = class_page.locator(
            ".monitor-card .monitor-card__title"
        ).filter(has_text="Container")
        expect(containers_card.first).to_be_visible(timeout=5000)

    def test_switch_tabs_preserves_page(self, class_page: Page):
        """Switching from runtime → debug → runtime leaves the page intact."""
        _goto_monitor(class_page)

        # Switch to debug tab
        _switch_to_tab(class_page, "Debug")
        expect(class_page.locator(".monitor-page")).to_be_visible()

        # Switch back to runtime
        _switch_to_tab(class_page, "Runtime")
        expect(class_page.locator(".monitor-page")).to_be_visible()

        # Summary cards from the runtime tab should still be present
        expect(
            class_page.locator(".monitor-summary-card").first
        ).to_be_visible(timeout=5000)

    def test_debug_tab_has_issue_or_empty_state(self, class_page: Page):
        """The Debug tab renders either issue-list items **or** an empty-state
        placeholder – either way, the container debugging pane has content."""
        _goto_monitor(class_page)
        _switch_to_tab(class_page, "Debug")

        # The debug pane always has at least the two grid cards
        # ("Running Tasks Missing Containers" and "Orphan Running Containers").
        # Each one contains either an .issue-list or an n-empty component.
        debug_cards = class_page.locator(".monitor-card--stretch")
        expect(debug_cards.first).to_be_visible(timeout=5000)
        assert debug_cards.count() >= 2, (
            "Expected at least 2 stretch cards in the debug pane "
            f"(Running-Tasks + Orphan-Containers), got {debug_cards.count()}"
        )


# ===================================================================
#  Summary Card Detail Tests
# ===================================================================


@pytest.mark.monitor
class TestMonitorSummaryCards:
    """Deeper assertions on the overview summary cards that sit above the tabs."""

    def test_summary_card_has_label_and_value(self, class_page: Page):
        """Every summary card must contain a visible label and a numeric value."""
        _goto_monitor(class_page)
        class_page.wait_for_selector(".monitor-summary-card", timeout=10000)

        cards = class_page.locator(".monitor-summary-card")
        card_count = cards.count()
        assert card_count > 0, "No summary cards found"

        for i in range(card_count):
            card = cards.nth(i)
            label = card.locator(".summary-label")
            value = card.locator(".summary-value")
            expect(label).to_be_visible()
            expect(value).to_be_visible()
            # Label should have non-empty text
            assert label.inner_text().strip(), f"Summary card {i} has an empty label"
            # Value should have text (even "0" is valid)
            assert value.inner_text().strip() != "", (
                f"Summary card {i} has an empty value"
            )

    def test_summary_cards_minimum_count(self, class_page: Page):
        """The overview section should render at least 4 summary cards
        (Running Now, Backlog, Active Containers, Health Summary)."""
        _goto_monitor(class_page)
        class_page.wait_for_selector(".monitor-summary-card", timeout=10000)

        cards = class_page.locator(".monitor-summary-card")
        assert cards.count() >= 4, (
            f"Expected at least 4 overview summary cards, got {cards.count()}"
        )

    def test_summary_card_has_help_text(self, class_page: Page):
        """Each overview summary card includes a help/description paragraph."""
        _goto_monitor(class_page)
        class_page.wait_for_selector(".monitor-summary-card", timeout=10000)

        cards = class_page.locator(".monitor-summary-card")
        for i in range(cards.count()):
            help_el = cards.nth(i).locator(".summary-help")
            expect(help_el).to_be_attached()


# ===================================================================
#  Data / Content Card Tests
# ===================================================================


@pytest.mark.monitor
class TestMonitorDataCards:
    """Validate the runtime-tab content cards that display live data
    (Active Task Queue, Recent Finished Activity)."""

    def test_active_tasks_section_exists(self, class_page: Page):
        """The runtime tab includes an 'Active Task Queue' card."""
        _goto_monitor(class_page)

        # The card title is rendered as "Active Task Queue" (en i18n key)
        title = class_page.locator(".monitor-card__title").filter(
            has_text="Active Task"
        )
        expect(title.first).to_be_visible(timeout=10000)

    def test_recent_activity_section_exists(self, class_page: Page):
        """The runtime tab includes a 'Recent Finished Activity' card."""
        _goto_monitor(class_page)

        title = class_page.locator(".monitor-card__title").filter(
            has_text="Recent"
        )
        expect(title.first).to_be_visible(timeout=10000)

    def test_container_section_exists(self, class_page: Page):
        """The debug tab contains a 'Worker Containers' card with a header and body."""
        _goto_monitor(class_page)
        _switch_to_tab(class_page, "Debug")

        container_title = class_page.locator(".monitor-card__title").filter(
            has_text="Container"
        )
        expect(container_title.first).to_be_visible(timeout=5000)

        # The card should also have a body area (either data-table or empty state)
        container_card = class_page.locator(".monitor-card").filter(
            has=class_page.locator(".monitor-card__title", has_text="Container")
        )
        body = container_card.locator(".n-data-table, .n-empty")
        expect(body.first).to_be_visible(timeout=5000)

    def test_health_tab_has_health_checks(self, class_page: Page):
        """The Health tab renders at least one health-check item."""
        _goto_monitor(class_page)
        _switch_to_tab(class_page, "Health")

        checks = class_page.locator(".health-check")
        expect(checks.first).to_be_visible(timeout=5000)
        assert checks.count() >= 1, (
            f"Expected at least 1 health check, got {checks.count()}"
        )

    def test_health_tab_has_status_breakdown(self, class_page: Page):
        """The Health tab renders the status-breakdown bar chart."""
        _goto_monitor(class_page)
        _switch_to_tab(class_page, "Health")

        breakdown = class_page.locator(".status-breakdown")
        expect(breakdown).to_be_visible(timeout=5000)

        rows = class_page.locator(".status-breakdown__row")
        assert rows.count() >= 1, (
            f"Expected at least 1 status breakdown row, got {rows.count()}"
        )
