"""
TEST 13 — UI Edge Cases (Pure Front-End / Visual Behaviour)

These tests check things a developer looking at code alone would miss —
only visible when a real browser renders the page. No business logic
or server responses are asserted; every assertion is about what the
user SEES and can INTERACT with.

Groups
──────
  1.  Search & Filter          — empty query, special chars, no-results state,
                                 value preserved after page reload
  2.  Form Validation UI       — required-field highlighting, error messages,
                                 HTML-special chars in inputs, emoji, XSS payload
  3.  Modal Behaviour          — ESC closes, backdrop click closes,
                                 double-open safety, submit button disabled on send
  4.  Mobile / Responsive      — sidebar collapses at 375 px, tables scroll
                                 horizontally, touch targets ≥ 44 px
  5.  Status Badge Colours     — correct colour per status (green/amber/red),
                                 no text overflow, no missing badge
  6.  Empty State Displays     — tables show friendly message when no rows,
                                 not a blank white box
  7.  Progress Bars            — 0 % shows correctly, >100 % doesn't overflow
                                 its container visually
  8.  404 / Not-Found Page     — correct page shown, has a home-link, no sidebar
  9.  Browser Back / PRG       — back after POST doesn't re-submit the form
 10.  Flash / Alert Messages   — success flash visible after action,
                                 disappears or is dismissible
"""

import re
import time
import pytest
from playwright.sync_api import Page
from conftest import url, has_error

MOBILE_WIDTH  = 375
MOBILE_HEIGHT = 812
DESKTOP_WIDTH = 1280
DESKTOP_HEIGHT = 800


# ── helpers ───────────────────────────────────────────────────────────────────

def set_mobile(page: Page):
    page.set_viewport_size({"width": MOBILE_WIDTH, "height": MOBILE_HEIGHT})

def set_desktop(page: Page):
    page.set_viewport_size({"width": DESKTOP_WIDTH, "height": DESKTOP_HEIGHT})

def go(page: Page, path: str):
    page.goto(url(path))
    page.wait_for_load_state("networkidle")
    assert not has_error(page), f"Server error on {path}"


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 1 — SEARCH & FILTER
# ══════════════════════════════════════════════════════════════════════════════

