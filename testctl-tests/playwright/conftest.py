"""
Shared fixtures and helpers for all Playwright tests.

Auth strategy:
  Run save_session.py once to log in manually via Microsoft SSO.
  Session is saved to .auth/session.json and reused for all subsequent tests.

Role-switching strategy:
  The app has an Assume Role feature (/assume-role POST endpoint).
  Role fixtures (employee_page, manager_page, deputy_page) use the admin
  session, then call /assume-role to switch to the target user before yielding.
  The role is released with /release-role after each test.

  Configure user IDs to assume in .env:
    EMPLOYEE_USER_ID=5
    MANAGER_USER_ID=3
    DEPUTY_USER_ID=8
  Or discover them via /debug/users (admin only).
"""

import os
import pathlib
import pytest
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

load_dotenv(pathlib.Path(__file__).parent / ".env")

BASE_URL          = os.getenv("TEST_BASE_URL", "https://robomon.boundaryless.com/test/timetracker/public")
AUTH_URL          = os.getenv("AUTH_URL", "https://auth.boundaryless.com/public/login_form.php?app=timetracker-ng-test")
HEADED            = os.getenv("HEADED", "0") == "1"
SESSION_FILE      = pathlib.Path(__file__).parent / ".auth" / "session.json"

# Role user IDs — set these in .env after discovering via /debug/users
EMPLOYEE_USER_ID  = os.getenv("EMPLOYEE_USER_ID", "")
MANAGER_USER_ID   = os.getenv("MANAGER_USER_ID", "")
DEPUTY_USER_ID    = os.getenv("DEPUTY_USER_ID", "")


def url(path: str) -> str:
    return f"{BASE_URL.rstrip('/')}/{path.lstrip('/')}"


def has_error(page) -> bool:
    """True if page shows a server error (500 / Whoops / Stack trace).

    Returns False when page.content() fails (page still navigating) —
    a navigation-in-progress page cannot be a rendered error page.
    """
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
        content = page.content()
    except Exception:
        return False
    return (
        "Stack trace" in content
        or "Whoops" in content
        or page.title().startswith("500")
        or "<title>500" in content
    )


def is_404(page) -> bool:
    content = page.content()
    return "404" in page.title() or "404 not found" in content.lower()


def get_csrf_token(page: Page, path: str = "/dashboard") -> str:
    """Fetch CSRF token from a page's hidden input field."""
    page.goto(url(path))
    page.wait_for_load_state("networkidle")
    el = page.locator("input[name='_csrf'], input[name='_token']").first
    return el.input_value() if el.count() > 0 else ""


def impersonate(page: Page, user_id: str) -> bool:
    """
    Switch the current browser session to act as `user_id`.
    Uses the app's /debug/impersonate POST endpoint (admin-only debug tool).

    IMPORTANT: Each role fixture must use its OWN isolated browser context
    (copied from session.json) so impersonation doesn't contaminate the
    shared admin context. See role fixtures below.

    Returns True if impersonation was successful.
    """
    # Get CSRF token from the debug users page
    page.goto(url("/debug/users"))
    page.wait_for_load_state("networkidle")
    if has_error(page) or "login" in page.url:
        return False

    # Find the impersonate form for this specific user_id
    form = page.locator(f"form[action*='impersonate']").filter(
        has=page.locator(f"input[name='user_id'][value='{user_id}']")
    ).first

    if form.count() == 0:
        return False

    # Click the submit button in that form
    submit = form.locator("button[type='submit'], input[type='submit']").first
    if submit.count() == 0:
        return False

    try:
        with page.expect_navigation(wait_until="networkidle", timeout=15000):
            submit.click()
    except Exception:
        pass

    return not has_error(page) and "login" not in page.url


# Legacy alias kept for any existing tests
assume_role = impersonate


def release_role(page: Page) -> None:
    """
    No-op — role contexts are isolated per-fixture using separate browser
    contexts. Closing the context releases the impersonation automatically.
    This function is kept for backward compatibility.
    """
    pass


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def browser_instance():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not HEADED, slow_mo=80)
        yield browser
        browser.close()


