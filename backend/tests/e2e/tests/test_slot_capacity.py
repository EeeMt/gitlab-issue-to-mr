"""
Slot Capacity E2E Tests

Tests for the slot-capacity feature across multiple pages:
- Config page: slot_max_tasks and slot_max_tasks_enforce form fields
- Config persistence: save, reload, verify round-trip
- CreateTask page: slot warning elements and submit button state
- ScheduleOverview page: slot capacity summary cards
- HeatmapChart: "Full" legend indicator
"""

import pytest
from playwright.sync_api import Page, expect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_for_config_tab(page: Page):
    """Wait for the config tabs container to be rendered."""
    page.wait_for_selector(".config-tabs", timeout=10000)


def _goto_runtime(page: Page):
    """Navigate to the runtime settings tab and wait for data to load."""
    page.goto("/config?tab=runtime", wait_until="networkidle")
    _wait_for_config_tab(page)


def _get_slot_max_tasks_input(page: Page):
    """Locate the n-input-number <input> for 'Max Tasks per Hour Slot'."""
    form_item = page.locator(".n-form-item").filter(
        has_text="Max Tasks per Hour Slot"
    )
    return form_item.locator(".n-input-number input")


def _get_enforce_switch(page: Page):
    """Locate the role='switch' element for 'Enforce Slot Limit'."""
    form_item = page.locator(".n-form-item").filter(
        has_text="Enforce Slot Limit"
    )
    # Naive UI renders NSwitch as <div role="switch">, not <button>
    return form_item.locator("[role='switch']")


def _set_slot_max_tasks(page: Page, value: int):
    """Fill slot_max_tasks and blur so the form becomes dirty.

    Clears the field first with triple-click + delete to ensure the form
    detects a change even when the existing value equals `value`.
    """
    input_el = _get_slot_max_tasks_input(page)
    input_el.click(click_count=3)          # select all existing text
    input_el.press("Backspace")            # clear → triggers dirty
    input_el.fill(str(value))
    input_el.press("Tab")


def _save_runtime_and_wait(page: Page):
    """Click 'Save changes' in the runtime panel and wait for the API round-trip."""
    save_btn = page.get_by_role("button", name="Save changes").first
    # The button is disabled while the form is clean; wait for it to become
    # enabled after our edits have been detected by Vue reactivity.
    expect(save_btn).to_be_enabled(timeout=5000)
    save_btn.click()
    # Wait for the save to complete — button becomes disabled when form is clean.
    expect(save_btn).to_be_disabled(timeout=10000)


def _set_slot_config_via_ui(page: Page, max_tasks: int):
    """End-to-end helper: open config, set slot_max_tasks, save."""
    _goto_runtime(page)
    _set_slot_max_tasks(page, max_tasks)
    _save_runtime_and_wait(page)


# ---------------------------------------------------------------------------
# 1. Config page – Slot Capacity form structure (read-only)
# ---------------------------------------------------------------------------

@pytest.mark.config_tabs
@pytest.mark.slot_capacity
class TestSlotCapacityConfigStructure:
    """Verify that slot capacity form elements are present on the runtime tab."""

    def test_slot_capacity_section_heading(self, class_page: Page):
        """The 'Slot Capacity' section heading is visible."""
        _goto_runtime(class_page)
        heading = class_page.get_by_text("Slot Capacity", exact=True)
        expect(heading).to_be_visible()

    def test_slot_max_tasks_input_exists(self, class_page: Page):
        """A number input for 'Max Tasks per Hour Slot' is visible."""
        _goto_runtime(class_page)
        form_item = class_page.locator(".n-form-item").filter(
            has_text="Max Tasks per Hour Slot"
        )
        expect(form_item).to_be_visible()
        input_number = form_item.locator(".n-input-number")
        expect(input_number).to_be_visible()

    def test_slot_max_tasks_enforce_switch_exists(self, class_page: Page):
        """A toggle switch for 'Enforce Slot Limit' is visible."""
        _goto_runtime(class_page)
        form_item = class_page.locator(".n-form-item").filter(
            has_text="Enforce Slot Limit"
        )
        expect(form_item).to_be_visible()
        switch = form_item.locator(".n-switch")
        expect(switch).to_be_visible()

    def test_slot_max_tasks_hint_text(self, class_page: Page):
        """Hint text explains the max-tasks field."""
        _goto_runtime(class_page)
        hint = class_page.get_by_text(
            "Maximum number of tasks that can be scheduled"
        )
        expect(hint).to_be_visible()

    def test_slot_enforce_hint_text(self, class_page: Page):
        """Hint text explains the enforce toggle."""
        _goto_runtime(class_page)
        hint = class_page.get_by_text("When enabled, reject task creation")
        expect(hint).to_be_visible()

    def test_save_and_revert_buttons_present(self, class_page: Page):
        """Save and Revert buttons are visible in the runtime section."""
        _goto_runtime(class_page)
        save_btn = class_page.get_by_role("button", name="Save changes").first
        expect(save_btn).to_be_visible()
        revert_btn = class_page.get_by_role(
            "button", name="Revert changes"
        ).first
        expect(revert_btn).to_be_visible()


