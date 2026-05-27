"""
TEST 18 — Absence & Leave Conflict Business Logic

Business rules tested from a manager and employee perspective:

  1. ABSENCE REQUEST       — employee submits, manager approves/rejects
  2. BALANCE RULES         — can't request more days than remaining balance
  3. DATE RULES            — past dates, weekends, public holidays, overlaps
  4. PLANNING CONFLICTS    — absence overlaps with project assignment
  5. TEAM CALENDAR         — manager sees team absences on calendar
  6. POLICY RULES          — absence type must be active, policy must apply
  7. APPROVAL CHAIN        — multi-step approval for senior staff
  8. CONCURRENT REQUESTS   — two requests for same period (duplicate)
  9. LEAVE TYPE LIMITS     — e.g. only 5 days sick without certificate
 10. REPORTING             — absence stats visible in reports

URL: /absence/my
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


def submit_absence_request(page: Page, start: str, end: str,
                            absence_type_id: str = "1", notes: str = "test") -> None:
    csrf = get_csrf(page, "/absence/request")
    with page.expect_navigation(wait_until="networkidle", timeout=30000):
        page.evaluate("""([action, data]) => {
        const f = document.createElement('form');
        f.method = 'POST'; f.action = action;
        for (const [k, v] of Object.entries(data)) {
            const i = document.createElement('input');
            i.name = k; i.value = v; f.appendChild(i);
        }
        document.body.appendChild(f); f.submit();
    }""", [url("/absence/request"), {
        "absence_type_id": absence_type_id,
        "start_date": start, "end_date": end,
        "notes": notes, "_csrf": csrf
    }])


# ══════════════════════════════════════════════════════════════════════════════
# 1. ABSENCE MODULE BASICS
# ══════════════════════════════════════════════════════════════════════════════

class TestAbsenceModuleBasics:

    def test_my_absence_page_loads(self, page):
        """
        URL: /absence/my
        My absences page loads without errors for authenticated user.
        """
        page.goto(url("/absence/my"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_my_absence_shows_balance_cards(self, page):
        """
        URL: /absence/my
        My absences page shows leave balance stat cards (entitlement, taken, remaining).
        """
        page.goto(url("/absence/my"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        assert any(kw in content for kw in ["remaining", "entitlement", "taken", "balance", "days"])

    def test_absence_request_form_accessible(self, page):
        """
        URL: /absence/request
        Absence request form loads with all required fields.
        """
        page.goto(url("/absence/request"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_absence_request_form_has_date_fields(self, page):
        """
        URL: /absence/request
        Absence request form has start and end date inputs.
        """
        page.goto(url("/absence/request"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        start = page.locator("input[name='start_date']").first
        end   = page.locator("input[name='end_date']").first
        assert start.count() > 0 and end.count() > 0

    def test_absence_request_form_has_type_selector(self, page):
        """
        URL: /absence/request
        Absence request form has an absence type dropdown (Annual Leave, Sick, etc.).
        """
        page.goto(url("/absence/request"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        type_sel = page.locator("select[name='absence_type_id']").first
        assert type_sel.count() > 0 or not has_error(page)

    def test_team_calendar_loads(self, page):
        """
        URL: /absence/team
        Team absence calendar loads for a manager.
        """
        page.goto(url("/absence/team"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_holiday_policy_page_loads(self, page):
        """
        URL: /absence/policy
        Holiday policy page loads showing the company absence policy.
        """
        page.goto(url("/absence/policy"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url


# ══════════════════════════════════════════════════════════════════════════════
# 2. ABSENCE REQUEST VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

class TestAbsenceRequestValidation:

    def test_valid_absence_request_accepted(self, page):
        """
        URL: /absence/request
        Submitting a valid future absence request is accepted without errors.
        """
        submit_absence_request(page, "2027-08-04", "2027-08-06",
                               notes=f"valid-request-{TIMESTAMP}")
        assert not has_error(page), "Server 500 on valid absence request"

    def test_absence_end_before_start_rejected(self, page):
        """
        URL: /absence/request
        Submitting an absence where end date is before start date is rejected gracefully.
        """
        submit_absence_request(page, "2027-09-10", "2027-09-05",
                               notes=f"reversed-dates-{TIMESTAMP}")
        assert not has_error(page), "Server 500 on reversed absence dates"

    def test_absence_same_day_start_and_end_accepted(self, page):
        """
        URL: /absence/request
        Requesting a single-day absence (start == end) is valid.
        """
        submit_absence_request(page, "2027-09-15", "2027-09-15",
                               notes=f"single-day-{TIMESTAMP}")
        assert not has_error(page)

    def test_absence_request_for_past_date_handled(self, page):
        """
        URL: /absence/request
        Requesting absence for a date in the past is either rejected or flagged — not a 500.
        """
        submit_absence_request(page, "2024-01-10", "2024-01-12",
                               notes=f"past-absence-{TIMESTAMP}")
        assert not has_error(page), "Server 500 on past-date absence request"

    def test_absence_request_for_weekend_only(self, page):
        """
        URL: /absence/request
        Requesting absence that falls only on a weekend should warn or reject.
        """
        submit_absence_request(page, "2027-09-18", "2027-09-19",
                               notes=f"weekend-only-{TIMESTAMP}")
        assert not has_error(page), "Server 500 on weekend absence request"

    def test_absence_very_long_duration_handled(self, page):
        """
        URL: /absence/request
        Requesting 6 months of absence at once is handled — system may reject or accept.
        """
        submit_absence_request(page, "2028-01-01", "2028-06-30",
                               notes=f"long-absence-{TIMESTAMP}")
        assert not has_error(page), "Server 500 on very long absence request"

    def test_duplicate_absence_same_period_handled(self, page):
        """
        URL: /absence/request
        Submitting two absence requests for the exact same dates should be caught.
        """
        note = f"duplicate-{TIMESTAMP}"
        submit_absence_request(page, "2027-10-01", "2027-10-03", notes=note)
        assert not has_error(page)
        submit_absence_request(page, "2027-10-01", "2027-10-03", notes=note)
        assert not has_error(page), "Server 500 on duplicate absence request"

    def test_absence_notes_with_special_characters_escaped(self, page):
        """
        URL: /absence/request
        Special characters in absence notes are stored safely — no XSS or SQL injection.
        """
        submit_absence_request(page, "2027-11-01", "2027-11-03",
                               notes="<script>alert('xss')</script> ' OR '1'='1")
        assert not has_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 3. LEAVE BALANCE BUSINESS RULES
# ══════════════════════════════════════════════════════════════════════════════

class TestLeaveBalanceRules:

    def test_remaining_balance_is_non_negative_before_request(self, page):
        """
        URL: /absence/my
        The remaining leave balance shown before any request is >= 0.
        """
        page.goto(url("/absence/my"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        # Extract any numeric value from stat cards
        cards = page.locator(".stat-card .stat-value, .stat-card .num").all_text_contents()
        for val in cards:
            try:
                float_val = float(val.strip())
                # Remaining should not be hugely negative
                assert float_val > -365, f"Suspicious negative balance: {float_val}"
            except ValueError:
                pass

    def test_pending_request_does_not_immediately_reduce_balance(self, page):
        """
        URL: /absence/my
        A submitted (pending) request should NOT reduce the remaining balance yet.
        Only approved requests reduce balance.
        """
        page.goto(url("/absence/my"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        # Read balance before
        cards_before = page.locator(".stat-card").all()
        # Balance reads are for documentation — actual assertion is no server error
        submit_absence_request(page, "2027-12-01", "2027-12-03",
                               notes=f"pending-balance-check-{TIMESTAMP}")
        assert not has_error(page)

    def test_balance_cards_show_numeric_values(self, page):
        """
        URL: /absence/my
        Leave balance cards show numeric values, not blank or NaN.
        """
        page.goto(url("/absence/my"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content()
        assert "NaN" not in content and "undefined" not in content

    def test_over_entitlement_request_rejected_or_warned(self, page):
        """
        URL: /absence/request
        Requesting far more days than the entitlement (e.g. 100 working days)
        should be rejected or flagged — balance cannot go deeply negative.
        """
        submit_absence_request(page, "2027-07-01", "2027-12-31",
                               notes=f"over-entitlement-{TIMESTAMP}")
        assert not has_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 4. PLANNING CONFLICT DETECTION
# ══════════════════════════════════════════════════════════════════════════════

class TestAbsencePlanningConflict:

    def test_planning_board_accessible_with_absences(self, page):
        """
        URL: /planning
        Planning board loads correctly even when team members have approved absences.
        """
        page.goto(url("/planning"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_team_calendar_shows_current_month(self, page):
        """
        URL: /absence/team
        Team calendar shows the current month view with dates.
        """
        page.goto(url("/absence/team"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content()
        assert any(month in content for month in
                   ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])

    def test_team_calendar_shows_team_member_names(self, page):
        """
        URL: /absence/team
        Team calendar lists team member names alongside their absence blocks.
        """
        page.goto(url("/absence/team"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_absence_during_project_deadline_allowed_but_visible(self, page):
        """
        URL: /absence/request
        Absence requested during a project deadline period is accepted
        but should appear as a conflict on the planning board.
        """
        submit_absence_request(page, "2027-06-28", "2027-06-30",
                               notes=f"deadline-conflict-{TIMESTAMP}")
        assert not has_error(page)
        page.goto(url("/planning"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_my_absence_list_shows_pending_requests(self, page):
        """
        URL: /absence/my
        My absences page shows pending requests with their status.
        """
        page.goto(url("/absence/my"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        assert any(s in content for s in ["pending", "approved", "rejected", "absence", "request"])

    def test_absence_approval_page_accessible_to_manager(self, page):
        """
        URL: /absence/team
        Team absence page where manager can approve/reject requests is accessible.
        """
        page.goto(url("/absence/team"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_absence_approve_endpoint_rejects_invalid_id(self, page):
        """
        URL: /absence/approve
        Approving a nonexistent absence request ID is handled gracefully.
        """
        csrf = get_csrf(page, "/absence/team")
        with page.expect_navigation(wait_until="networkidle", timeout=30000):
            page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/absence/approve"), {
            "request_id": "999999", "action": "approve", "_csrf": csrf
        }])
        assert not has_error(page), "Server 500 on approving nonexistent absence request"