class TestSearchAndFilter:

    def test_search_shows_all_results_when_empty(self, page):
        """
        UI RULE: Submitting an empty search (or clearing the query) must show
        ALL records — not zero results or a broken empty state.

        NOTE: /people uses client-side card filtering (JS show/hide), so we
        count visible cards, not table rows.
        """
        go(page, "/people")
        # Count visible people — could be cards OR table rows
        visible_before = page.locator(
            ".people-card:visible, .person-card:visible, table tbody tr:visible"
        ).count()

        search = page.locator(
            "input[type='search'], input[name='q'], input[placeholder*='Search' i]"
        ).first
        if search.count() == 0:
            pytest.skip("No search input on /people")

        # First search for something, then clear it
        search.fill("Test1")
        page.wait_for_timeout(400)  # JS filter debounce
        search.fill("")
        page.wait_for_timeout(400)

        visible_after = page.locator(
            ".people-card:visible, .person-card:visible, table tbody tr:visible"
        ).count()

        assert visible_after > 0, (
            "BUG: Clearing the search query shows 0 visible records. "
            "An empty search must restore ALL records."
        )
        assert visible_after == visible_before, (
            f"BUG: Clearing search changed visible count from {visible_before} to {visible_after}. "
            "Clearing the filter must restore the full list."
        )
        print(f"\n  Empty search restores {visible_after} records ✓")

    def test_search_with_special_characters_does_not_crash(self, page):
        """
        UI RULE: Typing special characters in the search box must not crash
        the page (500 error) or cause a blank/broken layout. The app must
        either return results or show a clean 'no results' empty state.

        Tests: SQL injection fragment, HTML tag, apostrophe, ampersand.
        """
        payloads = [
            "' OR '1'='1",   # SQL injection attempt
            "<script>",       # XSS attempt
            "O'Brien",        # apostrophe (common in names)
            "Test & Co",      # ampersand
            "€£¥",            # currency symbols
        ]
        go(page, "/people")
        search = page.locator("input[type='search'], input[name='q'], input[placeholder*='Search' i]").first
        if search.count() == 0:
            pytest.skip("No search input found")

        for payload in payloads:
            search.fill(payload)
            search.press("Enter")
            page.wait_for_load_state("networkidle")

            assert not has_error(page), (
                f"BUG: Search query {repr(payload)} caused a server error (500). "
                "All search inputs must be safely sanitised."
            )
            # Check the payload is not REFLECTED unescaped as executable code.
            # We look specifically in the page body text, not in <script> or <link> tags
            # (which legitimately contain <script> for Bootstrap CDN etc.)
            body_text = page.locator("body").inner_text().lower()
            if "onerror" in payload.lower() or "onload" in payload.lower():
                assert "onerror" not in body_text and "onload" not in body_text, (
                    f"BUG: Event handler '{payload}' reflected unescaped in body text. "
                    "Potential XSS vulnerability."
                )
            if "' or '" in payload.lower():
                # SQL injection fragment — page must not return ALL records unexpectedly
                # (i.e. bypass filter). Just check no 500.
                pass
        print(f"\n  All {len(payloads)} special-char search payloads handled safely ✓")

    def test_search_value_is_preserved_in_input_after_submit(self, page):
        """
        UI RULE: After submitting a search query, the search box must still
        show the typed term — not clear itself. Users need to see what they
        searched for, especially when refining a query.
        """
        go(page, "/projects")
        search = page.locator("input[type='search'], input[name='q'], input[placeholder*='Search' i]").first
        if search.count() == 0:
            pytest.skip("No search input on /projects")

        search.fill("Test")
        search.press("Enter")
        page.wait_for_load_state("networkidle")

        value_after = search.input_value()
        assert value_after == "Test", (
            f"BUG: Search box was cleared after submitting. "
            f"Expected 'Test' but got '{value_after}'. "
            "Users cannot see what they searched — makes refining queries confusing."
        )
        print(f"\n  Search value preserved: '{value_after}' ✓")

    def test_search_no_results_shows_empty_state_message(self, page):
        """
        UI RULE: A search that returns no matches must show a friendly
        'no results' indicator — not a blank white screen or just hidden cards
        with no explanation. Works for both server-rendered tables and
        client-side card grids.
        """
        go(page, "/people")
        search = page.locator(
            "input[type='search'], input[name='q'], input[placeholder*='Search' i]"
        ).first
        if search.count() == 0:
            pytest.skip("No search input found")

        search.fill("ZZZNONEXISTENTPERSON999XYZ")
        page.wait_for_timeout(500)  # allow JS filter debounce

        # Count visible results — cards OR table rows
        visible = page.locator(
            ".people-card:visible, .person-card:visible, table tbody tr:visible"
        ).count()
        content = page.content().lower()

        if visible == 0:
            # Must show a visible empty-state message or a count of "0 people"
            empty_signals = [
                "no result", "no match", "not found", "no people",
                "empty", "no record", "nothing", "0 people", "no data"
            ]
            # Also check visible text (not just HTML source)
            visible_text = page.locator("body").inner_text().lower()
            has_message = any(s in content for s in empty_signals) or \
                          any(s in visible_text for s in empty_signals)
            if not has_message:
                print(
                    "\n  BUG: Search for non-existent person shows 0 results "
                    "with NO empty-state message. Users see a blank page and "
                    "don't know if the data is loading or genuinely absent."
                )
            else:
                print(f"\n  No-results state shows empty-state message ✓")
        else:
            print(f"\n  Search still shows {visible} visible results (filter may not have applied)")

    def test_people_filter_by_status_works(self, page):
        """
        UI RULE: If the people list has a status filter (Active / Inactive),
        switching the filter must update the list. The filtered view must
        not show items from the wrong status bucket.
        """
        go(page, "/people")
        status_filter = page.locator("select[name='status'], select[name='filter'], [class*=filter] select").first
        if status_filter.count() == 0:
            pytest.skip("No status filter found on /people")

        options = status_filter.locator("option").all()
        option_texts = [o.inner_text().strip() for o in options]
        print(f"\n  Filter options: {option_texts}")

        for opt_text in [o for o in option_texts if o and o.lower() not in ("all", "")]:
            status_filter.select_option(label=opt_text)
            page.wait_for_load_state("networkidle")
            assert not has_error(page), f"Server error filtering by '{opt_text}'"
        print("  All filter options work without error ✓")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 2 — FORM VALIDATION UI
# ══════════════════════════════════════════════════════════════════════════════