# ---------------------------------------------------------------------------
# 2. Config page – Slot Capacity persistence round-trips
# ---------------------------------------------------------------------------

@pytest.mark.config_tabs
@pytest.mark.slot_capacity
@pytest.mark.serial
class TestSlotCapacityConfigPersistence:
    """Verify that slot capacity settings persist across page reloads."""

    @pytest.fixture(autouse=True)
    def _reset_slot_config(self, db_cursor):
        """Reset slot config to defaults before each test to avoid stale state."""
        db_cursor.execute(
            "DELETE FROM system_config WHERE key IN ('slot_max_tasks', 'slot_max_tasks_enforce')"
        )
        yield
        db_cursor.execute(
            "DELETE FROM system_config WHERE key IN ('slot_max_tasks', 'slot_max_tasks_enforce')"
        )

    def test_save_slot_max_tasks_value(self, logged_in_page: Page):
        """Set slot_max_tasks to 5, save, reload, verify it persisted."""
        _goto_runtime(logged_in_page)
        _set_slot_max_tasks(logged_in_page, 5)
        _save_runtime_and_wait(logged_in_page)

        # Reload and verify
        _goto_runtime(logged_in_page)
        input_el = _get_slot_max_tasks_input(logged_in_page)
        expect(input_el).to_have_value("5")

    def test_toggle_enforce_on_persists(self, logged_in_page: Page):
        """Toggle slot_max_tasks_enforce ON, save, reload, verify persisted."""
        _goto_runtime(logged_in_page)

        switch = _get_enforce_switch(logged_in_page)
        # Ensure it starts off (click twice if already on)
        if switch.get_attribute("aria-checked") == "true":
            switch.click()
            _save_runtime_and_wait(logged_in_page)
            _goto_runtime(logged_in_page)
            switch = _get_enforce_switch(logged_in_page)

        expect(switch).to_have_attribute("aria-checked", "false")
        switch.click()
        expect(switch).to_have_attribute("aria-checked", "true")
        _save_runtime_and_wait(logged_in_page)

        # Reload and verify
        _goto_runtime(logged_in_page)
        switch = _get_enforce_switch(logged_in_page)
        expect(switch).to_have_attribute("aria-checked", "true")

    def test_save_both_slot_settings(self, logged_in_page: Page):
        """Set slot_max_tasks=3 and enforce=ON together, then verify both."""
        _goto_runtime(logged_in_page)

        _set_slot_max_tasks(logged_in_page, 3)

        switch = _get_enforce_switch(logged_in_page)
        if switch.get_attribute("aria-checked") == "false":
            switch.click()
        expect(switch).to_have_attribute("aria-checked", "true")

        _save_runtime_and_wait(logged_in_page)

        # Reload and verify both
        _goto_runtime(logged_in_page)
        input_el = _get_slot_max_tasks_input(logged_in_page)
        expect(input_el).to_have_value("3")
        switch = _get_enforce_switch(logged_in_page)
        expect(switch).to_have_attribute("aria-checked", "true")

    def test_reset_slot_max_tasks_to_zero(self, logged_in_page: Page):
        """Set slot_max_tasks back to 0 (unlimited), save, verify."""
        # First ensure it's non-zero so the change makes the form dirty
        _goto_runtime(logged_in_page)
        _set_slot_max_tasks(logged_in_page, 7)
        _save_runtime_and_wait(logged_in_page)

        # Now set to 0
        _goto_runtime(logged_in_page)
        _set_slot_max_tasks(logged_in_page, 0)
        _save_runtime_and_wait(logged_in_page)

        # Reload and verify
        _goto_runtime(logged_in_page)
        input_el = _get_slot_max_tasks_input(logged_in_page)
        expect(input_el).to_have_value("0")


