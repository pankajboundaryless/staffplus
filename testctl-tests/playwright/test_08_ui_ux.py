"""
TEST 08 — UI/UX Quality
All pages load without 500, 404s handled gracefully, long inputs, responsive.
"""

import pytest
from conftest import url, has_error

ALL_PAGES = [
    ("/dashboard",              "Dashboard"),
    ("/people",                 "People"),
    ("/projects",               "Projects"),
    ("/time/book",              "Book Time"),
    ("/time/timesheets",        "Timesheets"),
    ("/time/timer",             "Timer"),
    ("/time/approvals",         "Time Approvals"),
    ("/tasks",                  "Tasks"),
    ("/customers",              "Customers"),
    ("/invoicing",              "Invoices"),
    ("/invoicing/rate-cards",   "Rate Cards"),
    ("/subscriptions",          "Subscriptions"),
    ("/products",               "Products"),
    ("/reports",                "Reports"),
    ("/absence/my",             "My Absence"),
    ("/absence/team",           "Team Calendar"),
    ("/planning",               "Planning"),
    ("/simulations",            "Simulations"),
    ("/legal-entities",         "Legal Entities"),
    ("/admin/settings",         "Admin Settings"),
    ("/admin/users",            "Admin Users"),
    ("/admin/roles",            "Roles"),
    ("/admin/audit-log",        "Audit Log"),
    ("/admin/delegations",      "Delegations"),
    ("/admin/approval-rules",   "Approval Rules"),
    ("/holidays",               "Holiday Calendars"),
    ("/absence/policy",         "Holiday Policy"),
    ("/profile",                "Profile"),
    ("/settings",               "Settings"),
]


class TestAllPagesNoServerError:

    @pytest.mark.parametrize("path,label", ALL_PAGES)
    def test_page_has_no_500(self, page, path, label):
        """Every page must load without a 500 server error."""
        page.goto(url(path))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"Server error (500/Whoops) on {label} ({path})"
        assert "login" not in page.url, f"Session lost on {label}"

    @pytest.mark.parametrize("path,label", ALL_PAGES)
    def test_page_has_title(self, page, path, label):
        """Every page has a non-empty browser title."""
        page.goto(url(path))
        page.wait_for_load_state("networkidle")
        title = page.title()
        assert len(title.strip()) > 0, f"Empty title on {label} ({path})"
        assert title.strip() != "Untitled", f"Generic 'Untitled' title on {label}"


class TestFriendly404:

    def test_404_page_user_friendly(self, page):
        """404 shows a readable message, not a raw PHP error."""
        page.goto(url("/this-page-does-not-exist-xyz-abc-12345"))
        page.wait_for_load_state("networkidle")
        content = page.content()
        assert "Stack trace" not in content
        assert "/var/www" not in content
        has_message = any(x in content for x in ["404", "not found", "Not Found", "doesn't exist"])
        assert has_message or "dashboard" in page.url


class TestFormEdgeCases:

    def test_500_char_string_in_person_name(self, page):
        """Extremely long name input handled without 500."""
        page.goto(url("/people/new"))
        page.wait_for_load_state("networkidle")
        first = page.locator("input[name='first_name']")
        if first.count() == 0:
            pytest.skip("Person form not found")
        first.fill("A" * 500)
        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_load_state("networkidle")
        assert not has_error(page), "Server error on 500-char name — no length validation"

    def test_special_chars_in_search(self, page):
        """Special characters in search don't crash the app."""
        page.goto(url("/people"))
        page.wait_for_load_state("networkidle")
        search = page.locator("input[type='search'], input[name='search'], input[name='q']")
        if search.count() == 0:
            pytest.skip("No search field found")
        for chars in ["<>&\"'", "%%%", "🔥💀🚀"]:
            search.first.fill(chars)
            page.keyboard.press("Enter")
            page.wait_for_load_state("networkidle")
            assert not has_error(page), f"Server error on special chars: {chars}"
            search.first.clear()

    def test_future_date_in_time_entry(self, page):
        """Far-future date is handled gracefully."""
        page.goto(url("/time/book"))
        page.wait_for_load_state("networkidle")
        date = page.locator("input[name='date'], input[type='date']")
        if date.count() == 0:
            pytest.skip("Date field not found")
        date.first.fill("2099-12-31")
        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_load_state("networkidle")
        assert not has_error(page), "Server error on far-future date"

    def test_negative_hours_no_crash(self, page):
        """
        The duration field on /time/book is a time-format picker inside a day-card.
        The submit button lives inside a card that may not be visible at load time.
        We use JS to force a negative value then submit the first booking form
        directly — verifying the server does not return a 500 on bad input.
        """
        page.goto(url("/time/book"))
        page.wait_for_load_state("networkidle")

        hours_field = page.locator("input[name='hours'], input[name='duration']").first
        if hours_field.count() == 0:
            pytest.skip("Duration/hours field not found on /time/book")

        # Force negative value via JS (field may be inside a hidden card)
        page.evaluate(
            "el => { el.value = '-1'; el.dispatchEvent(new Event('change', {bubbles:true})); }",
            hours_field.element_handle()
        )

        # Submit the first booking form via JS (bypasses visibility constraint)
        submitted = page.evaluate("""() => {
            const form = document.querySelector('form[action*="time"], form[action*="book"]');
            if (!form) return false;
            form.submit();
            return true;
        }""")

        if not submitted:
            pytest.skip("No time booking form found to submit")

        page.wait_for_load_state("networkidle")
        assert not has_error(page), "Server error (500) on negative hours input"


class TestResponsiveLayout:

    VIEWPORTS = [
        {"name": "mobile",  "width": 375,  "height": 812},
        {"name": "tablet",  "width": 768,  "height": 1024},
        {"name": "desktop", "width": 1440, "height": 900},
    ]

    @pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: v["name"])
    def test_dashboard_no_error_at_viewport(self, page, vp):
        page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    @pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: v["name"])
    def test_no_horizontal_overflow(self, page, vp):
        """No horizontal scrollbar at any viewport."""
        page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        scroll_w = page.evaluate("document.body.scrollWidth")
        client_w = page.evaluate("document.body.clientWidth")
        assert scroll_w <= client_w + 20, \
            f"Horizontal overflow on {vp['name']} ({vp['width']}px): " \
            f"scrollWidth={scroll_w} > clientWidth={client_w}"