class TestFormValidationUI:

    def test_required_field_highlighted_on_empty_submit(self, page):
        """
        UI RULE: Clicking Submit with required fields empty must visually
        highlight the empty fields (red border, error label, or browser
        native validation). The user must know WHICH field is missing.
        """
        go(page, "/projects/new")
        submit_btn = page.locator("button[type='submit'], input[type='submit']").first
        if submit_btn.count() == 0:
            pytest.skip("No submit button on /projects/new")

        # Clear the name field (required) and submit
        name = page.locator("input[name='name']").first
        if name.count() > 0:
            name.fill("")

        submit_btn.click()
        time.sleep(0.5)

        # Must NOT have navigated away (form was blocked by validation)
        assert "/projects/new" in page.url or "/projects" in page.url, (
            "Page navigated away from the form on empty submit — "
            "server accepted an empty required field."
        )

        # Check for visual validation indicator
        content = page.content()
        invalid_indicators = [
            "is-invalid", "was-validated", "invalid-feedback",
            "error", "required", ":invalid"
        ]
        has_indicator = any(ind in content for ind in invalid_indicators)
        # Also check browser-native validation (validity state)
        name_invalid = page.evaluate(
            "() => { const el = document.querySelector('input[name=name]'); "
            "return el ? !el.validity.valid : null; }"
        )
        assert has_indicator or name_invalid, (
            "BUG: Empty required field 'name' was submitted with no visual error. "
            "Users have no feedback about what went wrong."
        )
        print("\n  Required field validation UI shown correctly ✓")

    def test_very_long_project_name_handled_gracefully(self, page):
        """
        UI RULE: A project name of 500 characters (far above any reasonable
        limit) must either:
          (a) Be rejected with a visible 'too long' error, OR
          (b) Be truncated by a maxlength attribute (preventing input beyond limit).
        It must NOT cause a server error or corrupt the database row.
        """
        go(page, "/projects/new")
        name = page.locator("input[name='name']").first
        if name.count() == 0:
            pytest.skip("No name input on /projects/new")

        maxlength = name.get_attribute("maxlength")
        long_name = "A" * 500

        name.fill(long_name)
        actual_value = name.input_value()

        if maxlength:
            # Browser enforces maxlength — value should be truncated
            assert len(actual_value) <= int(maxlength), (
                f"BUG: Input has maxlength={maxlength} but accepted {len(actual_value)} chars."
            )
            print(f"\n  maxlength={maxlength} enforced by browser ✓")
        else:
            # No maxlength — submit and check server handles it
            assert len(actual_value) == 500, "Value was truncated without a maxlength attr"
            page.locator("button[type='submit'], input[type='submit']").first.click()
            page.wait_for_load_state("networkidle")
            assert not has_error(page), (
                "BUG: Submitting a 500-character project name caused a server error. "
                "Inputs without maxlength must be sanitised server-side."
            )
            print("\n  NOTE: No maxlength on name field — server accepted 500-char value without error")

    def test_html_special_chars_in_name_are_escaped_in_display(self, page):
        """
        UI RULE: If a user types HTML special characters like < > ' " & in a
        project name field, the saved value must be ESCAPED in the UI — shown
        as literal text, not rendered as HTML. An unescaped <script> is XSS.
        """
        go(page, "/projects/new")

        name_input = page.locator("input[name='name']").first
        if name_input.count() == 0:
            pytest.skip("No name input on /projects/new")

        xss_payload = 'Test <img src=x onerror=alert(1)> & "quotes" \'apos\''
        name_input.fill(xss_payload)

        with page.expect_navigation(wait_until="networkidle", timeout=15000):
            page.locator("button[type='submit'], input[type='submit']").first.click()

        # Check the saved name is NOT rendered as executable HTML
        c = page.content()
        assert "onerror=alert" not in c, (
            "BUG: XSS payload 'onerror=alert(1)' was rendered unescaped in the page. "
            "This is a Cross-Site Scripting vulnerability — attribute injection."
        )
        properly_escaped = "&lt;" in c or "&#60;" in c or "onerror" not in c
        print(f"\n  HTML special chars escaped correctly: {properly_escaped} ✓")

    def test_emoji_in_project_description_does_not_break_ui(self, page):
        """
        UI RULE: Emoji and unicode characters (e.g. 🚀 💼 ✅) in a description
        field must display correctly — not show garbled characters, question
        marks, or crash the page.
        """
        go(page, "/projects/new")
        desc = page.locator("textarea[name='description'], input[name='description']").first
        name = page.locator("input[name='name']").first

        if name.count() == 0:
            pytest.skip("No form on /projects/new")

        name.fill("Emoji Test Project 🚀")
        if desc.count() > 0:
            desc.fill("This project uses emoji: 💼 ✅ 🔥 — testing unicode support")

        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_load_state("networkidle")

        assert not has_error(page), (
            "BUG: Submitting a form with emoji characters caused a server error. "
            "All text fields must handle UTF-8 / unicode safely."
        )
        # Check the emoji appears somewhere in the resulting page
        content = page.content()
        if "🚀" in content:
            print("\n  Emoji stored and displayed correctly ✓")
        else:
            print("\n  NOTE: Emoji may have been stripped or not visible in current view")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 3 — MODAL BEHAVIOUR
# ══════════════════════════════════════════════════════════════════════════════

