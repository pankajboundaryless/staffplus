"""
test_31_rate_limiting.py — Rate Limiting & Brute Force Protection Tests
=======================================================================
Tests whether the app and SSO layer enforce:
  • Login brute-force protection (lockout / CAPTCHA / delay after N fails)
  • Rate limiting on API endpoints (GET + POST flooding)
  • Rate-limit response headers (X-RateLimit-*, Retry-After)
  • Username enumeration resistance (timing consistency)
  • Data-spam / duplicate-submission prevention
  • Concurrent session flooding

App:  https://robomon.boundaryless.com/test/timetracker/public
SSO:  https://auth.boundaryless.com/public

Auth: session cookie read from .auth/session.json

Pre-probe results (confirmed before writing):
  - GET /people ×30:  all 200, 0 rate-limits
  - POST /time/store ×20: all 302, 0 rate-limits
  - SSO wrong-pass ×15: all 200 ~50ms, no lockout, no CAPTCHA
  - No X-RateLimit-* or Retry-After headers anywhere

Expected outcome: Most security-assertion tests FAIL because rate
limiting is genuinely absent — each failure documents a real bug.
"""

import json
import re
import statistics
import time
from pathlib import Path
from urllib.parse import urljoin

import pytest
import requests
from playwright.sync_api import Page, expect

# ─── Config ──────────────────────────────────────────────────────────────────
BASE     = "https://robomon.boundaryless.com/test/timetracker/public"
SSO_BASE = "https://auth.boundaryless.com/public"
SESSION  = Path(__file__).parent / ".auth" / "session.json"

# ─── Helpers ─────────────────────────────────────────────────────────────────

def load_cookie() -> str:
    with open(SESSION) as f:
        data = json.load(f)
    for c in data.get("cookies", []):
        if c.get("name") == "bmgmt_sess":
            return c["value"]
    raise RuntimeError("bmgmt_sess not found in session.json")


def app_session() -> requests.Session:
    s = requests.Session()
    s.cookies.set("bmgmt_sess", load_cookie(), domain="robomon.boundaryless.com")
    s.headers["User-Agent"] = "StaffPlus-RateLimit-Tests/31"
    return s


def sso_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "StaffPlus-RateLimit-Tests/31"
    return s


def get_csrf_from(session: requests.Session, url: str,
                  field: str = "_csrf") -> str:
    r = session.get(url, timeout=10)
    m = re.search(rf'name="{field}"\s+value="([^"]+)"', r.text)
    return m.group(1) if m else ""


def get_sso_csrf(session: requests.Session) -> str:
    r = session.get(
        f"{SSO_BASE}/login_form.php?app=timetracker-ng-test", timeout=10
    )
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    return m.group(1) if m else ""


def is_rate_limited(r: requests.Response) -> bool:
    """Return True if response indicates rate limiting."""
    if r.status_code == 429:
        return True
    body = r.text.lower()
    keywords = ["too many", "rate limit", "rate-limit", "throttl",
                 "blocked", "try again", "slow down", "retry after"]
    return any(kw in body for kw in keywords)


def has_rate_limit_headers(r: requests.Response) -> bool:
    headers = {k.lower(): v for k, v in r.headers.items()}
    rl_keys = ["x-ratelimit-limit", "x-ratelimit-remaining",
               "x-ratelimit-reset", "ratelimit-limit",
               "retry-after", "x-retry-after"]
    return any(k in headers for k in rl_keys)


def is_sso_locked_out(r: requests.Response) -> bool:
    if r.status_code == 429:
        return True
    body = r.text.lower()
    keywords = ["too many", "locked", "blocked", "captcha",
                 "wait", "throttl", "rate limit", "retry"]
    return any(kw in body for kw in keywords)


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 1 — SSO Login Brute Force
# ═══════════════════════════════════════════════════════════════════════════════

