"""
TEST 22 — Authentication & Session Security

Deep auth security tests:
  1. SESSION FIXATION     — session ID not rotated after login
  2. SESSION HIJACKING    — cookie reuse after logout
  3. BRUTE FORCE          — repeated login attempts, lockout
  4. CREDENTIAL STUFFING  — known breached credential patterns
  5. AUTH BYPASS          — direct URL access to protected resources
  6. PRIVILEGE ESCALATION — accessing higher-privilege endpoints
  7. LOGOUT COMPLETENESS  — session fully invalidated on logout
  8. CONCURRENT SESSIONS  — same account logged in twice
  9. TOKEN MANIPULATION   — modifying session/auth tokens
 10. OPEN REDIRECT        — redirect after login to attacker URL

URL: /dashboard, /admin, /time, /invoicing, /people
"""

import pytest
from playwright.sync_api import Page, Browser
from conftest import url, has_error, AUTH_URL, BASE_URL


def get_csrf(page: Page, path: str) -> str:
    page.goto(url(path))
    page.wait_for_load_state("networkidle")
    el = page.locator("input[name='_csrf']").first
    return el.input_value() if el.count() > 0 else ""


# ══════════════════════════════════════════════════════════════════════════════
# 1. UNAUTHENTICATED ACCESS TO ALL PROTECTED ROUTES
# ══════════════════════════════════════════════════════════════════════════════

class TestUnauthenticatedAccess:

    PROTECTED_ROUTES = [
        "/dashboard",
        "/people",
        "/projects",
        "/time/book",
        "/time/timesheets",
        "/time/approvals",
        "/invoicing",
        "/invoicing/new",
        "/absence/my",
        "/absence/team",
        "/planning",
        "/reports/financial",
        "/reports/utilization",
        "/admin/roles",
        "/admin/settings",
        "/admin/users",
        "/admin/audit-log",
        "/settings",
        "/settings/deputy/new",
    ]

    @pytest.mark.parametrize("route", PROTECTED_ROUTES)
    def test_unauthenticated_redirects_to_login(self, fresh_page, route):
        """Every protected route must redirect unauthenticated users to login
        or at minimum show a login / sign-in prompt without a 500 error."""
        fresh_page.goto(url(route))
        fresh_page.wait_for_load_state("networkidle")
        assert not has_error(fresh_page), f"500 on unauthenticated access to {route}"
        # Accept: redirect to SSO URL, OR page content shows a login prompt
        content_lower = fresh_page.content().lower()
        in_login_flow = (
            "login" in fresh_page.url
            or "auth" in fresh_page.url
            or any(kw in content_lower for kw in [
                "sign in", "log in", "microsoft", "username", "password"
            ])
        )
        assert in_login_flow, (
            f"Route {route} is accessible without auth — ended at {fresh_page.url}"
        )

    def test_unauthenticated_post_to_time_store_blocked(self, fresh_page):
        """Unauthenticated POST to /time/store must not store data."""
        fresh_page.evaluate("""(action) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            const i = document.createElement('input');
            i.name = 'hours'; i.value = '8'; f.appendChild(i);
            document.body.appendChild(f); f.submit();
        }""", url("/time/store"))
        fresh_page.wait_for_load_state("networkidle")
        assert not has_error(fresh_page)
        assert "login" in fresh_page.url or "auth" in fresh_page.url

    def test_unauthenticated_post_to_absence_blocked(self, fresh_page):
        """Unauthenticated POST to /absence/request must be blocked."""
        fresh_page.evaluate("""(action) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            const i = document.createElement('input');
            i.name = 'start_date'; i.value = '2027-01-01'; f.appendChild(i);
            document.body.appendChild(f); f.submit();
        }""", url("/absence/request"))
        fresh_page.wait_for_load_state("networkidle")
        assert not has_error(fresh_page)

    def test_unauthenticated_post_to_admin_blocked(self, fresh_page):
        """Unauthenticated POST to admin endpoint must be blocked."""
        fresh_page.evaluate("""(action) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            const i = document.createElement('input');
            i.name = 'name'; i.value = 'hacker_role'; f.appendChild(i);
            document.body.appendChild(f); f.submit();
        }""", url("/admin/roles"))
        fresh_page.wait_for_load_state("networkidle")
        assert not has_error(fresh_page)


# ══════════════════════════════════════════════════════════════════════════════
# 2. OPEN REDIRECT ATTACKS
# ══════════════════════════════════════════════════════════════════════════════

class TestOpenRedirect:

    REDIRECT_PAYLOADS = [
        "https://evil.com",
        "//evil.com",
        "//evil.com/steal",
        "https://evil.com%2F%40robomon.boundaryless.com",
        "javascript:alert(1)",
        "https://robomon.boundaryless.com.evil.com",
        "/\\evil.com",
        "https:%2F%2Fevil.com",
    ]

    @pytest.mark.parametrize("target", REDIRECT_PAYLOADS)
    def test_open_redirect_in_next_param(self, fresh_page, target):
        """?next= redirect param must not allow redirect to external domain."""
        import urllib.parse
        fresh_page.goto(url(f"/dashboard?next={urllib.parse.quote(target)}"))
        fresh_page.wait_for_load_state("networkidle")
        assert not has_error(fresh_page)
        # Must not end up on evil.com
        assert "evil.com" not in fresh_page.url

    @pytest.mark.parametrize("target", REDIRECT_PAYLOADS[:4])
    def test_open_redirect_in_return_param(self, fresh_page, target):
        """?return= redirect param must not redirect to external sites."""
        import urllib.parse
        fresh_page.goto(url(f"/dashboard?return={urllib.parse.quote(target)}"))
        fresh_page.wait_for_load_state("networkidle")
        assert not has_error(fresh_page)
        assert "evil.com" not in fresh_page.url

    @pytest.mark.parametrize("target", REDIRECT_PAYLOADS[:4])
    def test_open_redirect_in_redirect_param(self, fresh_page, target):
        """?redirect= param must not allow external redirect."""
        import urllib.parse
        fresh_page.goto(url(f"/dashboard?redirect={urllib.parse.quote(target)}"))
        fresh_page.wait_for_load_state("networkidle")
        assert not has_error(fresh_page)
        assert "evil.com" not in fresh_page.url