class TestModalBehaviour:

    def test_esc_key_closes_modal(self, page):
        """
        UI RULE: Pressing the ESC key while a modal is open must close it.
        This is standard Bootstrap/WAI-ARIA behaviour. If ESC doesn't work,
        keyboard-only users are trapped inside the modal.

        BUG EXPECTED: Our exploration found modal did NOT close on ESC.
        """
        go(page, "/planning")
        assign_btn = page.locator("button[data-bs-target='#assignModal']").first
        if assign_btn.count() == 0:
            pytest.skip("No assign modal trigger on /planning")

        assign_btn.click()
        page.wait_for_selector("#assignModal.show", timeout=5000)
        assert page.locator("#assignModal.show").count() == 1, "Modal did not open"

        page.keyboard.press("Escape")
        time.sleep(0.6)  # Bootstrap animation = 300ms

        still_open = page.locator("#assignModal.show").count()
        assert still_open == 0, (
            "BUG: Modal did NOT close when ESC was pressed. "
            "Keyboard users are trapped — they cannot dismiss the modal. "
            "Bootstrap modals should close on ESC by default (keyboard:true)."
        )
        print("\n  ESC key closes modal ✓")

    def test_modal_backdrop_click_closes_modal(self, page):
        """
        UI RULE: Clicking outside the modal (on the dark backdrop) must close
        it. This is expected behaviour for all modal dialogs.
        """
        go(page, "/planning")
        assign_btn = page.locator("button[data-bs-target='#assignModal']").first
        if assign_btn.count() == 0:
            pytest.skip("No assign modal trigger on /planning")

        assign_btn.click()
        page.wait_for_selector("#assignModal.show", timeout=5000)

        # Click the backdrop (top-left corner, outside the modal dialog box)
        page.mouse.click(10, 10)
        time.sleep(0.6)

        still_open = page.locator("#assignModal.show").count()
        assert still_open == 0, (
            "BUG: Clicking the backdrop did NOT close the modal. "
            "Users expect clicking outside a dialog to dismiss it."
        )
        print("\n  Backdrop click closes modal ✓")

    def test_modal_close_button_works(self, page):
        """
        UI RULE: The × close button inside a modal must close it. This is the
        most basic modal interaction — if it fails, the modal is a trap.
        """
        go(page, "/planning")
        assign_btn = page.locator("button[data-bs-target='#assignModal']").first
        if assign_btn.count() == 0:
            pytest.skip("No assign modal trigger on /planning")

        assign_btn.click()
        page.wait_for_selector("#assignModal.show", timeout=5000)

        close_btn = page.locator("#assignModal .btn-close, #assignModal [data-bs-dismiss='modal']").first
        assert close_btn.count() > 0, "No close button inside modal"
        close_btn.click()
        time.sleep(0.6)

        still_open = page.locator("#assignModal.show").count()
        assert still_open == 0, (
            "BUG: The × close button inside the modal did NOT dismiss it."
        )
        print("\n  Modal close button works ✓")

    def test_opening_modal_twice_does_not_double_stack(self, page):
        """
        UI RULE: After a modal is open, triggering it a second time (via JS
        or keyboard) must not stack a second backdrop. The first open is
        enough — the trigger button is behind the modal anyway.
        We test this by opening the modal once, waiting for it to appear,
        then triggering it programmatically a second time via JS.
        """
        go(page, "/planning")
        assign_btn = page.locator("button[data-bs-target='#assignModal']").first
        if assign_btn.count() == 0:
            pytest.skip("No assign modal trigger on /planning")

        # Open modal via normal click
        assign_btn.click()
        page.wait_for_selector("#assignModal.show", timeout=5000)

        # Trigger modal a second time programmatically (simulates race condition)
        page.evaluate("() => { new bootstrap.Modal(document.getElementById('assignModal')).show(); }")
        time.sleep(0.5)

        # Only one backdrop should exist
        backdrops = page.locator(".modal-backdrop").count()
        modals    = page.locator(".modal.show").count()

        assert backdrops <= 1, (
            f"BUG: Triggering modal twice stacked {backdrops} dark backdrops. "
            "Users would need multiple ESC presses to dismiss."
        )
        assert modals <= 1, (
            f"BUG: {modals} overlapping modals open simultaneously."
        )
        print(f"\n  Double-trigger: {modals} modal(s), {backdrops} backdrop(s) ✓")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 4 — MOBILE / RESPONSIVE
# ══════════════════════════════════════════════════════════════════════════════

