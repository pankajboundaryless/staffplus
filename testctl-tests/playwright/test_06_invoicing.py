"""
TEST 06 — Invoicing Module
Real URLs: /invoicing, /invoicing/new, /invoicing/rate-cards,
           /subscriptions, /products, /invoicing/reminders
"""

import pytest
import time
from conftest import url, has_error

TIMESTAMP = str(int(time.time()))


class TestInvoicingPages:

    def test_invoices_page_loads(self, page):
        page.goto(url("/invoicing"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_rate_cards_page_loads(self, page):
        page.goto(url("/invoicing/rate-cards"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_reminders_page_loads(self, page):
        page.goto(url("/invoicing/reminders"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_subscriptions_page_loads(self, page):
        page.goto(url("/subscriptions"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_products_page_loads(self, page):
        page.goto(url("/products"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_cross_charge_page_loads(self, page):
        page.goto(url("/admin/cross-charge-discounts"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)


class TestInvoiceList:

    def test_invoices_list_renders(self, page):
        page.goto(url("/invoicing"))
        page.wait_for_load_state("networkidle")
        has_table = page.locator("table").count() >= 1
        has_cards = page.locator(".card, .invoice-row").count() >= 1
        has_empty = "invoice" in page.content().lower()
        assert has_table or has_cards or has_empty

    def test_new_invoice_button_present(self, page):
        page.goto(url("/invoicing"))
        page.wait_for_load_state("networkidle")
        btn = page.get_by_text("New Invoice").or_(page.get_by_text("New invoice")).or_(
              page.get_by_text("Create invoice"))
        assert btn.count() >= 1 or page.locator("a[href*='invoicing/new']").count() >= 1

    def test_invoice_status_badges_present(self, page):
        page.goto(url("/invoicing"))
        page.wait_for_load_state("networkidle")
        if page.locator("table tbody tr, .card").count() >= 1:
            content = page.content().lower()
            assert any(s in content for s in ["draft", "sent", "paid", "overdue"])


class TestCreateInvoice:

    def test_new_invoice_form_loads(self, page):
        page.goto(url("/invoicing/new"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert page.locator("form").count() >= 1

    def test_invoice_form_fields_present(self, page):
        page.goto(url("/invoicing/new"))
        page.wait_for_load_state("networkidle")
        assert page.locator("select[name='customer_id']").count() >= 1 or \
               "customer" in page.content().lower()
        assert page.locator("input[name='invoice_date'], input[type='date']").count() >= 1

    def test_empty_invoice_form_validation(self, page):
        page.goto(url("/invoicing/new"))
        page.wait_for_load_state("networkidle")
        submit = page.locator("button[type='submit'], input[type='submit']").first
        submit.scroll_into_view_if_needed()
        submit.click()
        page.wait_for_load_state("networkidle")
        assert not has_error(page), "Server error on empty invoice submit"
        content = page.content().lower()
        assert "required" in content or "invalid" in content or \
               page.locator(".is-invalid, .alert-danger, .error").count() >= 1

    def test_create_draft_invoice(self, page):
        page.goto(url("/invoicing/new"))
        page.wait_for_load_state("networkidle")

        customer = page.locator("select[name='customer_id']")
        if customer.count() == 0:
            pytest.skip("Customer field not found on invoice form")
        if customer.locator("option:not([value=''])").count() == 0:
            pytest.skip("No customers available")

        customer.select_option(index=1)

        date = page.locator("input[name='invoice_date']")
        if date.count() > 0:
            date.fill("2026-05-07")

        due = page.locator("input[name='due_date']")
        if due.count() > 0:
            due.fill("2026-06-07")

        currency = page.locator("select[name='currency']")
        if currency.count() > 0:
            currency.select_option("CHF")

        submit = page.locator("button[type='submit'], input[type='submit']").first
        submit.scroll_into_view_if_needed()
        submit.click()
        page.wait_for_load_state("networkidle")
        assert not has_error(page), "Server error after invoice creation"
        assert page.locator(".alert-danger").count() == 0

    def test_created_invoice_is_draft(self, page):
        page.goto(url("/invoicing"))
        page.wait_for_load_state("networkidle")
        assert "draft" in page.content().lower() or \
               page.locator("[class*='draft']").count() >= 1
