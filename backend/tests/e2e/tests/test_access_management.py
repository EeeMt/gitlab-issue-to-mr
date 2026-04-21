"""
Access Management E2E Tests

Tests for the access management page where admins can manage user roles.

Test classes:
  - TestAccessManagement: Existing tests for role updates (serial, logged_in_page).
  - TestAccessManagementStructure: Read-only UI structure assertions (class_page).
  - TestAccessManagementInteractions: Search, filter, and revoke interactions (logged_in_page).
"""

import hashlib

import pytest
from playwright.sync_api import Page, expect



@pytest.mark.access
@pytest.mark.serial  # Modifies shared user/role state; requires serial execution.
class TestAccessManagement:
    """Tests for the access management logged_in_page."""

    @pytest.fixture(autouse=True)
    def extra_viewer_user(self, db_cursor, logged_in_page):
        """Insert a second user so the Save Access button is enabled for someone other than self."""
        password_hash = _hash_password("SecurePass123!")
        db_cursor.execute(
            """
            INSERT INTO users (
                username, display_name, email, auth_provider, local_password_hash,
                platform_role, platform_role_source, state, created_at, updated_at
            ) VALUES (
                'test_viewer', 'Test Viewer', 'viewer@test.example.com', 'local',
                %s, 'platform_user', 'manual', 'active', NOW(), NOW()
            )
            ON CONFLICT (username) DO UPDATE
                SET platform_role = 'platform_user',
                    local_password_hash = EXCLUDED.local_password_hash
            """,
            (password_hash,),
        )
        yield

    def _change_viewer_role(self, page: Page) -> None:
        """Helper: find the test_viewer card, change role to trigger dirty state."""
        # Wait for both user cards to be visible
        page.wait_for_selector(".user-management__card:nth-child(2)", state="visible", timeout=10000)

        # Find the viewer's card by display name and click its role select
        viewer_card = page.locator(".user-management__card").filter(has_text="Test Viewer")
        role_select = viewer_card.locator(".n-select").first
        role_select.locator(".n-base-selection").click()

        # Wait for dropdown portal; pick first option (Platform admin) scoped to the menu
        menu = page.locator(".n-base-select-menu")
        menu.wait_for(state="visible", timeout=5000)
        menu.locator(".n-base-select-option").first.click()
        # Give Vue one tick to process the selection before proceeding
        page.wait_for_timeout(300)

    def test_update_user_role_success(self, logged_in_page: Page, reset_database):
        """Test that updating a user's role shows success message."""
        logged_in_page.goto("/access-management")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("access-management-page")).to_be_visible()

        self._change_viewer_role(logged_in_page)

        # Save Access button for the viewer should now be enabled.
        save_buttons = logged_in_page.get_by_role("button", name="Save access")
        enabled_save = None
        for i in range(save_buttons.count()):
            btn = save_buttons.nth(i)
            if not btn.is_disabled():
                enabled_save = btn
                break
        assert enabled_save is not None, "Save Access button is still disabled after role change"
        enabled_save.click()

        # Wait for any toast message and verify it is a success (not error)
        logged_in_page.wait_for_selector(".n-message", state="visible", timeout=5000)
        assert logged_in_page.locator(".n-message--error").count() == 0, \
            "Error message appeared after saving role"
        assert "Updated access" in (logged_in_page.locator(".n-message").first.text_content() or ""), \
            "Expected success message text not found"

    def test_update_user_role_click_save_access(self, logged_in_page: Page, reset_database):
        """Test clicking Save Access button does not show an error."""
        logged_in_page.goto("/access-management")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("access-management-page")).to_be_visible()

        self._change_viewer_role(logged_in_page)

        save_buttons = logged_in_page.get_by_role("button", name="Save access")
        enabled_save = None
        for i in range(save_buttons.count()):
            btn = save_buttons.nth(i)
            if not btn.is_disabled():
                enabled_save = btn
                break
        assert enabled_save is not None, "Save Access button is still disabled after role change"
        enabled_save.click()

        # Verify no error message appeared.
        logged_in_page.wait_for_selector(".n-message", state="visible", timeout=5000)
        assert logged_in_page.locator(".n-message--error").count() == 0, \
            "Error message appeared after clicking Save Access"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: str = "e2e_salt") -> str:
    """Generate a PBKDF2 hash compatible with the backend's verify logic."""
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 1
    ).hex()
    return f"pbkdf2_sha256$1${salt}${digest}"