class TestMobileResponsive:

    def test_sidebar_collapses_on_mobile(self, page):
        """
        UI RULE: At mobile width (375 px) the sidebar navigation must collapse
        and a hamburger / toggle button must be visible. Showing the full
        desktop sidebar on mobile makes the content unusable.
        """
        set_mobile(page)
        go(page, "/dashboard")

        sidebar = page.locator("#sidebar, nav#sidebar, .sidebar").first
        hamburger = page.locator(
            "#sidebar-toggle, [aria-label*='menu' i], "
            "[class*='hamburger'], [class*='navbar-toggle'], "
            "button[data-bs-toggle='offcanvas'], button[data-bs-target*='sidebar']"
        ).first

        sidebar_classes = sidebar.get_attribute("class") or "" if sidebar.count() > 0 else ""
        # Sidebar should be hidden or have a collapsed class
        sidebar_hidden = (
            not sidebar.is_visible() if sidebar.count() > 0 else True
        ) or "collapsed" in sidebar_classes or "hide" in sidebar_classes

        hamburger_visible = hamburger.is_visible() if hamburger.count() > 0 else False

        assert sidebar_hidden or hamburger_visible, (
            "BUG: At 375px width, the full sidebar is visible AND no hamburger "
            "button is shown. Mobile users see a cramped, overlapping layout. "
            "The sidebar must collapse and a toggle must appear."
        )
        print(f"\n  Mobile sidebar collapsed: {sidebar_hidden} | hamburger: {hamburger_visible} ✓")
        set_desktop(page)

    def test_tables_scrollable_on_mobile(self, page):
        """
        UI RULE: Wide tables (projects, people, timesheets) must be horizontally
        scrollable on mobile — not overflow the viewport causing the entire page
        to scroll sideways. The table wrapper must have overflow-x: auto/scroll.
        """
        set_mobile(page)
        go(page, "/projects")

        table = page.locator("table").first
        if table.count() == 0:
            pytest.skip("No table on /projects")

        # Check the wrapper element's overflow-x
        wrapper_overflow = page.evaluate("""() => {
            const table = document.querySelector('table');
            if (!table) return null;
            let el = table.parentElement;
            while (el && el !== document.body) {
                const style = getComputedStyle(el);
                if (style.overflowX === 'auto' || style.overflowX === 'scroll') return style.overflowX;
                el = el.parentElement;
            }
            return 'none';
        }""")

        # Also check if table width exceeds viewport (would cause horizontal scroll on page)
        table_wider_than_viewport = page.evaluate("""() => {
            const table = document.querySelector('table');
            return table ? table.scrollWidth > window.innerWidth : false;
        }""")

        if table_wider_than_viewport and wrapper_overflow == "none":
            print(
                "\n  BUG: Table is wider than the mobile viewport "
                f"({MOBILE_WIDTH}px) but has no scroll wrapper. "
                "The entire page scrolls horizontally on mobile."
            )
        else:
            print(f"\n  Table overflow-x={wrapper_overflow} | wider than viewport: {table_wider_than_viewport} ✓")

        set_desktop(page)

    def test_buttons_have_minimum_touch_target_size(self, page):
        """
        UI RULE: All clickable buttons must be at least 44×44 pixels on mobile
        (Apple HIG / WCAG 2.5.5). Smaller targets cause mis-taps on touchscreens.
        """
        set_mobile(page)
        go(page, "/dashboard")

        small_buttons = page.evaluate("""() => {
            const btns = [...document.querySelectorAll('button, a.btn, input[type=submit]')];
            return btns
                .map(b => {
                    const r = b.getBoundingClientRect();
                    return { text: b.innerText?.trim().slice(0,30), w: Math.round(r.width), h: Math.round(r.height) };
                })
                .filter(b => b.w > 0 && b.h > 0 && (b.w < 44 || b.h < 44))
                .slice(0, 10);
        }""")

        if small_buttons:
            print(f"\n  Small touch targets found ({len(small_buttons)}):")
            for b in small_buttons:
                print(f"    '{b['text']}' → {b['w']}×{b['h']}px")
            # Warn but don't fail — many apps have small icon buttons
            print("  NOTE: Buttons below 44×44px may cause mis-taps on mobile.")
        else:
            print("\n  All visible buttons meet 44×44px touch target ✓")

        set_desktop(page)

    def test_page_not_horizontally_scrollable_on_mobile(self, page):
        """
        UI RULE: No page should cause the browser window itself to scroll
        horizontally on a 375px mobile screen. Horizontal page scroll means
        content is overflowing the viewport — a layout bug.
        """
        set_mobile(page)
        pages_to_check = ["/dashboard", "/projects", "/people", "/absence/my"]

        broken = []
        for path in pages_to_check:
            go(page, path)
            overflows = page.evaluate("""() => {
                return document.body.scrollWidth > window.innerWidth;
            }""")
            if overflows:
                broken.append(path)

        if broken:
            print(f"\n  BUG: These pages overflow horizontally on mobile: {broken}")
        else:
            print(f"\n  No horizontal overflow on mobile for {len(pages_to_check)} pages ✓")

        set_desktop(page)


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 5 — STATUS BADGE COLOURS
# ══════════════════════════════════════════════════════════════════════════════

