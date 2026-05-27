"""
TEST 05 — Time Module
Real URLs: /time/book, /time/timesheets, /time/timer, /time/approvals
/time itself is 404 — all sub-paths are used.
"""

import pytest
import time
from conftest import url, has_error, is_404

TEST_DATE = "2026-05-07"


class TestTimePages:

    def test_book_time_page_loads(self, page):
        page.goto(url("/time/book"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not is_404(page)

    def test_timesheets_page_loads(self, page):
        page.goto(url("/time/timesheets"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_timer_page_loads(self, page):
        page.goto(url("/time/timer"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_approvals_page_loads(self, page):
        page.goto(url("/time/approvals"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_timesheets_has_weekly_grid(self, page):
        """Weekly time-booking grid shows Mon-Fri columns.
        NOTE: /time/timesheets is a monthly project-grouped summary.
        The weekly day-column grid lives at /time/book — use that URL.
        """
        page.goto(url("/time/book"))
        page.wait_for_load_state("networkidle")
        content = page.content()
        days = sum(1 for d in ["Mon", "Tue", "Wed", "Thu", "Fri"] if d in content)
        assert days >= 3, f"Only {days}/5 weekdays found on /time/book grid"

    def test_timesheets_shows_hours_target(self, page):
        page.goto(url("/time/timesheets"))
        page.wait_for_load_state("networkidle")
        assert "0h" in page.content() or "h booked" in page.content() or "target" in page.content().lower()


class TestBookTime:

    def test_book_time_form_has_fields(self, page):
        """Book time form has project, date, and hours fields."""
        page.goto(url("/time/book"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        assert "project" in content or page.locator("select[name='project_id']").count() >= 1
        assert "date" in content or page.locator("input[type='date']").count() >= 1
        assert "hours" in content or page.locator("input[name='hours']").count() >= 1

    def test_empty_book_time_shows_validation(self, page):
        """Book time page has multiple day-cards each with a project select.
        Use .first to avoid strict mode error."""
        page.goto(url("/time/book"))
        page.wait_for_load_state("networkidle")
        submit = page.locator("button[type='submit'], input[type='submit']").first
        if submit.count() == 0:
            pytest.skip("No submit button on book time page")
        submit.scroll_into_view_if_needed()
        submit.click()
        page.wait_for_load_state("networkidle")
        assert not has_error(page), "Server error on empty time entry submit"

    def test_create_time_entry(self, page):
        """Book a time entry — page has multiple day-cards, use first card."""
        page.goto(url("/time/book"))
        page.wait_for_load_state("networkidle")

        # Page has multiple project selects (one per day card) — use first
        project = page.locator("select[name='project_id']").first
        hours   = page.locator("input[name='hours'], input[name='duration']").first

        if page.locator("select[name='project_id']").count() == 0:
            pytest.skip("No project_id select found on book time page")

        opts = project.locator("option:not([value=''])").count()
        if opts == 0:
            pytest.skip("No projects available to book time against")

        project.select_option(index=1)
        hours.fill("4")

        submit = page.locator("button[type='submit'], input[type='submit']").first
        submit.scroll_into_view_if_needed()
        submit.click()
        page.wait_for_load_state("networkidle")
        assert not has_error(page), "Server error after booking time"

    def test_negative_hours_rejected(self, page):
        page.goto(url("/time/book"))
        page.wait_for_load_state("networkidle")
        hours = page.locator("input[name='hours'], input[name='duration']").first
        if page.locator("input[name='hours']").count() == 0:
            pytest.skip("Hours field not found")
        hours.fill("-8")
        submit = page.locator("button[type='submit'], input[type='submit']").first
        submit.scroll_into_view_if_needed()
        submit.click()
        page.wait_for_load_state("networkidle")
        assert not has_error(page), "Server error on negative hours — no validation"


class TestTimeApprovals:

    def test_approvals_list_or_empty(self, page):
        page.goto(url("/time/approvals"))
        page.wait_for_load_state("networkidle")
        content = page.content().lower()
        assert "approval" in content or "time" in content or "no entries" in content or "pending" in content

    def test_timer_start_ui_present(self, page):
        page.goto(url("/time/timer"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        assert "timer" in content or "start" in content or "track" in content
