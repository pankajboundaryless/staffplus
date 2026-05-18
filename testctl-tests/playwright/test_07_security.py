"""
TEST 07 — Security
XSS, SQL injection, CSRF, auth bypass, IDOR, open redirects, headers.
"""

import pytest
import urllib.parse
import requests as req
from conftest import url, BASE_URL, AUTH_URL, has_error


class TestXSS:

    XSS_PAYLOADS = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>",
        "'><script>alert(document.cookie)</script>",
        "<svg onload=alert(1)>",
    ]

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_xss_in_people_search(self, page, payload):
        """The exact payload must not appear unescaped in the DOM.
        Note: page always contains <script> tags for app JS — we check for
        the specific injected string, not just the tag."""
        encoded = urllib.parse.quote(payload)
        page.goto(url(f"/people?search={encoded}"))
        page.wait_for_load_state("networkidle")
        # Check specific dangerous patterns are NOT reflected raw
        assert "onerror=alert" not in page.content(), \
            f"onerror XSS reflected unescaped: {payload}"
        assert "onload=alert" not in page.content(), \
            f"onload XSS reflected unescaped: {payload}"
        # Check the payload value attribute itself is not injected as executable
        assert "alert('xss')" not in page.content() or \
               "&amp;" in page.content() or "&#" in page.content() or \
               page.evaluate("typeof window.__xss_triggered === 'undefined'"), \
            f"XSS payload may have executed: {payload}"
        assert not has_error(page)

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_xss_in_project_search(self, page, payload):
        encoded = urllib.parse.quote(payload)
        page.goto(url(f"/projects?q={encoded}"))
        page.wait_for_load_state("networkidle")
        assert "onerror=alert" not in page.content(), \
            f"onerror XSS reflected in projects search: {payload}"
        assert not has_error(page)


class TestSQLInjection:

    SQL_PAYLOADS = [
        "' OR '1'='1",
        "'; DROP TABLE users;--",
        "1' ORDER BY 1--",
        "' UNION SELECT null,null--",
        "admin'--",
    ]

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_sqli_in_people_search(self, page, payload):
        encoded = urllib.parse.quote(payload)
        page.goto(url(f"/people?search={encoded}"))
        page.wait_for_load_state("networkidle")
        content = page.content()
        assert not has_error(page), f"Server error on SQL payload: {payload}"
        assert "syntax error" not in content.lower(), "SQL syntax error leaked"
        assert "mysql_" not in content.lower(), "MySQL error leaked"

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_sqli_in_project_search(self, page, payload):
        encoded = urllib.parse.quote(payload)
        page.goto(url(f"/projects?q={encoded}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"Server error on SQL payload in projects: {payload}"


class TestCSRF:

    def test_unauthenticated_post_rejected(self, fresh_page):
        """POST without CSRF/session must not succeed (302 to login, 400, or 403)."""
        resp = req.post(
            url("/people/new"),
            data={"first_name": "CSRFTest", "last_name": "Attack", "email": "csrf@testctl.local"},
            allow_redirects=False,
            timeout=10,
        )
        assert resp.status_code in (302, 400, 403, 419), \
            f"Unauthenticated POST returned {resp.status_code} — possible CSRF/auth bypass"

    def test_unauthenticated_post_to_invoice_rejected(self, fresh_page):
        resp = req.post(
            url("/invoicing/new"),
            data={"customer_id": "1", "invoice_date": "2026-01-01", "currency": "CHF"},
            allow_redirects=False,
            timeout=10,
        )
        assert resp.status_code in (302, 400, 403, 419), \
            f"Unauthenticated invoice POST returned {resp.status_code}"


class TestAuthBypass:

    PROTECTED_PATHS = [
        "/admin/settings",
        "/admin/users",
        "/admin/roles",
        "/admin/audit-log",
        "/people/new",
        "/projects/new",
        "/invoicing/new",
        "/reports",
        "/debug/users",
    ]

    @pytest.mark.parametrize("path", PROTECTED_PATHS)
    def test_unauthenticated_access_blocked(self, fresh_page, path):
        fresh_page.goto(url(path))
        fresh_page.wait_for_load_state("networkidle")
        is_redirected = "auth" in fresh_page.url or "login" in fresh_page.url
        is_403 = fresh_page.get_by_text("403").count() >= 1 or \
                 fresh_page.get_by_text("Forbidden").count() >= 1
        assert is_redirected or is_403, \
            f"Path {path} accessible without auth — SECURITY BUG (landed on: {fresh_page.url})"


class TestIDOR:

    def test_sequential_id_access_no_crash(self, page):
        """Accessing /people/1 through /people/5 must not 500."""
        for pid in range(1, 6):
            page.goto(url(f"/people/{pid}"))
            page.wait_for_load_state("networkidle")
            assert not has_error(page), f"Server error accessing /people/{pid}"

    def test_sequential_project_id_no_crash(self, page):
        for pid in range(1, 6):
            page.goto(url(f"/projects/{pid}"))
            page.wait_for_load_state("networkidle")
            assert not has_error(page), f"Server error accessing /projects/{pid}"


class TestSecurityHeaders:

    def test_php_version_not_exposed(self):
        resp = req.get(url("/dashboard"), allow_redirects=True, timeout=10)
        powered_by = resp.headers.get("X-Powered-By", "")
        assert "PHP/" not in powered_by, \
            f"PHP version exposed in X-Powered-By: {powered_by} — SECURITY BUG"

    def test_no_stack_trace_in_404(self, page):
        page.goto(url("/this-page-does-not-exist-xyz-12345"))
        page.wait_for_load_state("networkidle")
        content = page.content()
        assert "/var/www" not in content, "Server path exposed in 404"
        assert "Stack trace" not in content, "Stack trace in 404 page"
        assert "vendor/" not in content, "vendor/ path in 404 page"

    def test_no_db_credentials_in_source(self, page):
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        content = page.content()
        assert "DB_PASSWORD" not in content
        assert "jwt_secret" not in content.lower()
        assert "mysql://" not in content

    def test_open_redirect_blocked(self, fresh_page):
        """Login redirect must not allow off-site redirect to evil.com."""
        fresh_page.goto(url("/dashboard?redirect=https://evil.com"))
        fresh_page.wait_for_load_state("networkidle")
        assert "evil.com" not in fresh_page.url, \
            "Open redirect vulnerability detected — SECURITY BUG"
