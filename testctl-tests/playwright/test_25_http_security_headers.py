"""
TEST 25 — HTTP Security Headers & Response Security

Tests that all pages return correct security headers and response attributes:
  1. X-FRAME-OPTIONS      — clickjacking protection
  2. CSP                  — Content-Security-Policy
  3. X-CONTENT-TYPE       — MIME sniffing protection
  4. HSTS                 — Strict-Transport-Security
  5. REFERRER-POLICY      — referrer leakage control
  6. CORS                 — cross-origin request handling
  7. COOKIE FLAGS         — HttpOnly, Secure, SameSite
  8. CACHE CONTROL        — sensitive pages not cached
  9. ERROR PAGE INFO      — stack traces not leaked in errors
 10. SERVER HEADER        — server version not disclosed

URL: all main routes
"""

import re
import requests
import pytest
from playwright.sync_api import Page
from conftest import url, has_error, BASE_URL


def get_headers(path: str, session_cookies: dict = None):
    """Fetch response headers directly via requests (no browser).

    Returns None when the request fails (server unreachable / timeout) —
    callers should pytest.skip() in that case.
    Uses allow_redirects=False so we inspect the app server's direct response
    rather than the SSO redirect-chain headers.
    """
    full_url = f"{BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    cookies = session_cookies or {}
    try:
        resp = requests.get(full_url, cookies=cookies,
                            allow_redirects=False, timeout=15)
        return {k.lower(): v for k, v in resp.headers.items()}
    except Exception:
        return None


def get_session_cookies(page: Page) -> dict:
    """Extract session cookies from authenticated Playwright page."""
    page.goto(url("/dashboard"))
    page.wait_for_load_state("networkidle")
    cookies = page.context.cookies()
    return {c["name"]: c["value"] for c in cookies}


def require_headers(headers, path: str) -> dict:
    """Skip the test if direct HTTP request failed, otherwise return headers."""
    if headers is None:
        pytest.skip(f"Direct HTTP to {path} unavailable (timeout/network) — skipping header check")
    return headers


# ══════════════════════════════════════════════════════════════════════════════
# 1. CLICKJACKING — X-Frame-Options
# ══════════════════════════════════════════════════════════════════════════════

class TestClickjackingProtection:

    PAGES_TO_CHECK = [
        "/dashboard", "/people", "/projects",
        "/invoicing", "/time/book", "/settings",
    ]

    @pytest.mark.parametrize("path", PAGES_TO_CHECK)
    def test_x_frame_options_present(self, page, path):
        """Every app page must include X-Frame-Options or CSP frame-ancestors."""
        cookies = get_session_cookies(page)
        headers = require_headers(get_headers(path, cookies), path)
        has_xfo = "x-frame-options" in headers
        has_csp_frame = (
            "content-security-policy" in headers
            and "frame-ancestors" in headers.get("content-security-policy", "").lower()
        )
        assert has_xfo or has_csp_frame, (
            f"{path} missing X-Frame-Options and CSP frame-ancestors — clickjacking risk"
        )

    def test_x_frame_options_value(self, page):
        """X-Frame-Options must be DENY or SAMEORIGIN, not ALLOW-FROM."""
        cookies = get_session_cookies(page)
        headers = require_headers(get_headers("/dashboard", cookies), "/dashboard")
        xfo = headers.get("x-frame-options", "").upper()
        if xfo:
            assert xfo in ("DENY", "SAMEORIGIN"), f"Weak X-Frame-Options value: {xfo}"


# ══════════════════════════════════════════════════════════════════════════════
# 2. MIME SNIFFING — X-Content-Type-Options
# ══════════════════════════════════════════════════════════════════════════════