@pytest.fixture(scope="session")
def auth_context(browser_instance):
    """Session-scoped authenticated browser context (reuses saved session)."""
    assert SESSION_FILE.exists(), (
        f"\n\nNo session found at {SESSION_FILE}\n"
        "Run:  python save_session.py\n"
        "Then log in with Microsoft in the browser window that opens.\n"
    )
    ctx = browser_instance.new_context(storage_state=str(SESSION_FILE))

    # Quick sanity check — must reach dashboard
    page = ctx.new_page()
    page.goto(url("/dashboard"))
    page.wait_for_load_state("networkidle")
    assert "dashboard" in page.url, (
        "Saved session is expired.\nRun  python save_session.py  to refresh it."
    )
    page.close()
    yield ctx
    ctx.close()


@pytest.fixture
def page(auth_context) -> Page:
    """Per-test page — authenticated as the ADMIN user."""
    p = auth_context.new_page()
    p.set_default_timeout(20_000)
    yield p
    p.close()


@pytest.fixture
def fresh_page(browser_instance) -> Page:
    """Unauthenticated page — for login/security tests."""
    ctx = browser_instance.new_context()
    p = ctx.new_page()
    p.set_default_timeout(20_000)
    yield p
    p.close()
    ctx.close()


def _load_role_context(browser_instance, session_file: pathlib.Path, role_name: str):
    """
    Load a saved session file for a specific user role and return (ctx, page).
    Returns (None, None) if the session file doesn't exist.

    HOW TO SAVE ROLE SESSIONS:
      python save_session.py --output .auth/session_employee.json
      Log in as tester-4@test.internal (use the credentials on the login page
      or ask your admin for the test account passwords)
      Repeat for each role.
    """
    if not session_file.exists():
        return None, None
    ctx = browser_instance.new_context(storage_state=str(session_file))
    p = ctx.new_page()
    p.set_default_timeout(25_000)
    # Quick sanity check
    p.goto(url("/dashboard"))
    p.wait_for_load_state("networkidle")
    if "login" in p.url or has_error(p):
        p.close()
        ctx.close()
        return None, None
    return ctx, p


# Role session file paths
SESSION_EMPLOYEE = pathlib.Path(__file__).parent / ".auth" / "session_employee.json"
SESSION_MANAGER  = pathlib.Path(__file__).parent / ".auth" / "session_manager.json"
SESSION_DEPUTY   = pathlib.Path(__file__).parent / ".auth" / "session_deputy.json"


@pytest.fixture
def employee_page(browser_instance) -> Page:
    """
    Per-test page logged in as an EMPLOYEE user.

    Requires a saved session at .auth/session_employee.json
    Run:  python save_session.py --output .auth/session_employee.json
    Then log in as tester-4@test.internal (or any employee-role user).

    Skips tests if session file is absent.
    """
    ctx, p = _load_role_context(browser_instance, SESSION_EMPLOYEE, "employee")
    if p is None:
        pytest.skip(
            "No employee session found.\n"
            "Run: python save_session.py --output .auth/session_employee.json\n"
            "Then log in as an employee-role user (e.g. tester-4@test.internal)"
        )
    yield p
    p.close()
    ctx.close()


@pytest.fixture
def manager_page(browser_instance) -> Page:
    """
    Per-test page logged in as a MANAGER user.

    Requires a saved session at .auth/session_manager.json
    Run:  python save_session.py --output .auth/session_manager.json
    Then log in as an admin/manager-role user (e.g. tester-1@test.internal).
    """
    ctx, p = _load_role_context(browser_instance, SESSION_MANAGER, "manager")
    if p is None:
        pytest.skip(
            "No manager session found.\n"
            "Run: python save_session.py --output .auth/session_manager.json\n"
            "Then log in as a manager-role user (e.g. tester-1@test.internal)"
        )
    yield p
    p.close()
    ctx.close()


@pytest.fixture
def deputy_page(browser_instance) -> Page:
    """
    Per-test page logged in as a DEPUTY user.

    Requires a saved session at .auth/session_deputy.json
    First set up a delegation at /settings/deputy/new,
    then: python save_session.py --output .auth/session_deputy.json
    Log in as the deputy user.
    """
    ctx, p = _load_role_context(browser_instance, SESSION_DEPUTY, "deputy")
    if p is None:
        pytest.skip(
            "No deputy session found.\n"
            "Set up delegation at /settings/deputy/new first,\n"
            "then: python save_session.py --output .auth/session_deputy.json"
        )
    yield p
    p.close()
    ctx.close()