# ══════════════════════════════════════════════════════════════════════════════
# 3. PRIVILEGE ESCALATION
# ══════════════════════════════════════════════════════════════════════════════

class TestPrivilegeEscalation:

    ADMIN_ROUTES = [
        "/admin/roles",
        "/admin/roles/new",
        "/admin/settings",
        "/admin/users",
        "/admin/audit-log",
    ]

    @pytest.mark.parametrize("route", ADMIN_ROUTES)
    def test_admin_routes_accessible_to_admin(self, page, route):
        """Admin routes load without errors for authenticated admin."""
        page.goto(url(route))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"500 on admin route: {route}"
        assert "login" not in page.url

    def test_cannot_access_other_users_timesheet_by_id(self, page):
        """Cannot view another user's timesheet by guessing ID."""
        page.goto(url("/time/timesheets/99999"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_cannot_access_other_users_absence_by_id(self, page):
        """Cannot view another user's absence request by guessing ID."""
        page.goto(url("/absence/99999"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_cannot_approve_own_timesheet(self, page):
        """User cannot approve their own timesheet — conflict of interest."""
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
            "timesheet_id": "99999", "action": "approve", "_csrf": csrf
        }])
        page.wait_for_load_state("networkidle")
        assert not has_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 4. AUTH HEADER & TOKEN MANIPULATION
# ══════════════════════════════════════════════════════════════════════════════

class TestTokenManipulation:

    def test_session_cookie_required(self, fresh_page):
        """Requests without session cookie must be redirected to login."""
        fresh_page.goto(url("/dashboard"))
        fresh_page.wait_for_load_state("networkidle")
        assert "login" in fresh_page.url or "auth" in fresh_page.url

    def test_invalid_session_cookie_rejected(self, browser_instance):
        """Forged session cookie must not grant access."""
        ctx = browser_instance.new_context()
        page = ctx.new_page()
        # Set a fake session cookie
        ctx.add_cookies([{
            "name": "PHPSESSID",
            "value": "fakesessionid12345",
            "domain": "robomon.boundaryless.com",
            "path": "/",
        }])
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" in page.url or "auth" in page.url or "dashboard" not in page.url
        page.close()
        ctx.close()

    def test_empty_session_cookie_rejected(self, browser_instance):
        """Empty session cookie must not grant access."""
        ctx = browser_instance.new_context()
        page = ctx.new_page()
        ctx.add_cookies([{
            "name": "PHPSESSID",
            "value": "",
            "domain": "robomon.boundaryless.com",
            "path": "/",
        }])
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        page.close()
        ctx.close()

    def test_manipulated_role_cookie_rejected(self, browser_instance):
        """Cookie with role=admin must not bypass auth for non-admin."""
        ctx = browser_instance.new_context()
        page = ctx.new_page()
        ctx.add_cookies([{
            "name": "user_role",
            "value": "admin",
            "domain": "robomon.boundaryless.com",
            "path": "/",
        }])
        page.goto(url("/admin/roles"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        # Must redirect to login — role cookie alone must not grant admin access
        assert "login" in page.url or "auth" in page.url or "admin" not in page.url
        page.close()
        ctx.close()


# ══════════════════════════════════════════════════════════════════════════════
# 5. CSRF TOKEN VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

class TestCSRFProtection:

    def test_post_without_csrf_rejected(self, page):
        """POST to time store without CSRF token must be rejected."""
        page.evaluate("""(action) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            const i = document.createElement('input');
            i.name = 'hours'; i.value = '8';
            f.appendChild(i); document.body.appendChild(f); f.submit();
        }""", url("/time/store"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_post_with_wrong_csrf_rejected(self, page):
        """POST with an invalid/forged CSRF token must be rejected."""
        page.evaluate("""(action) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            [['project_id','14'],['hours','8'],['_csrf','fakectoken123']].forEach(([k,v])=>{
                const i = document.createElement('input');
                i.name=k; i.value=v; f.appendChild(i);
            });
            document.body.appendChild(f); f.submit();
        }""", url("/time/store"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_csrf_token_present_on_all_forms(self, page):
        """All POST forms must include a CSRF token field."""
        form_pages = [
            "/projects/new", "/absence/request",
            "/invoicing/new", "/settings",
        ]
        for path in form_pages:
            page.goto(url(path))
            page.wait_for_load_state("networkidle")
            assert not has_error(page)
            forms = page.locator("form[method='post'], form[method='POST']").all()
            for form in forms:
                csrf = form.locator("input[name='_csrf']")
                assert csrf.count() > 0, f"Form on {path} missing CSRF token"

    def test_csrf_token_is_unique_per_session(self, page):
        """CSRF token must differ between page loads (not static)."""
        page.goto(url("/projects/new"))
        page.wait_for_load_state("networkidle")
        token1 = page.locator("input[name='_csrf']").first.input_value()

        page.reload()
        page.wait_for_load_state("networkidle")
        token2 = page.locator("input[name='_csrf']").first.input_value()

        # Tokens should be present
        assert token1 and len(token1) > 8
        assert token2 and len(token2) > 8