# ---------------------------------------------------------------------------
# 3. CreateTask page – Slot warning elements
# ---------------------------------------------------------------------------

@pytest.mark.create_task
@pytest.mark.slot_capacity
class TestCreateTaskSlotElements:
    """Verify slot-capacity-related elements on the Create Task page."""

    def _goto_create_task(self, page: Page):
        page.goto("/create-task")
        page.wait_for_load_state("networkidle")

    def test_submit_button_exists(self, class_page: Page):
        """The submit button with data-testid is present."""
        self._goto_create_task(class_page)
        btn = class_page.get_by_test_id("create-task-submit-button")
        expect(btn).to_be_visible()

    def test_slot_warning_not_visible_by_default(self, class_page: Page):
        """No slot warning alert shown when no schedule time is selected."""
        self._goto_create_task(class_page)
        warning = class_page.locator(".slot-warning")
        expect(warning).to_have_count(0)

    def test_submit_button_not_disabled_by_default(self, class_page: Page):
        """Submit button is enabled when no schedule time is selected."""
        self._goto_create_task(class_page)
        btn = class_page.get_by_test_id("create-task-submit-button")
        expect(btn).not_to_be_disabled()


# ---------------------------------------------------------------------------
# 4. ScheduleOverview page – Slot capacity summary cards
# ---------------------------------------------------------------------------

@pytest.mark.schedule_overview
@pytest.mark.slot_capacity
class TestScheduleOverviewSlotCapacity:
    """Verify slot capacity cards appear / disappear based on config."""

    def test_page_loads(self, class_page: Page):
        """The schedule overview page loads."""
        class_page.goto("/schedule-overview")
        class_page.wait_for_load_state("networkidle")
        class_page.wait_for_selector(".schedule-overview__hero", timeout=15000)
        container = class_page.locator(".schedule-overview")
        expect(container).to_be_visible()

    def test_summary_cards_visible(self, class_page: Page):
        """At least one summary card is rendered."""
        class_page.goto("/schedule-overview")
        class_page.wait_for_load_state("networkidle")
        class_page.wait_for_selector(".schedule-overview__hero", timeout=15000)
        cards = class_page.locator(".schedule-summary-card")
        expect(cards.first).to_be_visible()


@pytest.mark.schedule_overview
@pytest.mark.slot_capacity
@pytest.mark.serial
class TestScheduleOverviewSlotCapacityConfig:
    """Verify slot capacity cards depend on slot_max_tasks config value."""

    @pytest.fixture(autouse=True)
    def _reset_slot_config(self, db_cursor):
        """Reset slot config to defaults before each test."""
        db_cursor.execute(
            "DELETE FROM system_config WHERE key IN ('slot_max_tasks', 'slot_max_tasks_enforce')"
        )
        yield
        db_cursor.execute(
            "DELETE FROM system_config WHERE key IN ('slot_max_tasks', 'slot_max_tasks_enforce')"
        )

    def test_slot_capacity_card_visible_when_configured(
        self, logged_in_page: Page
    ):
        """When slot_max_tasks > 0, a 'Slot Capacity' summary card appears."""
        _set_slot_config_via_ui(logged_in_page, max_tasks=5)

        logged_in_page.goto("/schedule-overview")
        logged_in_page.wait_for_selector(
            ".schedule-overview__hero", timeout=10000
        )
        slot_card = logged_in_page.get_by_text("Slot Capacity")
        expect(slot_card).to_be_visible(timeout=5000)

    def test_full_slots_card_visible_when_configured(
        self, logged_in_page: Page
    ):
        """When slot_max_tasks > 0, a 'Full Slots' summary card appears."""
        _set_slot_config_via_ui(logged_in_page, max_tasks=8)

        logged_in_page.goto("/schedule-overview")
        logged_in_page.wait_for_selector(
            ".schedule-overview__hero", timeout=10000
        )
        full_slots = logged_in_page.get_by_text("Full Slots")
        expect(full_slots).to_be_visible(timeout=5000)

    def test_slot_capacity_card_hidden_when_zero(self, logged_in_page: Page):
        """When slot_max_tasks = 0, no 'Slot Capacity' card appears."""
        # First set non-zero so the subsequent zero actually takes effect
        _set_slot_config_via_ui(logged_in_page, max_tasks=3)
        _set_slot_config_via_ui(logged_in_page, max_tasks=0)

        logged_in_page.goto("/schedule-overview")
        logged_in_page.wait_for_selector(
            ".schedule-overview__hero", timeout=10000
        )
        # Wait for the page to fully render its summary cards
        logged_in_page.wait_for_load_state("networkidle")

        slot_text = logged_in_page.locator(
            ".schedule-summary-card"
        ).filter(has_text="Slot Capacity")
        expect(slot_text).to_have_count(0)


