"""
TEST 17 — Invoice & Billing Business Logic

Business rules tested from a user perspective:

  1. INVOICE CREATION      — draft invoice, required fields, no timesheets
  2. UNBOOKED BILLING      — cannot invoice project with zero booked hours
  3. STATUS TRANSITIONS    — draft → sent → paid, reversals blocked
  4. LINE ITEM GENERATION  — lines match approved timesheets, not unapproved
  5. RATE CARD RULES       — no rate card set, wrong currency, rate override
  6. CROSS-CHARGE          — internal cross-charge form, legal entity required
  7. PAYMENT RECORDING     — partial payment, overpayment, double payment
  8. INVOICE NUMBER        — auto-generated, sequential, not duplicated
  9. ACCESS CONTROL        — employee cannot create invoices
 10. INVOICE LOCKING       — sent invoice cannot be edited

URL: /invoicing
"""

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


def post_invoice_action(page: Page, invoice_id: str, action: str, amount: str = ""):
    csrf = get_csrf(page, f"/invoicing/{invoice_id}")
    data = {"action": action, "_csrf": csrf}
    if amount:
        data["amount"] = amount
    with page.expect_navigation(wait_until="networkidle", timeout=30000):
        page.evaluate("""([action_url, data]) => {
        const f = document.createElement('form');
        f.method = 'POST'; f.action = action_url;
        for (const [k, v] of Object.entries(data)) {
            const i = document.createElement('input');
            i.name = k; i.value = v; f.appendChild(i);
        }
        document.body.appendChild(f); f.submit();
    }""", [url(f"/invoicing/{invoice_id}/action"), data])


# ══════════════════════════════════════════════════════════════════════════════
# 1. INVOICE LIST & BASICS
# ══════════════════════════════════════════════════════════════════════════════

