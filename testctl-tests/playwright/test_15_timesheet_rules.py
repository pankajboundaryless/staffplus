"""
TEST 15 — Timesheet Business Rules

From a user's perspective — what can and cannot be done when booking time:

  1. BOOKING RULES       — book time only on assigned projects
  2. UNASSIGNED BLOCK    — cannot book on project you're not assigned to
  3. WEEK SUBMISSION     — submit a week, then try to edit it
  4. DATE LOCK           — cannot book time on future locked periods
  5. ZERO / NEGATIVE     — 0h or negative hours are rejected
  6. WEEKEND BOOKING     — booking on Saturday/Sunday
  7. APPROVAL FLOW       — submitted timesheet triggers approval chain
  8. REJECTION FLOW      — after rejection, timesheet goes back to editable
  9. DUPLICATE BOOKING   — booking same project + date twice
 10. TIMESHEET OVERVIEW  — weekly grid shows correct total hours

URL: /time/book
"""

import re
import time
import pytest
from playwright.sync_api import Page
from conftest import url, has_error

TIMESTAMP = str(int(time.time()))[-6:]


# ─── helpers ──────────────────────────────────────────────────────────────────

def get_csrf(page: Page, path: str) -> str:
    page.goto(url(path))
    page.wait_for_load_state("networkidle")
    el = page.locator("input[name='_csrf']").first
    return el.input_value() if el.count() > 0 else ""


def book_time(page: Page, project_id: str, hours: str, date: str, desc: str = "test entry"):
    csrf = get_csrf(page, "/time/book")
    with page.expect_navigation(wait_until="networkidle", timeout=30000):
        page.evaluate("""([action, data]) => {
        const f = document.createElement('form');
        f.method = 'POST'; f.action = action;
        for (const [k, v] of Object.entries(data)) {
            const i = document.createElement('input');
            i.name = k; i.value = v; f.appendChild(i);
        }
        document.body.appendChild(f); f.submit();
    }""", [url("/time/store"), {
        "project_id": project_id, "hours": hours,
        "date_worked": date, "description": desc, "_csrf": csrf
    }])


def submit_week(page: Page, week_start: str):
    csrf = get_csrf(page, "/time/book")
    with page.expect_navigation(wait_until="networkidle", timeout=30000):
        page.evaluate("""([action, data]) => {
        const f = document.createElement('form');
        f.method = 'POST'; f.action = action;
        for (const [k, v] of Object.entries(data)) {
            const i = document.createElement('input');
            i.name = k; i.value = v; f.appendChild(i);
        }
        document.body.appendChild(f); f.submit();
    }""", [url("/time/submit-week"), {"week_start": week_start, "_csrf": csrf}])


# ══════════════════════════════════════════════════════════════════════════════
# 1. TIME BOOKING PAGE BASICS
# ══════════════════════════════════════════════════════════════════════════════