def _insert_user(
    db_cursor,
    *,
    username: str,
    display_name: str,
    email: str,
    role: str = "platform_user",
    state: str = "active",
) -> None:
    """Insert a test user directly into the database (idempotent)."""
    pw_hash = _hash_password("SecurePass123!", salt=f"salt_{username}")
    db_cursor.execute(
        """
        INSERT INTO users (
            username, display_name, email, auth_provider, local_password_hash,
            platform_role, platform_role_source, state, created_at, updated_at
        ) VALUES (
            %s, %s, %s, 'local', %s,
            %s, 'manual', %s, NOW(), NOW()
        )
        ON CONFLICT (username) DO NOTHING
        """,
        (username, display_name, email, pw_hash, role, state),
    )


# ---------------------------------------------------------------------------
# Read-only structure tests  (fast — share one browser context per module)
# ---------------------------------------------------------------------------

@pytest.mark.access
class TestAccessManagementStructure:
    """Read-only assertions on the Access Management page layout and widgets."""

    def test_page_header_visible(self, class_page: Page):
        """Header section with title and subtitle renders correctly."""
        class_page.goto("/access-management")
        class_page.wait_for_load_state("networkidle")

        header = class_page.get_by_test_id("access-management-header")
        expect(header).to_be_visible()
        expect(header).to_contain_text("Access Management")

    def test_summary_cards_visible(self, class_page: Page):
        """Summary stat cards are present and show expected labels."""
        class_page.goto("/access-management")
        class_page.wait_for_load_state("networkidle")

        summary = class_page.get_by_test_id("access-management-summary")
        expect(summary).to_be_visible()

        cards = class_page.get_by_test_id("access-management-summary-card")
        count = cards.count()
        assert count >= 3, f"Expected at least 3 summary cards, got {count}"

        # Each card should contain a label from the known set
        required_labels = {"Known Users", "Platform Admins", "Disabled Users"}
        found_labels = set()
        for i in range(count):
            text = cards.nth(i).text_content() or ""
            for label in required_labels:
                if label in text:
                    found_labels.add(label)
        assert required_labels.issubset(found_labels), (
            f"Expected at least labels {required_labels}, but found {found_labels}"
        )

    def test_search_input_visible(self, class_page: Page):
        """Search input box is present with the expected placeholder text."""
        class_page.goto("/access-management")
        class_page.wait_for_load_state("networkidle")

        search = class_page.get_by_test_id("access-management-search")
        expect(search).to_be_visible()

        # The placeholder lives on the inner <input> element
        search_input = search.locator("input")
        expect(search_input).to_have_attribute(
            "placeholder", "Search by username, display name, or email"
        )

    def test_role_filter_visible(self, class_page: Page):
        """Role filter dropdown is present and can be opened."""
        class_page.goto("/access-management")
        class_page.wait_for_load_state("networkidle")

        role_filter = class_page.get_by_test_id("access-management-role-filter")
        expect(role_filter).to_be_visible()

        # Open the dropdown and verify options exist
        role_filter.locator(".n-base-selection").click()
        menu = class_page.locator(".n-base-select-menu")
        menu.wait_for(state="visible", timeout=5000)
        options = menu.locator(".n-base-select-option")
        expect(options).to_have_count(2)

        # Close the dropdown by pressing Escape
        class_page.keyboard.press("Escape")

    def test_state_filter_visible(self, class_page: Page):
        """State filter dropdown is present and offers active/disabled options."""
        class_page.goto("/access-management")
        class_page.wait_for_load_state("networkidle")

        state_filter = class_page.get_by_test_id("access-management-state-filter")
        expect(state_filter).to_be_visible()

        # Open and verify the two options
        state_filter.locator(".n-base-selection").click()
        menu = class_page.locator(".n-base-select-menu")
        menu.wait_for(state="visible", timeout=5000)
        options = menu.locator(".n-base-select-option")
        expect(options).to_have_count(2)

        class_page.keyboard.press("Escape")

    def test_user_cards_displayed(self, class_page: Page):
        """At least one user card is visible (the logged-in admin user)."""
        class_page.goto("/access-management")
        class_page.wait_for_load_state("networkidle")

        user_cards = class_page.get_by_test_id("access-management-user-card")
        # Wait for the first card to appear (data is loaded async)
        expect(user_cards.first).to_be_visible(timeout=10000)
        assert user_cards.count() >= 1, "Expected at least one user card"

        # One of the cards should carry a "Current user" tag (not necessarily the first)
        all_text = ""
        for i in range(user_cards.count()):
            all_text += user_cards.nth(i).text_content() or ""
        assert "Current user" in all_text, (
            "Expected at least one user card to show 'Current user' tag"
        )

    def test_current_user_save_button_disabled(self, class_page: Page):
        """Save and Revoke buttons on the current user card are disabled."""
        class_page.goto("/access-management")
        class_page.wait_for_load_state("networkidle")

        # Find the card that contains "Current user"
        current_card = class_page.get_by_test_id("access-management-user-card").filter(
            has_text="Current user"
        )
        expect(current_card).to_be_visible(timeout=10000)

        save_btn = current_card.get_by_test_id("access-management-save-button")
        expect(save_btn).to_be_disabled()

        revoke_btn = current_card.get_by_test_id("access-management-revoke-button")
        expect(revoke_btn).to_be_disabled()

    def test_current_user_self_readonly_hint(self, class_page: Page):
        """Current user card shows a read-only hint explaining self-edit restriction."""
        class_page.goto("/access-management")
        class_page.wait_for_load_state("networkidle")

        current_card = class_page.get_by_test_id("access-management-user-card").filter(
            has_text="Current user"
        )
        expect(current_card).to_be_visible(timeout=10000)
        expect(current_card).to_contain_text("read-only here to avoid accidental lockout")


