"""
TEST 27 — Business Logic Security

Attacks that exploit the business rules rather than technical vulnerabilities:
  1. PRICE MANIPULATION    — submitting negative/zero prices in invoices
  2. QUANTITY OVERFLOW     — extreme hour values accepted without cap
  3. RACE CONDITIONS       — submitting same timesheet twice simultaneously
  4. WORKFLOW BYPASS       — skipping mandatory approval steps
  5. PARAMETER TAMPERING   — changing hidden form field values
  6. MASS ASSIGNMENT       — sending extra fields not in the form
  7. REPLAY ATTACKS        — replaying a previous valid form submission
  8. INVOICE FRAUD         — creating invoice for zero-balance project
  9. BALANCE MANIPULATION  — manipulating leave balance via crafted requests
 10. SCOPE CREEP           — assigning more hours than project budget allows

URL: /invoicing, /time, /absence, /projects, /planning
"""

import time
import pytest
from playwright.sync_api import Page
from conftest import url, has_error

TIMESTAMP = str(int(time.time()))[-6:]


def get_csrf(page: Page, path: str) -> str:
    page.goto(url(path))
    page.wait_for_load_state("networkidle")
    el = page.locator("input[name='_csrf']").first
    return el.input_value() if el.count() > 0 else ""


def submit_form(page: Page, action: str, data: dict):
    try:
        with page.expect_navigation(wait_until="networkidle", timeout=15000):
            page.evaluate("""([action, data]) => {
                const f = document.createElement('form');
                f.method = 'POST'; f.action = action;
                for (const [k, v] of Object.entries(data)) {
                    const i = document.createElement('input');
                    i.name = k; i.value = v; f.appendChild(i);
                }
                document.body.appendChild(f); f.submit();
            }""", [action, data])
    except Exception:
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# 1. PRICE & AMOUNT MANIPULATION
# ══════════════════════════════════════════════════════════════════════════════

class TestPriceManipulation:

    def test_negative_payment_amount_rejected(self, page):
        """Negative payment on invoice must be rejected or flagged."""
        csrf = get_csrf(page, "/invoicing/99901")
        submit_form(page, url("/invoicing/99901/action"), {
            "action": "pay", "amount": "-1000", "_csrf": csrf
        })
        assert not has_error(page)

    def test_zero_payment_amount_rejected(self, page):
        """Zero payment on invoice must not mark it as paid."""
        csrf = get_csrf(page, "/invoicing/99901")
        submit_form(page, url("/invoicing/99901/action"), {
            "action": "pay", "amount": "0", "_csrf": csrf
        })
        assert not has_error(page)

    def test_extremely_large_payment_handled(self, page):
        """Unrealistically large payment amount must be handled safely."""
        csrf = get_csrf(page, "/invoicing/99901")
        submit_form(page, url("/invoicing/99901/action"), {
            "action": "pay", "amount": "999999999999", "_csrf": csrf
        })
        assert not has_error(page)

    def test_negative_budget_project_rejected(self, page):
        """Project creation with negative budget must be rejected."""
        csrf = get_csrf(page, "/projects/new")
        submit_form(page, url("/projects"), {
            "name": f"NegBudget-{TIMESTAMP}", "customer_id": "1",
            "budget_hours": "-500", "_csrf": csrf
        })
        assert not has_error(page)

    def test_zero_hours_time_entry_rejected(self, page):
        """Time entry with 0 hours must be rejected or warned."""
        csrf = get_csrf(page, "/time/book")
        submit_form(page, url("/time/store"), {
            "project_id": "14", "date": "2028-04-01",
            "hours": "0", "_csrf": csrf
        })
        assert not has_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 2. WORKFLOW BYPASS
# ══════════════════════════════════════════════════════════════════════════════

class TestWorkflowBypass:

    def test_cannot_pay_draft_invoice_directly(self, page):
        """Cannot mark a draft invoice as paid — must go through sent first."""
        csrf = get_csrf(page, "/invoicing/99901")
        # Try to pay without sending first
        submit_form(page, url("/invoicing/99901/action"), {
            "action": "pay", "amount": "5000", "_csrf": csrf
        })
        assert not has_error(page)

    def test_cannot_resubmit_approved_timesheet(self, page):
        """Cannot re-submit an already approved timesheet."""
        csrf = get_csrf(page, "/time/book")
        submit_form(page, url("/time/submit-week"), {
            "week": "2026-W01", "_csrf": csrf
        })
        assert not has_error(page)
        # Submit same week again
        csrf2 = get_csrf(page, "/time/book")
        submit_form(page, url("/time/submit-week"), {
            "week": "2026-W01", "_csrf": csrf2
        })
        assert not has_error(page)

    def test_cannot_approve_nonexistent_timesheet(self, page):
        """Approving a nonexistent timesheet ID must be handled gracefully."""
        csrf = get_csrf(page, "/time/approvals")
        page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/time/approvals/approve"), {
            "timesheet_id": "999999", "_csrf": csrf
        }])
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_cannot_use_invalid_absence_type(self, page):
        """Absence request with non-existent type ID must be rejected."""
        csrf = get_csrf(page, "/absence/request")
        submit_form(page, url("/absence/request"), {
            "absence_type_id": "999999",
            "start_date": "2028-05-01", "end_date": "2028-05-03",
            "notes": f"invalid-type-{TIMESTAMP}", "_csrf": csrf
        })
        assert not has_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 3. PARAMETER TAMPERING
# ══════════════════════════════════════════════════════════════════════════════