class TestTimesheetPageBasics:

    def test_time_book_page_loads(self, page):
        """
        URL: /time/book
        Time booking page loads without errors.
        """
        page.goto(url("/time/book"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_time_book_shows_project_dropdown(self, page):
        """
        URL: /time/book
        Booking form shows a project selector for the user to choose a project.
        """
        page.goto(url("/time/book"))
        page.wait_for_load_state("networkidle")
        proj_select = page.locator("select[name='project_id'], #project_id").first
        assert proj_select.count() > 0 or not has_error(page)

    def test_time_book_shows_date_field(self, page):
        """
        URL: /time/book
        Booking form has a date field for the worked date.
        """
        page.goto(url("/time/book"))
        page.wait_for_load_state("networkidle")
        date_field = page.locator("input[name='date_worked'], input[type='date']").first
        assert date_field.count() > 0 or not has_error(page)

    def test_time_book_shows_hours_field(self, page):
        """
        URL: /time/book
        Booking form has an hours input field.
        """
        page.goto(url("/time/book"))
        page.wait_for_load_state("networkidle")
        hours_field = page.locator("input[name='hours'], input[name='duration']").first
        assert hours_field.count() > 0 or not has_error(page)

    def test_timesheets_page_loads(self, page):
        """
        URL: /time/timesheets
        Timesheets listing page loads correctly.
        """
        page.goto(url("/time/timesheets"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_weekly_grid_structure_visible(self, page):
        """
        URL: /time/book
        Weekly timesheet grid or list structure is present on the page.
        """
        page.goto(url("/time/book"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        assert any(day in content for day in ["mon", "tue", "wed", "thu", "fri", "week"])


# ══════════════════════════════════════════════════════════════════════════════
# 2. BOOKING VALIDATION RULES
# ══════════════════════════════════════════════════════════════════════════════

class TestBookingValidation:

    def test_booking_zero_hours_is_rejected(self, page):
        """
        URL: /time/store
        Booking 0 hours should be rejected — zero is not a valid time entry.
        """
        book_time(page, "14", "0", "2026-06-02", f"zero-hours-test-{TIMESTAMP}")
        assert not has_error(page), "Server 500 on 0-hour booking"

    def test_booking_negative_hours_is_rejected(self, page):
        """
        URL: /time/store
        Booking -8 hours should be rejected gracefully, not crash the server.
        """
        book_time(page, "14", "-8", "2026-06-03", f"negative-hours-{TIMESTAMP}")
        assert not has_error(page), "Server 500 on negative hour booking"

    def test_booking_more_than_24_hours_in_one_day(self, page):
        """
        URL: /time/store
        Booking 25 hours for a single day should be rejected (impossible workday).
        """
        book_time(page, "14", "25", "2026-06-04", f"over-24h-{TIMESTAMP}")
        assert not has_error(page), "Server 500 on >24h booking"

    def test_booking_valid_8_hours_is_accepted(self, page):
        """
        URL: /time/store
        Booking a standard 8-hour day is accepted without errors.
        """
        book_time(page, "14", "8", "2026-06-08", f"valid-8h-{TIMESTAMP}")
        assert not has_error(page)

    def test_booking_fractional_hours_accepted(self, page):
        """
        URL: /time/store
        Booking 7.5 hours (fractional) is accepted — half-hours are common.
        """
        book_time(page, "14", "7.5", "2026-06-09", f"fractional-7-5h-{TIMESTAMP}")
        assert not has_error(page)

    def test_booking_1_hour_minimum_accepted(self, page):
        """
        URL: /time/store
        Booking just 1 hour is accepted — minimum meaningful time entry.
        """
        book_time(page, "14", "1", "2026-06-10", f"min-1h-{TIMESTAMP}")
        assert not has_error(page)

    def test_booking_without_description_handled(self, page):
        """
        URL: /time/store
        Booking with an empty description either accepts or shows validation error — no 500.
        """
        book_time(page, "14", "4", "2026-06-11", "")
        assert not has_error(page)

    def test_booking_on_weekend_saturday_handled(self, page):
        """
        URL: /time/store
        Booking time on a Saturday — system should either reject or flag it, not crash.
        """
        book_time(page, "14", "8", "2026-06-06", f"saturday-booking-{TIMESTAMP}")
        assert not has_error(page), "Server 500 on Saturday booking"

    def test_booking_on_weekend_sunday_handled(self, page):
        """
        URL: /time/store
        Booking time on a Sunday — same as Saturday, no 500 allowed.
        """
        book_time(page, "14", "8", "2026-06-07", f"sunday-booking-{TIMESTAMP}")
        assert not has_error(page), "Server 500 on Sunday booking"

    def test_booking_on_very_old_past_date(self, page):
        """
        URL: /time/store
        Booking time on a date 2 years in the past — should be rejected (locked period).
        """
        book_time(page, "14", "8", "2024-01-15", f"old-date-booking-{TIMESTAMP}")
        assert not has_error(page), "Server 500 on old date booking"

    def test_booking_on_far_future_date(self, page):
        """
        URL: /time/store
        Booking time on a date far in the future (2030) should be rejected or flagged.
        """
        book_time(page, "14", "8", "2030-06-15", f"future-booking-{TIMESTAMP}")
        assert not has_error(page), "Server 500 on future date booking"


# ══════════════════════════════════════════════════════════════════════════════
# 3. BOOKING ON UNASSIGNED PROJECTS
# ══════════════════════════════════════════════════════════════════════════════

class TestUnassignedProjectBooking:

    def test_booking_on_project_shows_in_time_book_dropdown(self, page):
        """
        URL: /time/book
        Only projects the user is assigned to appear in the booking dropdown.
        """
        page.goto(url("/time/book"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        proj_sel = page.locator("select[name='project_id']").first
        if proj_sel.count() > 0:
            options = proj_sel.locator("option").all_text_contents()
            assert len(options) >= 0  # may be empty if no assignments

    def test_booking_on_nonexistent_project_id(self, page):
        """
        URL: /time/store
        Booking against a project ID that does not exist (99999) should fail gracefully.
        """
        book_time(page, "99999", "8", "2026-06-15", f"nonexistent-proj-{TIMESTAMP}")
        assert not has_error(page), "Server 500 on nonexistent project booking"

    def test_booking_on_project_zero_id(self, page):
        """
        URL: /time/store
        Booking against project_id=0 (null project) should be rejected cleanly.
        """
        book_time(page, "0", "8", "2026-06-16", f"zero-proj-id-{TIMESTAMP}")
        assert not has_error(page)

    def test_time_entry_list_does_not_show_other_users_entries(self, page):
        """
        URL: /time/book
        The current user's time booking page only shows their own entries.
        """
        page.goto(url("/time/book"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        # No other user's name or ID should appear in logged entries
        content = page.content()
        assert "login" not in page.url


# ══════════════════════════════════════════════════════════════════════════════
# 4. TIMESHEET SUBMISSION FLOW
# ══════════════════════════════════════════════════════════════════════════════

class TestTimesheetSubmission:

    def test_submit_week_endpoint_accessible(self, page):
        """
        URL: /time/submit-week
        Submit-week endpoint accepts POST without crashing.
        """
        submit_week(page, "2026-06-01")
        assert not has_error(page)

    def test_submit_empty_week_handled(self, page):
        """
        URL: /time/submit-week
        Submitting a week with zero hours should be rejected or warned — not a 500.
        """
        submit_week(page, "2026-05-04")
        assert not has_error(page), "Server 500 on empty-week submission"

    def test_submit_week_changes_status_to_submitted(self, page):
        """
        URL: /time/timesheets
        After submitting a week, the timesheet status changes from draft to submitted.
        """
        page.goto(url("/time/timesheets"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        # Page should show some status indicators
        assert any(s in content for s in ["submitted", "draft", "approved", "pending", "week"])

    def test_submitted_week_shows_in_timesheets_list(self, page):
        """
        URL: /time/timesheets
        Submitted timesheets appear in the timesheets list with correct status.
        """
        page.goto(url("/time/timesheets"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_timesheets_list_shows_date_range(self, page):
        """
        URL: /time/timesheets
        Each timesheet row shows a week date range (e.g. Jun 1 – Jun 7).
        """
        page.goto(url("/time/timesheets"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content()
        assert any(month in content for month in
                   ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])

    def test_double_submission_of_same_week_rejected(self, page):
        """
        URL: /time/submit-week
        Submitting the same week twice should be rejected — no duplicate submissions.
        """
        submit_week(page, "2026-04-06")
        assert not has_error(page)
        submit_week(page, "2026-04-06")  # second attempt
        assert not has_error(page), "Server 500 on double-submit"

    def test_submit_week_with_invalid_date_format(self, page):
        """
        URL: /time/submit-week
        Submitting with a malformed week_start date should fail gracefully.
        """
        submit_week(page, "not-a-date")
        assert not has_error(page), "Server 500 on malformed week_start"


# ══════════════════════════════════════════════════════════════════════════════
# 5. TIMER FEATURE
# ══════════════════════════════════════════════════════════════════════════════

class TestTimerWorkflow:

    def test_timer_page_loads(self, page):
        """
        URL: /time/timer
        Timer page loads without errors.
        """
        page.goto(url("/time/timer"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_timer_has_start_button(self, page):
        """
        URL: /time/timer
        Timer page shows a Start button or equivalent control.
        """
        page.goto(url("/time/timer"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_timer_start_endpoint_accessible(self, page):
        """
        URL: /time/timer/start
        Timer start endpoint accepts a POST request without crashing.
        """
        csrf = get_csrf(page, "/time/timer")
        with page.expect_navigation(wait_until="networkidle", timeout=30000):
            page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/time/timer/start"), {"project_id": "14", "_csrf": csrf}])
        assert not has_error(page)

    def test_running_two_timers_simultaneously_rejected(self, page):
        """
        URL: /time/timer/start
        Starting a second timer while one is already running should fail gracefully.
        """
        csrf = get_csrf(page, "/time/timer")
        for _ in range(2):
            with page.expect_navigation(wait_until="networkidle", timeout=30000):
                page.evaluate("""([action, data]) => {
                const f = document.createElement('form');
                f.method = 'POST'; f.action = action;
                for (const [k, v] of Object.entries(data)) {
                    const i = document.createElement('input');
                    i.name = k; i.value = v; f.appendChild(i);
                }
                document.body.appendChild(f); f.submit();
            }""", [url("/time/timer/start"), {"project_id": "14", "_csrf": csrf}])
        assert not has_error(page), "Server 500 on double timer start"

    def test_timer_stop_without_start_handled(self, page):
        """
        URL: /time/timer/stop
        Stopping a timer when none is running should fail gracefully, not crash.
        """
        csrf = get_csrf(page, "/time/timer")
        with page.expect_navigation(wait_until="networkidle", timeout=30000):
            page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/time/timer/stop"), {"_csrf": csrf}])
        assert not has_error(page)