# ---------------------------------------------------------------------------
# Interaction tests  (isolated — each test gets its own page + DB reset)
# ---------------------------------------------------------------------------

@pytest.mark.access
class TestAccessManagementInteractions:
    """Tests that modify data or exercise interactive widgets on Access Management."""

    def test_search_filters_users(self, logged_in_page: Page, db_cursor, reset_database):
        """Typing in the search box filters user cards by username/name/email."""
        # Insert two extra users so we can verify filtering
        _insert_user(
            db_cursor,
            username="alice_search",
            display_name="Alice SearchUser",
            email="alice_search@test.example.com",
        )
        _insert_user(
            db_cursor,
            username="bob_search",
            display_name="Bob SearchUser",
            email="bob_search@test.example.com",
        )

        logged_in_page.goto("/access-management")
        logged_in_page.wait_for_load_state("networkidle")

        user_cards = logged_in_page.get_by_test_id("access-management-user-card")
        # Wait for cards to load — we should see at least 3 (admin + alice + bob)
        logged_in_page.wait_for_selector(
            "[data-testid='access-management-user-card']", timeout=10000
        )
        initial_count = user_cards.count()
        assert initial_count >= 3, f"Expected ≥3 user cards, got {initial_count}"

        # Type a search term that matches only alice
        search_input = logged_in_page.get_by_test_id("access-management-search").locator("input")
        search_input.fill("alice_search")
        # Allow Vue reactivity to update the filtered list
        logged_in_page.wait_for_timeout(500)

        filtered_count = user_cards.count()
        assert filtered_count == 1, (
            f"Expected exactly 1 user card matching 'alice_search', got {filtered_count}"
        )
        expect(user_cards.first).to_contain_text("Alice SearchUser")

        # Clear the search and verify all cards reappear
        search_input.fill("")
        logged_in_page.wait_for_timeout(500)
        assert user_cards.count() >= 3, "Cards should reappear after clearing search"

    def test_role_filter_filters_users(self, logged_in_page: Page, db_cursor, reset_database):
        """Selecting a role from the role filter limits cards to that role."""
        # Insert a platform_user so we have at least one of each role
        _insert_user(
            db_cursor,
            username="viewer_filter",
            display_name="Viewer FilterUser",
            email="viewer_filter@test.example.com",
            role="platform_user",
        )

        logged_in_page.goto("/access-management")
        logged_in_page.wait_for_load_state("networkidle")

        user_cards = logged_in_page.get_by_test_id("access-management-user-card")
        logged_in_page.wait_for_selector(
            "[data-testid='access-management-user-card']", timeout=10000
        )
        initial_count = user_cards.count()
        assert initial_count >= 2, f"Expected ≥2 user cards, got {initial_count}"

        # Open role filter and select "Platform admin"
        role_filter = logged_in_page.get_by_test_id("access-management-role-filter")
        role_filter.locator(".n-base-selection").click()
        menu = logged_in_page.locator(".n-base-select-menu")
        menu.wait_for(state="visible", timeout=5000)
        # First option is "Platform admin"
        menu.locator(".n-base-select-option").first.click()
        logged_in_page.wait_for_timeout(500)

        # All remaining cards should be platform_admin (contain "Platform admin" tag)
        filtered_cards = logged_in_page.get_by_test_id("access-management-user-card")
        for i in range(filtered_cards.count()):
            card_text = filtered_cards.nth(i).text_content() or ""
            assert "Platform admin" in card_text, (
                f"Card {i} should be Platform admin after filtering, text: {card_text[:100]}"
            )

        # The viewer we inserted should NOT be visible
        viewer_card = filtered_cards.filter(has_text="Viewer FilterUser")
        expect(viewer_card).to_have_count(0)

    def test_state_filter_filters_users(self, logged_in_page: Page, db_cursor, reset_database):
        """Selecting 'disabled' from the state filter hides active users."""
        # Insert a disabled user
        _insert_user(
            db_cursor,
            username="disabled_user",
            display_name="Disabled TestUser",
            email="disabled_user@test.example.com",
            state="disabled",
        )

        logged_in_page.goto("/access-management")
        logged_in_page.wait_for_load_state("networkidle")

        user_cards = logged_in_page.get_by_test_id("access-management-user-card")
        logged_in_page.wait_for_selector(
            "[data-testid='access-management-user-card']", timeout=10000
        )

        # Open state filter and select "Disabled"
        state_filter = logged_in_page.get_by_test_id("access-management-state-filter")
        state_filter.locator(".n-base-selection").click()
        menu = logged_in_page.locator(".n-base-select-menu")
        menu.wait_for(state="visible", timeout=5000)
        # Second option is "Disabled"
        menu.locator(".n-base-select-option").nth(1).click()
        logged_in_page.wait_for_timeout(500)

        # Only the disabled user should remain visible
        filtered_cards = logged_in_page.get_by_test_id("access-management-user-card")
        assert filtered_cards.count() >= 1, "Expected at least one disabled user card"
        expect(filtered_cards.first).to_contain_text("Disabled TestUser")

        # The admin user (active) should NOT appear
        admin_card = filtered_cards.filter(has_text="Current user")
        expect(admin_card).to_have_count(0)

    def test_revoke_sessions_button(self, logged_in_page: Page, db_cursor, reset_database):
        """Clicking Revoke sessions on a non-current user shows a success message."""
        # Insert a second user whose sessions we can revoke
        _insert_user(
            db_cursor,
            username="revoke_target",
            display_name="Revoke Target",
            email="revoke_target@test.example.com",
        )

        logged_in_page.goto("/access-management")
        logged_in_page.wait_for_load_state("networkidle")

        # Wait for user cards to load
        logged_in_page.wait_for_selector(
            "[data-testid='access-management-user-card']", timeout=10000
        )

        # Locate the target user's card (not the current admin user)
        target_card = logged_in_page.get_by_test_id("access-management-user-card").filter(
            has_text="Revoke Target"
        )
        expect(target_card).to_be_visible()

        # The revoke button on this card should be enabled (not the current user)
        revoke_btn = target_card.get_by_test_id("access-management-revoke-button")
        expect(revoke_btn).to_be_enabled()
        revoke_btn.click()

        # A toast message should appear — either "Revoked … session(s)" or "No active sessions"
        logged_in_page.wait_for_selector(".n-message", state="visible", timeout=5000)
        assert logged_in_page.locator(".n-message--error").count() == 0, (
            "Error toast appeared after revoking sessions"
        )
        toast_text = logged_in_page.locator(".n-message").first.text_content() or ""
        assert "revoke_target" in toast_text.lower() or "session" in toast_text.lower(), (
            f"Expected session revocation message mentioning user/sessions, got: {toast_text}"
        )