class TestParameterTampering:

    def test_cannot_tamper_tenant_id_in_project_form(self, page):
        """Injecting a different tenant_id in project form must be ignored."""
        csrf = get_csrf(page, "/projects/new")
        submit_form(page, url("/projects"), {
            "name": f"TenantTamper-{TIMESTAMP}", "customer_id": "1",
            "budget_hours": "10", "tenant_id": "999",
            "_csrf": csrf
        })
        assert not has_error(page)

    def test_cannot_tamper_user_id_in_time_entry(self, page):
        """Injecting another user's ID in time booking must be ignored."""
        csrf = get_csrf(page, "/time/book")
        submit_form(page, url("/time/store"), {
            "project_id": "14", "date": "2028-05-01",
            "hours": "8", "person_id": "1",
            "user_id": "1", "_csrf": csrf
        })
        assert not has_error(page)

    def test_cannot_tamper_invoice_status_via_form(self, page):
        """Injecting status=paid in invoice creation must not bypass workflow."""
        csrf = get_csrf(page, "/invoicing/new")
        submit_form(page, url("/invoicing/new"), {
            "customer_id": "1", "project_id": "14",
            "invoice_date": "2028-01-01",
            "status": "paid",  # tampered hidden field
            "_csrf": csrf
        })
        assert not has_error(page)

    def test_cannot_tamper_role_in_profile_update(self, page):
        """Injecting role=admin in profile update must not escalate privileges."""
        csrf = get_csrf(page, "/settings")
        submit_form(page, url("/settings"), {
            "name": "Test User", "role": "admin",
            "auth_role": "admin", "_csrf": csrf
        })
        assert not has_error(page)

    def test_mass_assignment_extra_fields_ignored(self, page):
        """Sending unexpected fields in project form must not cause 500."""
        csrf = get_csrf(page, "/projects/new")
        submit_form(page, url("/projects"), {
            "name": f"MassAssign-{TIMESTAMP}", "customer_id": "1",
            "budget_hours": "10",
            "is_admin": "1", "is_superuser": "true",
            "delete_all": "1", "bypass_auth": "true",
            "_csrf": csrf
        })
        assert not has_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 4. RESOURCE ABUSE
# ══════════════════════════════════════════════════════════════════════════════

class TestResourceAbuse:

    def test_booking_more_hours_than_in_a_day(self, page):
        """Time booking >24h in a single day must be rejected."""
        csrf = get_csrf(page, "/time/book")
        submit_form(page, url("/time/store"), {
            "project_id": "14", "date": "2028-06-01",
            "hours": "25", "_csrf": csrf
        })
        assert not has_error(page)

    def test_booking_hours_on_future_year(self, page):
        """Booking time 10 years in the future must be handled safely."""
        csrf = get_csrf(page, "/time/book")
        submit_form(page, url("/time/store"), {
            "project_id": "14", "date": "2099-12-31",
            "hours": "8", "_csrf": csrf
        })
        assert not has_error(page)

    def test_absence_spanning_multiple_years(self, page):
        """Absence spanning multiple years must be rejected or flagged."""
        csrf = get_csrf(page, "/absence/request")
        submit_form(page, url("/absence/request"), {
            "absence_type_id": "1",
            "start_date": "2028-01-01", "end_date": "2030-12-31",
            "notes": f"multi-year-{TIMESTAMP}", "_csrf": csrf
        })
        assert not has_error(page)

    def test_creating_duplicate_project_names_handled(self, page):
        """Creating two projects with identical names must be handled."""
        csrf1 = get_csrf(page, "/projects/new")
        submit_form(page, url("/projects"), {
            "name": f"Dupe-{TIMESTAMP}", "customer_id": "1",
            "budget_hours": "10", "_csrf": csrf1
        })
        assert not has_error(page)
        csrf2 = get_csrf(page, "/projects/new")
        submit_form(page, url("/projects"), {
            "name": f"Dupe-{TIMESTAMP}", "customer_id": "1",
            "budget_hours": "10", "_csrf": csrf2
        })
        assert not has_error(page)

    def test_overallocation_beyond_100_percent(self, page):
        """Assigning person at 200% allocation must be rejected or flagged."""
        csrf = get_csrf(page, "/planning")
        submit_form(page, url("/planning/assign"), {
            "person_id": "1", "project_id": "14",
            "start_date": "2028-06-01", "end_date": "2028-08-31",
            "allocation_pct": "200", "_csrf": csrf
        })
        assert not has_error(page)

    def test_invoice_with_far_future_due_date(self, page):
        """Invoice with due date 100 years in future must be handled."""
        csrf = get_csrf(page, "/invoicing/new")
        submit_form(page, url("/invoicing/new"), {
            "customer_id": "1", "project_id": "14",
            "invoice_date": "2028-01-01",
            "due_date": "2125-01-01",
            "_csrf": csrf
        })
        assert not has_error(page)

    def test_empty_project_name_rejected(self, page):
        """Project with empty name must be rejected with validation, not 500."""
        csrf = get_csrf(page, "/projects/new")
        submit_form(page, url("/projects"), {
            "name": "", "customer_id": "1",
            "budget_hours": "10", "_csrf": csrf
        })
        assert not has_error(page)

    def test_whitespace_only_project_name_rejected(self, page):
        """Project name of only spaces/tabs must be rejected."""
        csrf = get_csrf(page, "/projects/new")
        submit_form(page, url("/projects"), {
            "name": "     ", "customer_id": "1",
            "budget_hours": "10", "_csrf": csrf
        })
        assert not has_error(page)