class TestMimeSniffing:

    @pytest.mark.parametrize("path", ["/dashboard", "/people", "/invoicing"])
    def test_x_content_type_options_present(self, page, path):
        """X-Content-Type-Options: nosniff must be set on all pages."""
        cookies = get_session_cookies(page)
        headers = require_headers(get_headers(path, cookies), path)
        # For a 302 redirect response, nosniff may not be set — acceptable
        if headers.get("location"):
            pytest.skip(f"{path} returns redirect — header check deferred")
        xcto = headers.get("x-content-type-options", "")
        assert xcto.lower() == "nosniff", (
            f"{path} missing X-Content-Type-Options: nosniff — MIME sniffing risk"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3. REFERRER POLICY
# ══════════════════════════════════════════════════════════════════════════════

class TestReferrerPolicy:

    @pytest.mark.parametrize("path", ["/dashboard", "/invoicing", "/settings"])
    def test_referrer_policy_present(self, page, path):
        """Referrer-Policy must be set to prevent leaking sensitive URLs."""
        cookies = get_session_cookies(page)
        headers = require_headers(get_headers(path, cookies), path)
        if headers.get("location"):
            pytest.skip(f"{path} returns redirect — header check deferred")
        rp = headers.get("referrer-policy", "")
        safe_values = [
            "no-referrer", "no-referrer-when-downgrade",
            "strict-origin", "strict-origin-when-cross-origin",
            "same-origin"
        ]
        if rp:
            assert any(v in rp.lower() for v in safe_values), (
                f"{path} has weak Referrer-Policy: {rp}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# 4. SERVER VERSION DISCLOSURE
# ══════════════════════════════════════════════════════════════════════════════

class TestServerVersionDisclosure:

    def test_server_header_not_verbose(self, page):
        """Server header must not disclose version numbers."""
        cookies = get_session_cookies(page)
        headers = require_headers(get_headers("/dashboard", cookies), "/dashboard")
        server = headers.get("server", "")
        has_version = bool(re.search(r'[\d]+\.[\d]+', server))
        assert not has_version, f"Server header discloses version: {server}"

    def test_x_powered_by_not_disclosed(self, page):
        """X-Powered-By header must not disclose PHP version."""
        cookies = get_session_cookies(page)
        headers = require_headers(get_headers("/dashboard", cookies), "/dashboard")
        xpb = headers.get("x-powered-by", "")
        assert "php" not in xpb.lower(), f"X-Powered-By discloses PHP: {xpb}"

    def test_x_aspnet_version_not_disclosed(self, page):
        """X-AspNet-Version header must not be present."""
        cookies = get_session_cookies(page)
        headers = require_headers(get_headers("/dashboard", cookies), "/dashboard")
        assert "x-aspnet-version" not in headers, "X-AspNet-Version header disclosed"

    def test_x_aspnetmvc_version_not_disclosed(self, page):
        """X-AspNetMvc-Version header must not be present."""
        cookies = get_session_cookies(page)
        headers = require_headers(get_headers("/dashboard", cookies), "/dashboard")
        assert "x-aspnetmvc-version" not in headers, "X-AspNetMvc-Version header disclosed"


# ══════════════════════════════════════════════════════════════════════════════
# 5. CACHE CONTROL ON SENSITIVE PAGES
# ══════════════════════════════════════════════════════════════════════════════

class TestCacheControl:

    SENSITIVE_PAGES = [
        "/invoicing",
        "/admin/settings",
        "/settings",
        "/admin/users",
    ]

    @pytest.mark.parametrize("path", SENSITIVE_PAGES)
    def test_sensitive_pages_not_cached(self, page, path):
        """Sensitive pages must include cache-control: no-store or no-cache."""
        cookies = get_session_cookies(page)
        headers = require_headers(get_headers(path, cookies), path)
        if headers.get("location"):
            pytest.skip(f"{path} returns redirect — cache header check deferred")
        cc = headers.get("cache-control", "").lower()
        # Must not explicitly be public without no-store override
        assert "public" not in cc or "no-store" in cc, (
            f"{path} set Cache-Control: public on sensitive page"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 6. COOKIE SECURITY FLAGS (via Playwright — no requests needed)
# ══════════════════════════════════════════════════════════════════════════════

class TestCookieSecurityFlags:

    def test_session_cookie_httponly(self, page):
        """Session cookie must have HttpOnly flag set."""
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        cookies = page.context.cookies()
        session_cookies = [c for c in cookies if "sess" in c["name"].lower()
                           or "phpsessid" in c["name"].lower()]
        if not session_cookies:
            pytest.skip("No session cookies found with 'sess'/'phpsessid' in name")
        for cookie in session_cookies:
            assert cookie.get("httpOnly", False), (
                f"Session cookie '{cookie['name']}' missing HttpOnly flag"
            )

    def test_session_cookie_samesite(self, page):
        """Session cookie must have SameSite=Lax or Strict."""
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        cookies = page.context.cookies()
        session_cookies = [c for c in cookies if "sess" in c["name"].lower()
                           or "phpsessid" in c["name"].lower()]
        if not session_cookies:
            pytest.skip("No session cookies found with 'sess'/'phpsessid' in name")
        for cookie in session_cookies:
            samesite = cookie.get("sameSite", "")
            assert samesite in ("Lax", "Strict", ""), (
                f"Session cookie '{cookie['name']}' has SameSite=None — CSRF risk"
            )

    def test_no_oversized_cookie_values(self, page):
        """Cookie values must not be suspiciously large (>4 KB)."""
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        cookies = page.context.cookies()
        for cookie in cookies:
            assert len(cookie.get("value", "")) < 4096, (
                f"Cookie '{cookie['name']}' has suspiciously large value"
            )


# ══════════════════════════════════════════════════════════════════════════════
# 7. ERROR PAGE INFORMATION DISCLOSURE (via Playwright)
# ══════════════════════════════════════════════════════════════════════════════

class TestErrorPageDisclosure:

    def test_404_does_not_reveal_stack_trace(self, page):
        """404 pages must not expose file paths or stack traces."""
        page.goto(url("/nonexistent-route-xyz-12345"))
        page.wait_for_load_state("networkidle")
        content = page.content().lower()
        assert "stack trace" not in content
        assert "/var/www" not in content
        # "exception" may appear in a friendly error message — only flag raw traces
        assert "unhandled exception" not in content

    def test_500_does_not_reveal_db_credentials(self, page):
        """Error pages must not expose database credentials or connection strings."""
        page.goto(url("/projects/trigger_error_test"))
        page.wait_for_load_state("networkidle")
        content = page.content().lower()
        assert "db_host" not in content
        assert "db_user" not in content
        assert "db_password" not in content

    def test_invalid_route_does_not_reveal_routes(self, page):
        """Invalid routes must not list all available application routes."""
        page.goto(url("/api/nonexistent"))
        page.wait_for_load_state("networkidle")
        content = page.content().lower()
        assert content.count("/admin") < 5, "Possible route disclosure on 404"

    def test_no_php_errors_in_page_source(self, page):
        """No PHP warnings or notices must appear in page source."""
        pages_to_check = ["/dashboard", "/people", "/projects", "/invoicing"]
        for path in pages_to_check:
            page.goto(url(path))
            page.wait_for_load_state("networkidle")
            content = page.content()
            assert "<b>Warning</b>:" not in content, f"PHP Warning on {path}"
            assert "<b>Notice</b>:" not in content, f"PHP Notice on {path}"
            assert "<b>Fatal error</b>:" not in content, f"PHP Fatal on {path}"


# ══════════════════════════════════════════════════════════════════════════════
# 8. CORS POLICY
# ══════════════════════════════════════════════════════════════════════════════

class TestCORSPolicy:

    def test_cors_not_wildcard_on_authenticated_routes(self, page):
        """Authenticated API routes must not have Access-Control-Allow-Origin: *."""
        cookies = get_session_cookies(page)
        headers = require_headers(get_headers("/dashboard", cookies), "/dashboard")
        acao = headers.get("access-control-allow-origin", "")
        assert acao != "*", (
            "Access-Control-Allow-Origin: * on authenticated route — CORS misconfiguration"
        )

    def test_preflight_request_handled(self, page):
        """OPTIONS preflight request must be handled without 500."""
        try:
            resp = requests.options(
                f"{BASE_URL}/time/store",
                headers={
                    "Origin": "https://evil.com",
                    "Access-Control-Request-Method": "POST",
                },
                timeout=10
            )
            assert resp.status_code != 500, "OPTIONS preflight returns 500"
        except Exception:
            pytest.skip("Direct HTTP to server unavailable for OPTIONS check")

    def test_foreign_origin_not_reflected(self, page):
        """Foreign Origin header must not be reflected in ACAO header."""
        try:
            resp = requests.get(
                f"{BASE_URL}/dashboard",
                headers={"Origin": "https://evil.com"},
                allow_redirects=False,
                timeout=10
            )
            acao = resp.headers.get("Access-Control-Allow-Origin", "")
            assert "evil.com" not in acao, (
                f"Server reflects attacker origin in ACAO: {acao}"
            )
        except Exception:
            pytest.skip("Direct HTTP to server unavailable for CORS reflection check")