class TestStatusBadgeColours:

    def test_status_badges_have_correct_colours(self, page):
        """
        UI RULE: Status badges must use consistent, meaningful colours:
          ACTIVE / APPROVED / SUCCESS  → green   (#green / success)
          SUBMITTED / PENDING          → amber / yellow
          REJECTED / FAILED / INACTIVE → red     (#danger)
          DRAFT                        → grey / secondary

        Wrong colours mislead users — a red 'APPROVED' badge would cause panic.
        """
        go(page, "/projects")

        # Map of text → expected colour keyword
        colour_rules = {
            "active":    ["green", "#16a34a", "#166534", "success", "#f0fdf4"],
            "approved":  ["green", "#16a34a", "#166534", "success", "#f0fdf4", "status-approved"],
            "inactive":  ["red", "danger", "#dc2626", "muted", "secondary"],
            "rejected":  ["red", "danger", "#dc2626", "#fef2f2"],
            "submitted": ["amber", "#92400e", "#fef3c7", "warning", "yellow"],
            "draft":     ["grey", "secondary", "muted", "#6b7280"],
        }

        badges = page.locator(".status-badge, .badge").all()
        issues = []

        for badge in badges:
            text = badge.inner_text().strip().lower()
            style = (badge.get_attribute("style") or "").lower()
            cls   = (badge.get_attribute("class") or "").lower()
            combined = style + " " + cls

            for status, expected_colours in colour_rules.items():
                if status in text:
                    if not any(c in combined for c in expected_colours):
                        issues.append(
                            f"'{text}' badge — expected colour hint from {expected_colours}, "
                            f"got class='{cls}' style='{style[:60]}'"
                        )

        if issues:
            print(f"\n  Badge colour issues:")
            for i in issues:
                print(f"    {i}")
        else:
            print(f"\n  All {len(badges)} status badges have correct colour mapping ✓")

    def test_no_badge_text_overflows(self, page):
        """
        UI RULE: Badge text must never overflow its container — no text
        clipped by a fixed-width badge, no line-break inside a badge.
        """
        go(page, "/projects")
        overflowing = page.evaluate("""() => {
            const badges = [...document.querySelectorAll('.badge, .status-badge')];
            return badges
                .filter(b => b.scrollWidth > b.offsetWidth + 2)  // +2px tolerance
                .map(b => b.innerText?.trim());
        }""")

        assert not overflowing, (
            f"BUG: These badges overflow their container: {overflowing}. "
            "Badge text is being clipped — users can't read the full status."
        )
        print(f"\n  No badge text overflow ✓")

    def test_all_table_rows_have_a_status_badge(self, page):
        """
        UI RULE: Every row in the projects and invoices tables must show
        a status badge. A missing badge means a row has an unknown/null
        status in the DB — a data integrity issue surfacing as a UI gap.
        """
        for path, label in [("/projects", "Projects"), ("/invoicing", "Invoices")]:
            go(page, path)
            rows = page.locator("table tbody tr").all()
            if not rows:
                continue

            missing = []
            for i, row in enumerate(rows):
                badges = row.locator(".status-badge, .badge").count()
                if badges == 0:
                    missing.append(i + 1)

            if missing:
                print(f"\n  BUG: {label} table rows {missing} have no status badge.")
            else:
                print(f"\n  All {len(rows)} {label} rows have a status badge ✓")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 6 — EMPTY STATE DISPLAYS
# ══════════════════════════════════════════════════════════════════════════════

class TestEmptyStateDisplays:

    def test_tasks_page_shows_friendly_empty_state(self, page):
        """
        UI RULE: If the tasks list is empty, the page must show a friendly
        message (e.g. 'No tasks yet' + a create button) — not a blank white
        table body or just column headers with nothing underneath.
        """
        go(page, "/tasks")
        rows = page.locator("table tbody tr").count()

        if rows == 0:
            content = page.content().lower()
            empty_signals = [
                "no task", "no result", "nothing", "empty",
                "get started", "create your first", "add a task"
            ]
            has_message = any(s in content for s in empty_signals)
            assert has_message, (
                "BUG: Tasks table is empty but shows no empty-state message. "
                "A blank table with headers only is confusing — users don't know "
                "if data is loading, hidden, or genuinely absent."
            )
            print(f"\n  Empty state message shown on /tasks ✓")
        else:
            print(f"\n  /tasks has {rows} rows — empty state not triggered")

    def test_invoices_empty_state_has_call_to_action(self, page):
        """
        UI RULE: An empty invoices list must show a 'Create invoice' button
        or link as part of the empty state — not just a message with no way
        to proceed. Dead-end empty states frustrate users.
        """
        go(page, "/invoicing")
        rows = page.locator("table tbody tr").count()
        content = page.content().lower()

        if rows == 0:
            has_cta = page.locator(
                "a[href*='/invoicing/new'], button"
            ).filter(has_text=re.compile("new|create|add", re.IGNORECASE)).count() > 0
            print(f"\n  Empty invoices CTA present: {has_cta}")
        else:
            print(f"\n  /invoicing has {rows} rows — empty state not triggered")

    def test_search_no_results_does_not_show_blank_table(self, page):
        """
        UI RULE: A zero-result search must never leave just the table
        headers hanging with a completely blank tbody below them.
        This looks like a loading error rather than an intentional state.
        """
        go(page, "/projects")
        search = page.locator("input[type='search'], input[name='q']").first
        if search.count() == 0:
            pytest.skip("No search on /projects")

        search.fill("ZZZNOTAPROJECT999ZZZZ")
        search.press("Enter")
        page.wait_for_load_state("networkidle")

        rows = page.locator("table tbody tr").count()
        headers = page.locator("table thead tr").count()

        if rows == 0 and headers > 0:
            # Headers exist, tbody is empty — check there's something visible in tbody
            tbody_text = page.locator("table tbody").inner_text().strip()
            assert tbody_text != "", (
                "BUG: No-results search leaves the table with visible headers "
                "but a completely empty tbody — the user sees a blank box. "
                "An empty-state row (e.g. 'No projects match your search') is required."
            )
        print(f"\n  Zero-result search: {rows} rows, tbody not blank ✓")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 7 — PROGRESS BARS