# ---------------------------------------------------------------------------
# 5. HeatmapChart – Capacity visual indicators
# ---------------------------------------------------------------------------

@pytest.mark.schedule_overview
@pytest.mark.slot_capacity
class TestHeatmapLegend:
    """Verify the heatmap legend renders on the schedule overview page."""

    def _goto_schedule(self, page: Page):
        page.goto("/schedule-overview")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".schedule-overview__hero", timeout=15000)

    def test_heatmap_legend_visible(self, class_page: Page):
        """The heatmap legend bar is visible."""
        self._goto_schedule(class_page)
        legend = class_page.locator(".heatmap-chart__legend")
        expect(legend.first).to_be_visible(timeout=5000)

    def test_heatmap_legend_has_light_and_busy_labels(self, class_page: Page):
        """The legend shows 'Light' and 'Busy' baseline labels."""
        self._goto_schedule(class_page)
        legend = class_page.locator(".heatmap-chart__legend").first
        expect(legend.get_by_text("Light")).to_be_visible()
        expect(legend.get_by_text("Busy")).to_be_visible()


@pytest.mark.schedule_overview
@pytest.mark.slot_capacity
@pytest.mark.serial
class TestHeatmapFullIndicator:
    """Verify 'Full' legend appears only when slot capacity is configured."""

    @pytest.fixture(autouse=True)
    def _reset_slot_config(self, db_cursor):
        """Reset slot config to defaults before each test."""
        db_cursor.execute(
            "DELETE FROM system_config WHERE key IN ('slot_max_tasks', 'slot_max_tasks_enforce')"
        )
        yield
        db_cursor.execute(
            "DELETE FROM system_config WHERE key IN ('slot_max_tasks', 'slot_max_tasks_enforce')"
        )

    def test_full_legend_visible_when_capacity_set(
        self, logged_in_page: Page
    ):
        """When slot_max_tasks > 0, the 'Full' swatch and label appear."""
        _set_slot_config_via_ui(logged_in_page, max_tasks=5)

        logged_in_page.goto("/schedule-overview")
        logged_in_page.wait_for_selector(
            ".schedule-overview__hero", timeout=10000
        )

        full_swatch = logged_in_page.locator(
            ".heatmap-chart__legend-swatch--full"
        )
        expect(full_swatch.first).to_be_visible(timeout=5000)

        full_label = logged_in_page.locator(
            ".heatmap-chart__legend"
        ).first.get_by_text("Full")
        expect(full_label).to_be_visible()

    def test_full_legend_hidden_when_capacity_zero(
        self, logged_in_page: Page
    ):
        """When slot_max_tasks = 0, the 'Full' swatch is absent."""
        # Ensure we go from non-zero to zero
        _set_slot_config_via_ui(logged_in_page, max_tasks=4)
        _set_slot_config_via_ui(logged_in_page, max_tasks=0)

        logged_in_page.goto("/schedule-overview")
        logged_in_page.wait_for_selector(
            ".schedule-overview__hero", timeout=10000
        )
        logged_in_page.wait_for_load_state("networkidle")

        full_swatch = logged_in_page.locator(
            ".heatmap-chart__legend-swatch--full"
        )
        expect(full_swatch).to_have_count(0)