class TestSSORateLimitBruteForce:
    """
    BUG #14: SSO login has no brute-force protection.
    15 rapid wrong-password attempts all succeed instantly at ~50ms each.
    No lockout, no CAPTCHA, no progressive delay.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.responses: list[requests.Response] = []
        self.timings: list[float] = []
        yield

    def _attempt(self, username: str, password: str) -> tuple[requests.Response, float]:
        s = sso_session()
        csrf = get_sso_csrf(s)
        t0 = time.perf_counter()
        r = s.post(
            f"{SSO_BASE}/login_form_submit.php",
            data={"csrf_token": csrf, "username": username, "password": password},
            allow_redirects=True,
            timeout=15,
        )
        elapsed = time.perf_counter() - t0
        return r, elapsed

    def test_sso_no_lockout_after_5_fails(self):
        """BUG #14: Account should lock out after 5 wrong passwords — it doesn't."""
        for i in range(5):
            r, t = self._attempt("tester-1@test.internal", f"WRONG_PASS_{i}")
            self.responses.append(r)
            self.timings.append(t)

        locked = any(is_sso_locked_out(r) for r in self.responses)
        assert locked, (
            "BUG #14 — No lockout after 5 failed SSO login attempts. "
            "All 5 attempts returned HTTP 200 with invalid-credentials message. "
            "Unlimited brute force is possible against the authentication endpoint."
        )

    def test_sso_no_lockout_after_10_fails(self):
        """BUG #14: 10 wrong-password attempts — still no protection."""
        for i in range(10):
            r, t = self._attempt("tester-1@test.internal", f"BRUTE_{i}")
            self.responses.append(r)
            self.timings.append(t)

        locked = any(is_sso_locked_out(r) for r in self.responses)
        assert locked, (
            "BUG #14 — No lockout or rate limiting after 10 consecutive failed "
            "SSO login attempts for the same account. "
            f"All response times: {[f'{t:.2f}s' for t in self.timings]}"
        )

    def test_sso_no_lockout_after_15_fails(self):
        """BUG #14: 15 wrong-password attempts — still HTTP 200 every time."""
        for i in range(15):
            r, t = self._attempt("tester-1@test.internal", f"BRUTE_{i}")
            self.responses.append(r)
            self.timings.append(t)

        locked = any(is_sso_locked_out(r) for r in self.responses)
        http_429 = any(r.status_code == 429 for r in self.responses)
        assert locked or http_429, (
            "BUG #14 — No account lockout, CAPTCHA, or HTTP 429 after 15 rapid "
            f"failed login attempts. "
            f"Avg response time: {statistics.mean(self.timings)*1000:.0f}ms — "
            f"constant timing means no progressive delay either."
        )

    def test_sso_no_progressive_delay(self):
        """BUG #14: Response times should increase after repeated fails — they don't."""
        for i in range(8):
            r, t = self._attempt("tester-1@test.internal", f"TIMING_{i}")
            self.timings.append(t)

        if len(self.timings) < 4:
            pytest.skip("Not enough timing samples")

        first_half_avg = statistics.mean(self.timings[:4])
        second_half_avg = statistics.mean(self.timings[4:])

        # Progressive delay should make later attempts at least 2× slower
        assert second_half_avg >= first_half_avg * 2.0, (
            "BUG #14 — No progressive delay between failed login attempts. "
            f"First 4 attempts avg: {first_half_avg*1000:.0f}ms, "
            f"Last 4 attempts avg: {second_half_avg*1000:.0f}ms. "
            "A secure system should add increasing delays after repeated failures."
        )

    def test_sso_no_captcha_after_fails(self):
        """BUG #14: No CAPTCHA challenge appears after repeated failures."""
        for i in range(8):
            r, _ = self._attempt("tester-1@test.internal", f"CAPTCHA_TEST_{i}")
            self.responses.append(r)

        has_captcha = any(
            "captcha" in r.text.lower() or
            "recaptcha" in r.text.lower() or
            "hcaptcha" in r.text.lower()
            for r in self.responses
        )
        assert has_captcha, (
            "BUG #14 — No CAPTCHA challenge served after 8 consecutive failed "
            "login attempts. Automated brute force is not blocked."
        )

    def test_sso_no_rate_limit_headers_on_failure(self):
        """BUG #15: Failed login response has no rate-limit headers."""
        r, _ = self._attempt("tester-1@test.internal", "WRONG_PASS")
        has_rl = has_rate_limit_headers(r)
        assert has_rl, (
            "BUG #15 — SSO failed-login response includes no rate-limit headers "
            "(X-RateLimit-*, Retry-After). "
            f"Response headers: {dict(r.headers)}"
        )

    def test_sso_username_enumeration_via_timing(self):
        """
        Timing attack: valid username + wrong password should be
        indistinguishable in response time from invalid username + wrong password.
        """
        valid_times = []
        invalid_times = []

        for i in range(5):
            # Valid username (exists in system), wrong password
            _, t_valid = self._attempt("tester-1@test.internal", f"WRONG_{i}")
            valid_times.append(t_valid)

            # Invalid username (does not exist)
            _, t_invalid = self._attempt(f"nonexistent_{i}@fake-domain.xyz", f"WRONG_{i}")
            invalid_times.append(t_invalid)

        avg_valid   = statistics.mean(valid_times)
        avg_invalid = statistics.mean(invalid_times)

        # More than 100ms difference in average → timing oracle → username enumeration
        diff_ms = abs(avg_valid - avg_invalid) * 1000
        assert diff_ms <= 100, (
            f"Potential username enumeration via timing: "
            f"valid username avg {avg_valid*1000:.0f}ms vs "
            f"invalid username avg {avg_invalid*1000:.0f}ms "
            f"(diff: {diff_ms:.0f}ms > 100ms threshold). "
            "Consistent response timing required for both paths."
        )

    def test_sso_same_error_message_for_valid_and_invalid_user(self):
        """
        Error message must be identical for valid user/wrong-pass vs
        completely invalid user, to prevent username enumeration.
        """
        r_valid,   _ = self._attempt("tester-1@test.internal", "WRONG_PASS_ENUM_1")
        r_invalid, _ = self._attempt("nobody@doesnotexist.xyz", "WRONG_PASS_ENUM_2")

        # Extract error text (strip HTML tags for comparison)
        def extract_error(html: str) -> str:
            cleaned = re.sub(r"<[^>]+>", " ", html)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            for phrase in ["invalid", "incorrect", "wrong", "not found",
                           "does not exist", "no account"]:
                if phrase in cleaned.lower():
                    start = cleaned.lower().find(phrase)
                    return cleaned[max(0, start-20):start+80].strip()
            return cleaned[:200]

        msg_valid   = extract_error(r_valid.text).lower()
        msg_invalid = extract_error(r_invalid.text).lower()

        # If one says "account not found" and other says "wrong password" → enumeration
        valid_specific   = any(p in msg_valid   for p in ["not found", "no account", "does not exist"])
        invalid_specific = any(p in msg_invalid for p in ["not found", "no account", "does not exist"])

        assert valid_specific == invalid_specific, (
            "BUG: Different error messages for valid vs invalid username — "
            "enables username enumeration. "
            f"Valid user msg: '{msg_valid[:80]}', "
            f"Invalid user msg: '{msg_invalid[:80]}'"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 2 — App Endpoint GET Rate Limiting
# ═══════════════════════════════════════════════════════════════════════════════

class TestAppEndpointGETRateLimit:
    """
    BUG #15: No rate limiting on app GET endpoints.
    30 rapid requests all return 200 with no throttling.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.sess = app_session()

    def _flood_get(self, path: str, count: int) -> list[requests.Response]:
        responses = []
        for _ in range(count):
            r = self.sess.get(f"{BASE}/{path}", timeout=10)
            responses.append(r)
        return responses

    def test_no_rate_limit_on_people_list(self):
        """BUG #15: 30 rapid GET /people — all 200, no 429."""
        resps = self._flood_get("people", 30)
        rate_limited = [r for r in resps if is_rate_limited(r)]
        assert len(rate_limited) > 0, (
            "BUG #15 — No rate limiting on GET /people. "
            f"30 rapid requests: all returned {resps[0].status_code}. "
            "No 429, no throttling, no rate-limit headers."
        )

    def test_no_rate_limit_on_dashboard(self):
        """BUG #15: 30 rapid GET /dashboard — all 200."""
        resps = self._flood_get("dashboard", 30)
        rate_limited = [r for r in resps if is_rate_limited(r)]
        assert len(rate_limited) > 0, (
            "BUG #15 — No rate limiting on GET /dashboard. "
            f"30 requests: all {resps[0].status_code}. "
        )

    def test_no_rate_limit_on_projects_list(self):
        """BUG #15: 30 rapid GET /projects — all 200."""
        resps = self._flood_get("projects", 30)
        rate_limited = [r for r in resps if is_rate_limited(r)]
        assert len(rate_limited) > 0, (
            "BUG #15 — No rate limiting on GET /projects. 30 requests, 0 throttled."
        )

    def test_no_rate_limit_on_admin_users(self):
        """BUG #15: 20 rapid GET /admin/users — admin endpoints not protected."""
        resps = self._flood_get("admin/users", 20)
        rate_limited = [r for r in resps if is_rate_limited(r)]
        assert len(rate_limited) > 0, (
            "BUG #15 — No rate limiting on GET /admin/users. "
            "Admin pages served without any request throttling."
        )

    def test_no_rate_limit_on_audit_log(self):
        """BUG #15: 20 rapid GET /admin/audit-log — sensitive endpoint unprotected."""
        resps = self._flood_get("admin/audit-log", 20)
        rate_limited = [r for r in resps if is_rate_limited(r)]
        assert len(rate_limited) > 0, (
            "BUG #15 — Audit log endpoint has no rate limiting. "
            "20 rapid requests served without throttling."
        )

    def test_no_rate_limit_on_invoicing(self):
        """BUG #15: 20 rapid GET /invoicing — financial data endpoint unthrottled."""
        resps = self._flood_get("invoicing", 20)
        rate_limited = [r for r in resps if is_rate_limited(r)]
        assert len(rate_limited) > 0, (
            "BUG #15 — No rate limiting on GET /invoicing. 20 requests, 0 throttled."
        )

    def test_no_rate_limit_on_reports(self):
        """BUG #15: 20 rapid GET /reports — report generation not throttled."""
        resps = self._flood_get("reports", 20)
        rate_limited = [r for r in resps if is_rate_limited(r)]
        assert len(rate_limited) > 0, (
            "BUG #15 — No rate limiting on GET /reports. Reports serve without throttling."
        )

    def test_no_rate_limit_on_search_flood(self):
        """BUG #15: 30 rapid search requests — search endpoint unprotected."""
        responses = []
        for i in range(30):
            r = self.sess.get(f"{BASE}/people?search=flood{i}", timeout=10)
            responses.append(r)
        rate_limited = [r for r in responses if is_rate_limited(r)]
        assert len(rate_limited) > 0, (
            "BUG #15 — Search endpoint has no rate limiting. "
            "30 rapid search requests (different query each time) all returned 200. "
            "Search-scraping and enumeration are unrestricted."
        )

    def test_all_responses_lack_rate_limit_headers(self):
        """BUG #16: None of the app responses include X-RateLimit-* headers."""
        endpoints = [
            "people", "projects", "customers", "dashboard",
            "time/timesheets", "invoicing", "reports", "admin/users",
        ]
        missing = []
        for ep in endpoints:
            r = self.sess.get(f"{BASE}/{ep}", timeout=10)
            if not has_rate_limit_headers(r):
                missing.append(ep)

        assert not missing, (
            f"BUG #16 — {len(missing)}/{len(endpoints)} endpoints return no "
            f"rate-limit headers (X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After): "
            f"{missing}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 3 — App Endpoint POST Rate Limiting
# ═══════════════════════════════════════════════════════════════════════════════

class TestAppEndpointPOSTRateLimit:
    """
    BUG #15: No rate limiting on write endpoints.
    20 rapid POSTs all succeed with no throttling.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.sess = app_session()

    def test_no_rate_limit_on_time_entry_creation(self):
        """BUG #15: 20 rapid time entry POSTs — all accepted without limit."""
        responses = []
        for i in range(20):
            csrf = get_csrf_from(self.sess, f"{BASE}/time/book")
            r = self.sess.post(
                f"{BASE}/time/store",
                data={
                    "_csrf": csrf,
                    "project_id": "1",
                    "date_worked": "2025-01-15",
                    "duration": "1",
                    "description": f"Rate-limit test entry {i}",
                },
                allow_redirects=False,
                timeout=10,
            )
            responses.append(r)

        rate_limited = [r for r in responses if is_rate_limited(r)]
        assert len(rate_limited) > 0, (
            "BUG #15 — No rate limiting on POST /time/store. "
            f"20 rapid time entries all accepted (codes: "
            f"{list(dict.fromkeys(r.status_code for r in responses))}). "
            "An attacker or runaway script can flood the timesheet with junk data."
        )

    def test_no_rate_limit_on_person_create(self):
        """BUG #15: 10 rapid person POSTs (with validation errors) — no throttling."""
        responses = []
        for i in range(10):
            csrf = get_csrf_from(self.sess, f"{BASE}/people/new")
            r = self.sess.post(
                f"{BASE}/people/new",
                data={"_csrf": csrf, "last_name": f"FloodTest{i}"},
                timeout=10,
            )
            responses.append(r)

        rate_limited = [r for r in responses if is_rate_limited(r)]
        assert len(rate_limited) > 0, (
            "BUG #15 — No rate limiting on POST /people/new. "
            "10 rapid form submissions (even with validation errors) not throttled."
        )

    def test_no_rate_limit_on_customer_create(self):
        """BUG #15: 10 rapid customer POSTs — not throttled."""
        responses = []
        for i in range(10):
            csrf = get_csrf_from(self.sess, f"{BASE}/customers/new")
            r = self.sess.post(
                f"{BASE}/customers/new",
                data={"_csrf": csrf, "currency": "EUR"},
                timeout=10,
            )
            responses.append(r)

        rate_limited = [r for r in responses if is_rate_limited(r)]
        assert len(rate_limited) > 0, (
            "BUG #15 — No rate limiting on POST /customers/new. "
            "10 rapid submissions not throttled."
        )

    def test_csrf_token_is_reusable(self):
        """
        Security property: CSRF tokens should be single-use.
        If the same token can be reused multiple times → weaker CSRF protection.
        This is informational — not necessarily a bug if session-bound.
        """
        csrf = get_csrf_from(self.sess, f"{BASE}/people/new")

        results = []
        for i in range(3):
            r = self.sess.post(
                f"{BASE}/people/new",
                data={
                    "_csrf": csrf,
                    "last_name": f"CsrfReuseTest{i}",
                },
                timeout=10,
            )
            # 200 = still on form (validation error or CSRF rejection)
            # 302 = success or CSRF rejection with redirect
            is_rejected = r.status_code == 403 or "csrf" in r.text.lower()
            results.append(is_rejected)

        reuses_accepted = results.count(False)
        if reuses_accepted >= 2:
            pytest.xfail(
                f"CSRF token reused {reuses_accepted}×/3 without rejection. "
                "Session-bound CSRF tokens (not per-request) may allow replay within session. "
                "Consider per-request single-use tokens for stronger protection."
            )

    def test_no_duplicate_submission_protection(self):
        """
        Submitting identical data twice should be detected (idempotency check).
        Sending same time entry twice should be rejected or deduplicated.
        """
        csrf1 = get_csrf_from(self.sess, f"{BASE}/time/book")
        payload = {
            "_csrf": csrf1,
            "project_id": "1",
            "date_worked": "2020-01-01",
            "duration": "7",
            "description": "DUPLICATE-SUBMISSION-TEST-v31",
        }
        r1 = self.sess.post(f"{BASE}/time/store", data=payload,
                            allow_redirects=False, timeout=10)

        csrf2 = get_csrf_from(self.sess, f"{BASE}/time/book")
        payload["_csrf"] = csrf2
        r2 = self.sess.post(f"{BASE}/time/store", data=payload,
                            allow_redirects=False, timeout=10)

        # Both succeed → no duplicate prevention
        both_accepted = r1.status_code in (200, 302) and r2.status_code in (200, 302)
        assert not both_accepted, (
            "No duplicate submission protection: identical time entry "
            f"(project=1, date=2020-01-01, duration=7h, desc=DUPLICATE-SUBMISSION-TEST-v31) "
            "accepted twice. The system should detect and reject duplicate entries."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 4 — Auth Callback Rate Limiting
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthCallbackRateLimit:
    """
    The /auth/callback endpoint handles SSO token exchange.
    Rapid unauthenticated hits should be throttled.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.sess = requests.Session()
        self.sess.headers["User-Agent"] = "StaffPlus-RateLimit-Tests/31"

    def test_auth_callback_not_rate_limited(self):
        """BUG #15: /auth/callback — 20 rapid unauthenticated hits, no throttling."""
        responses = []
        for _ in range(20):
            r = self.sess.get(f"{BASE}/auth/callback",
                              allow_redirects=False, timeout=10)
            responses.append(r)

        rate_limited = [r for r in responses if is_rate_limited(r)]
        statuses = [r.status_code for r in responses]
        assert len(rate_limited) > 0, (
            "BUG #15 — Auth callback endpoint not rate limited. "
            f"20 rapid unauthenticated requests: statuses={list(dict.fromkeys(statuses))}. "
            "The token-exchange endpoint should throttle unauthenticated probing."
        )

    def test_auth_login_redirect_not_rate_limited(self):
        """BUG #15: /auth/login redirect — 20 rapid hits, no throttling."""
        responses = []
        for _ in range(20):
            r = self.sess.get(f"{BASE}/auth/login",
                              allow_redirects=False, timeout=10)
            responses.append(r)

        rate_limited = [r for r in responses if is_rate_limited(r)]
        assert len(rate_limited) > 0, (
            "BUG #15 — /auth/login redirect not rate limited. "
            "20 rapid requests all processed without throttling."
        )

    def test_unauthenticated_flood_no_lockout(self):
        """BUG #15: 30 rapid unauthenticated requests to protected pages."""
        pages = [
            "dashboard", "people", "projects", "customers",
            "invoicing", "reports", "admin/users",
        ]
        responses = []
        for i in range(30):
            path = pages[i % len(pages)]
            r = self.sess.get(f"{BASE}/{path}",
                              allow_redirects=False, timeout=10)
            responses.append(r)

        rate_limited = [r for r in responses if is_rate_limited(r)]
        assert len(rate_limited) > 0, (
            "BUG #15 — 30 rapid unauthenticated requests to protected pages not throttled. "
            f"All received {responses[0].status_code} (redirect to login). "
            "Bot/scanner traffic is not blocked."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 5 — Data Spam / Enumeration Protection
# ═══════════════════════════════════════════════════════════════════════════════

class TestDataSpamProtection:
    """
    Test whether the app prevents automated data creation at scale.
    Rapid record creation should be detected and limited.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.sess = app_session()

    def test_rapid_task_creation_not_limited(self):
        """BUG #15: 15 rapid task creations — no limit on task spam."""
        responses = []
        for i in range(15):
            csrf = get_csrf_from(self.sess, f"{BASE}/tasks")
            r = self.sess.post(
                f"{BASE}/tasks/board/new",
                data={"_csrf": csrf, "name": f"Spam Task {i}", "type": "todo"},
                allow_redirects=False,
                timeout=10,
            )
            responses.append(r)

        rate_limited = [r for r in responses if is_rate_limited(r)]
        assert len(rate_limited) > 0, (
            "BUG #15 — No rate limiting on task creation. "
            f"15 tasks created in rapid succession without throttling "
            f"(codes: {list(dict.fromkeys(r.status_code for r in responses))})."
        )

    def test_person_id_enumeration_not_rate_limited(self):
        """
        BUG #15: Enumerating /people/1 through /people/50 — no throttling.
        An attacker can scrape all personnel records sequentially.
        """
        responses = []
        found = []
        for person_id in range(1, 31):
            r = self.sess.get(f"{BASE}/people/{person_id}", timeout=10)
            responses.append(r)
            if r.status_code == 200:
                found.append(person_id)

        rate_limited = [r for r in responses if is_rate_limited(r)]
        assert len(rate_limited) > 0 or len(found) < 5, (
            "BUG #15 — Sequential enumeration of /people/:id not rate limited. "
            f"Found {len(found)} accessible person records by sequential ID probing "
            f"(IDs: {found[:10]}{'...' if len(found)>10 else ''}). "
            "Rate limiting or randomised IDs should prevent bulk data scraping."
        )

    def test_invoice_id_enumeration_not_rate_limited(self):
        """BUG #15: Enumerating /invoicing/:id — financial records accessible by sequential ID."""
        responses = []
        found = []
        for inv_id in range(1, 21):
            r = self.sess.get(f"{BASE}/invoicing/{inv_id}", timeout=10)
            responses.append(r)
            if r.status_code == 200 and "invoice" in r.text.lower():
                found.append(inv_id)

        rate_limited = [r for r in responses if is_rate_limited(r)]
        assert len(rate_limited) > 0 or len(found) < 3, (
            "BUG #15 — Invoice records enumerable by sequential ID without rate limiting. "
            f"Found {len(found)} invoice records via /invoicing/1..20 enumeration."
        )

    def test_customer_id_enumeration_not_rate_limited(self):
        """BUG #15: Enumerating /customers/:id — all customer records accessible."""
        responses = []
        found = []
        for cust_id in range(1, 21):
            r = self.sess.get(f"{BASE}/customers/{cust_id}", timeout=10)
            responses.append(r)
            if r.status_code == 200 and "customer" in r.text.lower():
                found.append(cust_id)

        rate_limited = [r for r in responses if is_rate_limited(r)]
        assert len(rate_limited) > 0 or len(found) < 3, (
            "BUG #15 — Customer records enumerable by sequential ID without rate limiting."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 6 — Response Consistency & Timing
# ═══════════════════════════════════════════════════════════════════════════════

class TestResponseConsistency:
    """
    Verify response consistency under load — no server degradation,
    no information leakage under stress conditions.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.sess = app_session()

    def test_response_time_stable_under_load(self):
        """
        50 rapid requests to /people — response time should stay under 5s each.
        Not a rate-limit test; checks for server degradation.
        """
        timings = []
        for _ in range(50):
            t0 = time.perf_counter()
            r = self.sess.get(f"{BASE}/people", timeout=15)
            elapsed = time.perf_counter() - t0
            timings.append(elapsed)
            assert r.status_code == 200, f"Unexpected status {r.status_code} under load"

        avg_ms = statistics.mean(timings) * 1000
        max_ms = max(timings) * 1000
        p95_ms = sorted(timings)[int(len(timings) * 0.95)] * 1000

        assert max_ms < 5000, (
            f"Response time degraded under 50 concurrent requests: "
            f"max={max_ms:.0f}ms, avg={avg_ms:.0f}ms, p95={p95_ms:.0f}ms"
        )

    def test_no_server_errors_under_rapid_posts(self):
        """
        20 rapid POSTs with invalid data — server must not 500 under load.
        """
        errors = []
        for i in range(20):
            csrf = get_csrf_from(self.sess, f"{BASE}/people/new")
            r = self.sess.post(
                f"{BASE}/people/new",
                data={"_csrf": csrf, "first_name": f"Load{i}"},
                timeout=10,
            )
            if r.status_code == 500 or "Whoops" in r.text:
                errors.append(i)

        assert not errors, (
            f"Server returned 500 on {len(errors)} out of 20 rapid POST requests: "
            f"at attempt numbers {errors}. Server is not stable under POST load."
        )

    def test_concurrent_session_requests_no_cross_contamination(self):
        """
        Two sessions making requests simultaneously should get consistent responses.
        Checks for session isolation under concurrent load.
        """
        sess1 = app_session()
        sess2 = app_session()

        # Use list page — guaranteed to have content and return 200
        r1 = sess1.get(f"{BASE}/people", timeout=10)
        r2 = sess2.get(f"{BASE}/people", timeout=10)

        assert r1.status_code == r2.status_code == 200, (
            f"Concurrent sessions got different status codes: "
            f"sess1={r1.status_code}, sess2={r2.status_code}"
        )
        # Both responses should have similar size (same page rendered twice)
        size_ratio = len(r1.text) / max(len(r2.text), 1)
        assert 0.8 <= size_ratio <= 1.2, (
            f"Concurrent session responses differ significantly in size: "
            f"sess1={len(r1.text)}B, sess2={len(r2.text)}B — possible race condition"
        )

    def test_search_responses_consistent_under_rapid_queries(self):
        """
        30 identical search queries should return identical result counts.
        Inconsistent results under load indicate race conditions or caching bugs.
        """
        results = []
        for _ in range(10):
            r = self.sess.get(f"{BASE}/people?search=test", timeout=10)
            assert r.status_code == 200
            # Count result rows as a proxy for result count
            count = r.text.count('href="/test/timetracker/public/people/')
            results.append(count)

        if results:
            unique_counts = set(results)
            assert len(unique_counts) <= 2, (
                f"Inconsistent search results under rapid identical queries: "
                f"got {len(unique_counts)} different result counts: {unique_counts}. "
                "Possible race condition or cache inconsistency."
            )

    def test_no_info_leak_in_rate_limit_error(self):
        """
        If a 429 were ever returned, it must not leak stack traces or internals.
        Pre-check: verify app 404 pages don't leak info either.
        """
        r = self.sess.get(f"{BASE}/nonexistent-path-xyz", timeout=10)
        body = r.text

        assert "Stack trace" not in body, "Stack trace in 404 response"
        assert "#0 " not in body, "PHP call stack in 404 response"
        assert "/usr/www/" not in body, "Server path in 404 response"
        assert "vendor/" not in body, "Vendor path in 404 response"

    def test_response_body_not_empty_under_load(self):
        """
        Server should not return empty bodies under rapid load.
        Empty 200 body = likely server-side error or partial response.
        """
        empty_responses = []
        for i in range(20):
            r = self.sess.get(f"{BASE}/people", timeout=10)
            if len(r.text) < 100:
                empty_responses.append(i)

        assert not empty_responses, (
            f"Server returned near-empty body on {len(empty_responses)}/20 "
            f"rapid requests (at attempts: {empty_responses}). "
            "Possible connection exhaustion or partial response under load."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS 7 — Playwright — Browser-based Rate Limit Checks
# ═══════════════════════════════════════════════════════════════════════════════

class TestNavigationRateLimitChecks:
    """
    Requests-based checks confirming rapid navigation doesn't produce
    rate-limit responses on any page. Uses authenticated session cookie.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.sess = app_session()

    def test_no_429_on_rapid_page_navigation(self):
        """Rapid GET across 8 pages — none should return 429 or 'too many requests'."""
        paths = [
            "dashboard", "people", "projects", "customers",
            "invoicing", "time/timesheets", "reports", "tasks",
        ]
        for path in paths:
            r = self.sess.get(f"{BASE}/{path}", timeout=10)
            assert r.status_code != 429, f"429 received on GET /{path}"
            assert "too many requests" not in r.text.lower(), \
                f"Rate-limit page content on /{path}"

    def test_no_429_on_rapid_search_queries(self):
        """20 search queries with different terms — no rate limit page served."""
        terms = ["a", "b", "test", "admin", "project", "invoice",
                 "e", "f", "g", "h", "i", "j", "k", "l",
                 "contract", "customer", "time", "report", "z", ""]
        for term in terms:
            r = self.sess.get(f"{BASE}/people?search={term}", timeout=10)
            assert r.status_code != 429, f"429 on search '{term}'"
            assert "too many" not in r.text.lower(), \
                f"Rate-limit page on search '{term}'"

    def test_no_429_on_rapid_form_submissions(self):
        """10 rapid form submits (empty body → validation error) — no 429."""
        for i in range(10):
            csrf = get_csrf_from(self.sess, f"{BASE}/people/new")
            r = self.sess.post(
                f"{BASE}/people/new",
                data={"_csrf": csrf},
                timeout=10,
            )
            assert r.status_code != 429, f"429 on form submit {i}"
            assert "too many" not in r.text.lower(), \
                f"Rate-limit page on form submit {i}"

    def test_no_429_on_rapid_admin_page_access(self):
        """6 admin pages loaded in rapid succession — no rate limit."""
        admin_paths = [
            "admin/users", "admin/roles", "admin/audit-log",
            "admin/settings", "admin/delegations", "admin/approval-rules",
        ]
        for path in admin_paths:
            r = self.sess.get(f"{BASE}/{path}", timeout=10)
            assert r.status_code != 429, f"429 on /{path}"
            assert "too many requests" not in r.text.lower(), \
                f"Rate-limit page on /{path}"