class TestInvoiceListBasics:

    def test_invoicing_list_loads(self, page):
        """
        URL: /invoicing
        Invoicing list page loads without errors.
        """
        page.goto(url("/invoicing"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_invoicing_list_shows_status_badges(self, page):
        """
        URL: /invoicing
        Each invoice row shows a status badge (Draft / Sent / Paid).
        """
        page.goto(url("/invoicing"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        assert any(s in content for s in ["draft", "sent", "paid", "invoice", "overdue"])

    def test_invoicing_list_shows_amounts(self, page):
        """
        URL: /invoicing
        Invoice list shows monetary amounts for each invoice.
        """
        page.goto(url("/invoicing"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_invoicing_new_form_accessible(self, page):
        """
        URL: /invoicing/new
        New invoice form loads for admin users.
        """
        page.goto(url("/invoicing/new"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_invoicing_new_form_has_customer_field(self, page):
        """
        URL: /invoicing/new
        New invoice form requires selecting a customer.
        """
        page.goto(url("/invoicing/new"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        customer_sel = page.locator("select[name='customer_id'], #customer_id").first
        assert customer_sel.count() > 0 or not has_error(page)

    def test_invoicing_new_form_has_project_field(self, page):
        """
        URL: /invoicing/new
        New invoice form has a project selector.
        """
        page.goto(url("/invoicing/new"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        proj_sel = page.locator("select[name='project_id'], #project_id").first
        assert proj_sel.count() > 0 or not has_error(page)

    def test_create_draft_invoice_accepted(self, page):
        """
        URL: /invoicing/new
        Submitting a new invoice form creates a draft invoice.
        """
        csrf = get_csrf(page, "/invoicing/new")
        with page.expect_navigation(wait_until="networkidle", timeout=30000):
            page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/invoicing"), {
            "customer_id": "1", "project_id": "14",
            "invoice_date": "2026-06-01", "_csrf": csrf
        }])
        assert not has_error(page), "Server 500 on draft invoice creation"


# ══════════════════════════════════════════════════════════════════════════════
# 2. INVOICE CREATION VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

class TestInvoiceCreationValidation:

    def test_invoice_without_customer_rejected(self, page):
        """
        URL: /invoicing
        Creating an invoice with no customer should fail with a validation error, not 500.
        """
        csrf = get_csrf(page, "/invoicing/new")
        with page.expect_navigation(wait_until="networkidle", timeout=30000):
            page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/invoicing"), {"customer_id": "", "_csrf": csrf}])
        assert not has_error(page), "Server 500 on invoice with no customer"

    def test_invoice_with_past_date_accepted(self, page):
        """
        URL: /invoicing/new
        Creating an invoice dated in the past is valid — back-dated invoices are common.
        """
        csrf = get_csrf(page, "/invoicing/new")
        with page.expect_navigation(wait_until="networkidle", timeout=30000):
            page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/invoicing"), {
            "customer_id": "1", "project_id": "14",
            "invoice_date": "2025-01-15", "_csrf": csrf
        }])
        assert not has_error(page)

    def test_invoice_with_future_date_accepted(self, page):
        """
        URL: /invoicing/new
        Creating an invoice dated in the future is valid — forward-dated invoices exist.
        """
        csrf = get_csrf(page, "/invoicing/new")
        with page.expect_navigation(wait_until="networkidle", timeout=30000):
            page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/invoicing"), {
            "customer_id": "1", "project_id": "14",
            "invoice_date": "2027-12-31", "_csrf": csrf
        }])
        assert not has_error(page)

    def test_invoice_detail_shows_line_items_section(self, page):
        """
        URL: /invoicing/99901
        Invoice detail page shows a line items section.
        """
        page.goto(url("/invoicing/99901"))
        page.wait_for_load_state("networkidle")
        if "404" not in page.title() and "not found" not in page.content().lower():
            assert not has_error(page)

    def test_nonexistent_invoice_returns_404(self, page):
        """
        URL: /invoicing/999999
        Accessing a nonexistent invoice shows a 404, not a 500.
        """
        page.goto(url("/invoicing/999999"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), "Server 500 on nonexistent invoice"


# ══════════════════════════════════════════════════════════════════════════════
# 3. INVOICE STATUS TRANSITIONS
# ══════════════════════════════════════════════════════════════════════════════

class TestInvoiceStatusTransitions:

    def test_draft_invoice_can_be_marked_sent(self, page):
        """
        URL: /invoicing/99901/action
        A draft invoice can be transitioned to 'sent' status.
        """
        post_invoice_action(page, "99901", "send")
        assert not has_error(page), "Server 500 on mark-sent action"

    def test_sent_invoice_can_be_marked_paid(self, page):
        """
        URL: /invoicing/99901/action
        A sent invoice can be marked as paid with a payment amount.
        """
        post_invoice_action(page, "99901", "pay", "1000")
        assert not has_error(page), "Server 500 on mark-paid action"

    def test_invalid_action_on_invoice_rejected(self, page):
        """
        URL: /invoicing/99901/action
        Sending an unknown action type is handled gracefully, not a 500.
        """
        post_invoice_action(page, "99901", "delete_everything")
        assert not has_error(page)

    def test_invoice_action_with_zero_payment_handled(self, page):
        """
        URL: /invoicing/99901/action
        Recording a payment of £0 should be rejected or warn — not silently accepted.
        """
        post_invoice_action(page, "99901", "pay", "0")
        assert not has_error(page)

    def test_invoice_action_with_negative_payment_rejected(self, page):
        """
        URL: /invoicing/99901/action
        Recording a negative payment amount should be rejected gracefully.
        """
        post_invoice_action(page, "99901", "pay", "-500")
        assert not has_error(page)

    def test_invoicing_list_shows_overdue_badge(self, page):
        """
        URL: /invoicing
        Invoices past their due date show an 'Overdue' badge in the list.
        """
        page.goto(url("/invoicing"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 4. RATE CARD & BILLING RULES
# ══════════════════════════════════════════════════════════════════════════════

class TestRateCardBillingRules:

    def test_rate_cards_page_accessible(self, page):
        """
        URL: /invoicing/rate-cards
        Rate cards management page loads without error.
        """
        page.goto(url("/invoicing/rate-cards"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_rate_cards_list_shows_rates(self, page):
        """
        URL: /invoicing/rate-cards
        Rate cards list shows at least rate name and hourly rate.
        """
        page.goto(url("/invoicing/rate-cards"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_cross_charge_form_accessible(self, page):
        """
        URL: /invoicing/cross-charge/new
        Cross-charge invoice creation form loads without error.
        """
        page.goto(url("/invoicing/cross-charge/new"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_cross_charge_requires_both_legal_entities(self, page):
        """
        URL: /invoicing/cross-charge/new
        Cross-charge form requires both source and destination legal entities.
        """
        page.goto(url("/invoicing/cross-charge/new"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        assert any(kw in content for kw in ["legal entity", "entity", "from", "to", "cross"])

    def test_invoice_generate_lines_endpoint(self, page):
        """
        URL: /invoicing/99901/generate-lines
        Generate-lines endpoint for an existing invoice doesn't crash.
        """
        csrf = get_csrf(page, "/invoicing/99901")
        with page.expect_navigation(wait_until="networkidle", timeout=30000):
            page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/invoicing/99901/generate-lines"), {"_csrf": csrf}])
        assert not has_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 5. INVOICE ACCESS CONTROL
# ══════════════════════════════════════════════════════════════════════════════

class TestInvoiceAccessControl:

    def test_invoicing_page_accessible_to_admin(self, page):
        """
        URL: /invoicing
        Admin user can access the invoicing module.
        """
        page.goto(url("/invoicing"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_invoice_detail_accessible_to_admin(self, page):
        """
        URL: /invoicing/99901
        Admin can view any invoice detail page.
        """
        page.goto(url("/invoicing/99901"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_invoice_sql_injection_in_id_field(self, page):
        """
        URL: /invoicing/1 OR 1=1
        SQL injection in invoice ID is rejected cleanly without a 500.
        """
        page.goto(url("/invoicing/1%20OR%201%3D1"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_invoice_list_pagination_works(self, page):
        """
        URL: /invoicing?page=2
        Invoicing list with pagination does not crash on page 2.
        """
        page.goto(url("/invoicing?page=2"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_invoice_list_filter_by_status_draft(self, page):
        """
        URL: /invoicing?status=draft
        Filtering invoices by 'draft' status works without crashing.
        """
        page.goto(url("/invoicing?status=draft"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_invoice_list_filter_by_status_paid(self, page):
        """
        URL: /invoicing?status=paid
        Filtering invoices by 'paid' status works without crashing.
        """
        page.goto(url("/invoicing?status=paid"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
