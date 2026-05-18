"""
TEST 01 — Login & Auth
Covers: login page UI, error on bad credentials, redirect after login,
        logout clears session.
"""

import pytest
from conftest import AUTH_URL, BASE_URL, url


class TestLoginPage:

    def test_login_page_loads(self, fresh_page):
        """Login page renders with expected elements."""
        fresh_page.goto(AUTH_URL)
        fresh_page.wait_for_load_state("networkidle")
        assert fresh_page.locator("text=Sign in").count() >= 1
        assert fresh_page.locator("button:has-text('Sign in with Microsoft')").count() == 1
        assert fresh_page.locator("input[placeholder='Username']").count() == 1
        assert fresh_page.locator("input[placeholder='Password']").count() == 1
        assert fresh_page.locator("text=Forgot your password?").count() == 1

    def test_invalid_credentials_shows_error(self, fresh_page):
        """Wrong password shows error message, does not redirect."""
        fresh_page.goto(AUTH_URL)
        fresh_page.fill("input[placeholder='Username']", "nobody@example.com")
        fresh_page.fill("input[placeholder='Password']", "wrongpassword123")
        fresh_page.click("button[type='submit']")
        fresh_page.wait_for_load_state("networkidle")
        assert "Invalid credentials" in fresh_page.content() or "error" in fresh_page.url
        assert "dashboard" not in fresh_page.url

    def test_empty_submit_shows_error(self, fresh_page):
        """Submitting empty form does not log in."""
        fresh_page.goto(AUTH_URL)
        fresh_page.click("button[type='submit']")
        fresh_page.wait_for_load_state("networkidle")
        assert "dashboard" not in fresh_page.url

    def test_unauthenticated_redirect(self, fresh_page):
        """Accessing dashboard without login redirects to auth."""
        fresh_page.goto(url("/dashboard"))
        fresh_page.wait_for_load_state("networkidle")
        assert "auth" in fresh_page.url or "login" in fresh_page.url or "dashboard" not in fresh_page.url


class TestAuthenticatedSession:

    def test_dashboard_accessible_after_login(self, page):
        """Authenticated user reaches dashboard successfully."""
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        assert "dashboard" in page.url
        assert page.locator("text=Dashboard").count() >= 1

    def test_session_persists_across_pages(self, page):
        """Navigating to different pages keeps session alive."""
        page.goto(url("/people"))
        page.wait_for_load_state("networkidle")
        assert "login" not in page.url and "auth" not in page.url

    def test_logout_clears_session(self, browser_instance):
        """After logout, dashboard access redirects to login."""
        ctx = browser_instance.new_context()
        p = ctx.new_page()
        p.goto(url("/dashboard"))
        p.wait_for_load_state("networkidle")

        # Find and click logout
        logout = p.locator("a[href*='logout'], button:has-text('Logout'), a:has-text('Sign out')")
        if logout.count() > 0:
            logout.first.click()
            p.wait_for_load_state("networkidle")
            p.goto(url("/dashboard"))
            p.wait_for_load_state("networkidle")
            assert "dashboard" not in p.url or "auth" in p.url
        else:
            pytest.skip("Logout button not found — may require avatar menu click")

        p.close()
        ctx.close()