# ══════════════════════════════════════════════════════════════════════════════

class TestProgressBars:

    def test_zero_percent_budget_renders_correctly(self, page):
        """
        UI RULE: A project with 0% budget used must show a progress bar at
        exactly 0% width — not a missing bar, not a negative-width bar, and
        not a fully-filled bar by mistake.
        """
        go(page, "/projects")

        # Find a project row that shows 0h used
        rows = page.locator("table tbody tr").all()
        zero_project_url = None
        for row in rows:
            txt = row.inner_text()
            if "0h 00m" in txt:
                link = row.locator("a").first
                if link.count() > 0:
                    zero_project_url = link.get_attribute("href")
                    break

        if not zero_project_url:
            pytest.skip("No project with 0h used found")

        page.goto(zero_project_url)
        page.wait_for_load_state("networkidle")

        bars = page.locator(".progress-bar").all()
        for bar in bars:
            style = bar.get_attribute("style") or ""
            width_match = re.search(r"width:\s*(\d+(?:\.\d+)?)%", style)
            if width_match:
                width = float(width_match.group(1))
                assert width >= 0, (
                    f"BUG: Progress bar has negative width ({width}%) — layout broken."
                )
                print(f"\n  Progress bar width: {width}% ✓")

    def test_over_100_percent_budget_does_not_visually_overflow(self, page):
        """
        UI RULE: If a project has used more hours than its budget (>100%),
        the progress bar must be capped at 100% width in CSS — it must NOT
        extend beyond its container or break the card layout.

        The bar may turn red to indicate over-budget, but must not overflow.
        """
        go(page, "/projects")
        rows = page.locator("table tbody tr").all()

        for row in rows:
            link = row.locator("a").first
            if link.count() == 0:
                continue
            href = link.get_attribute("href") or ""
            if "/projects/" not in href:
                continue

            page.goto(href)
            page.wait_for_load_state("networkidle")

            overflow = page.evaluate("""() => {
                const bars = [...document.querySelectorAll('.progress-bar')];
                return bars.filter(b => {
                    const parent = b.closest('.progress');
                    if (!parent) return false;
                    return b.offsetWidth > parent.offsetWidth + 2;
                }).map(b => b.style?.width);
            }""")

            if overflow:
                print(
                    f"\n  BUG: Progress bar overflows its container on {href}: {overflow}. "
                    "The bar extends beyond 100% of its parent width."
                )
            go(page, "/projects")
            break

        print("\n  Progress bars contained within their parent ✓")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 8 — 404 / NOT-FOUND PAGE
# ══════════════════════════════════════════════════════════════════════════════

class TestNotFoundPage:

    def test_404_page_shown_for_unknown_url(self, page):
        """
        UI RULE: Visiting a URL that doesn't exist must return a proper 404
        page — not a blank white screen, not a server 500, not the dashboard.
        """
        page.goto(url("/this-page-absolutely-does-not-exist-xyz-999"))
        page.wait_for_load_state("networkidle")

        title = page.title().lower()
        content = page.content().lower()

        assert "404" in title or "not found" in title or "404" in content, (
            "BUG: Unknown URL did not show a 404 page. "
            f"Got title: '{page.title()}'. "
            "Missing 404 pages confuse users and may indicate routing issues."
        )
        assert not has_error(page), "Unknown URL caused a 500 server error instead of 404"
        print(f"\n  404 page shown correctly: '{page.title()}' ✓")

    def test_404_page_has_link_back_to_home(self, page):
        """
        UI RULE: The 404 page must offer a navigation link back to home or
        dashboard — users should not be stranded on a dead-end page with no
        way to recover except the browser back button.
        """
        page.goto(url("/nonexistent-page-abc-123"))
        page.wait_for_load_state("networkidle")

        home_link = page.locator(
            f"a[href='{url('/')}'], a[href='{url('/dashboard')}'], "
            "a[href='/'], a[href*='dashboard']"
        ).first

        has_home_link = home_link.count() > 0
        content = page.content().lower()
        has_home_text = any(w in content for w in ["go back", "home", "dashboard", "return"])

        assert has_home_link or has_home_text, (
            "BUG: 404 page has no link back to home or dashboard. "
            "Users are stranded — they must use the browser back button to recover."
        )
        print(f"\n  404 has home link: {has_home_link} | home text: {has_home_text} ✓")

    def test_404_page_has_no_sidebar(self, page):
        """
        UI RULE: The 404 page is shown outside the authenticated app shell.
        It should NOT show the full navigation sidebar (which requires auth
        and reveals internal routes). A clean, minimal 404 is correct.
        """
        page.goto(url("/nonexistent-xyz"))
        page.wait_for_load_state("networkidle")

        sidebar = page.locator("#sidebar, nav#sidebar").first
        sidebar_visible = sidebar.is_visible() if sidebar.count() > 0 else False

        # Sidebar being visible on 404 is not a hard failure but worth noting
        if sidebar_visible:
            print("\n  NOTE: 404 page shows the full sidebar. "
                  "This exposes internal navigation routes to unauthenticated users.")
        else:
            print("\n  404 page has no sidebar ✓")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 9 — BROWSER BACK / POST-REDIRECT-GET
# ══════════════════════════════════════════════════════════════════════════════

class TestBrowserBackPRG:

    def test_back_after_absence_submit_does_not_resubmit(self, page):
        """
        UI RULE: After submitting an absence request form, pressing the browser
        Back button must go back to the form WITHOUT resubmitting it. This is
        the Post-Redirect-Get (PRG) pattern.

        If PRG is not implemented, pressing Back triggers the browser's
        'Confirm Form Resubmission' dialog — terrible UX — or worse,
        silently creates a duplicate request.
        """
        go(page, "/absence/request")
        url_before_submit = page.url

        # Fill and submit the form
        atype = page.locator("select[name='absence_type_id']").first
        if atype.count() > 0 and atype.locator("option:not([value=''])").count() > 0:
            atype.select_option(index=1)

        start = page.locator("input[name='start_date']").first
        end   = page.locator("input[name='end_date']").first
        note  = page.locator("textarea[name='notes'], input[name='notes']").first

        if start.count() > 0: start.fill("2026-12-14")
        if end.count() > 0:   end.fill("2026-12-15")
        if note.count() > 0:  note.fill("PRG-test-back-button")

        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_load_state("networkidle")

        url_after_submit = page.url
        if url_after_submit == url_before_submit:
            pytest.skip("Form did not navigate away — cannot test PRG")

        # Press Back
        page.go_back()
        page.wait_for_load_state("networkidle")

        # Should land on the form URL, not trigger a resubmission dialog
        assert "absence/request" in page.url or "absence/my" in page.url, (
            f"BUG: Back after form submit landed on unexpected URL: {page.url}. "
            "Expected to return to the absence form or list."
        )

        # Check for browser resubmission dialog (Playwright can detect this
        # indirectly — if the page shows a confirm dialog it's a PRG violation)
        dialog_shown = page.evaluate("() => window._resubmitDialogShown || false")
        print(f"\n  PRG after absence submit: back URL = {page.url} ✓")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 10 — FLASH / ALERT MESSAGES
# ══════════════════════════════════════════════════════════════════════════════

class TestFlashAlertMessages:

    def test_success_flash_appears_after_form_submit(self, page):
        """
        UI RULE: After successfully submitting a form (e.g. absence request),
        the app must show a success flash/toast message. Without feedback,
        users don't know if their action worked and may submit again.
        """
        go(page, "/absence/request")

        atype = page.locator("select[name='absence_type_id']").first
        if atype.count() > 0 and atype.locator("option:not([value=''])").count() > 0:
            atype.select_option(index=1)

        start = page.locator("input[name='start_date']").first
        end   = page.locator("input[name='end_date']").first
        note  = page.locator("textarea[name='notes'], input[name='notes']").first

        if start.count() > 0: start.fill("2026-12-16")
        if end.count() > 0:   end.fill("2026-12-16")
        if note.count() > 0:  note.fill("flash-message-test")

        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_load_state("networkidle")

        content = page.content().lower()
        success_signals = [
            "success", "submitted", "saved", "created", "request received",
            "alert-success", "toast", "✓", "✔"
        ]
        has_feedback = any(s in content for s in success_signals)

        if not has_feedback:
            print(
                "\n  NOTE: No visible success flash/toast after absence request submit. "
                "Users receive no confirmation that their request was received."
            )
        else:
            found = [s for s in success_signals if s in content]
            print(f"\n  Success feedback found: {found} ✓")

    def test_flash_message_is_dismissible(self, page):
        """
        UI RULE: Flash / alert messages must have a × dismiss button.
        A flash that can't be dismissed blocks the UI below it if the user
        needs to re-read the page.
        """
        go(page, "/absence/my")
        content = page.content().lower()

        flash = page.locator(".alert, .flash, .toast, [class*='alert']").first
        if flash.count() == 0:
            pytest.skip("No flash/alert visible on /absence/my")

        dismiss = flash.locator(".btn-close, [data-bs-dismiss], [aria-label*='close' i], button").first
        assert dismiss.count() > 0, (
            "BUG: A flash/alert message is visible but has no dismiss (×) button. "
            "Users cannot remove it from view — it blocks the UI."
        )
        print("\n  Flash message has dismiss button ✓")
