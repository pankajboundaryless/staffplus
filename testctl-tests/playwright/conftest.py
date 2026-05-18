"""
Shared fixtures and helpers for all Playwright tests.

Auth strategy:
  Run save_session.py once to log in manually via Microsoft SSO.
  Session is saved to .auth/session.json and reused for all subsequent tests.
"""

import os
import pathlib
import pytest
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

load_dotenv(pathlib.Path(__file__).parent / ".env")

BASE_URL     = os.getenv("TEST_BASE_URL", "https://robomon.boundaryless.com/test/timetracker/public")
AUTH_URL     = os.getenv("AUTH_URL", "https://auth.boundaryless.com/public/login_form.php?app=timetracker-ng-test")
HEADED       = os.getenv("HEADED", "0") == "1"
SESSION_FILE = pathlib.Path(__file__).parent / ".auth" / "session.json"


def url(path: str) -> str:
    return f"{BASE_URL.rstrip('/')}/{path.lstrip('/')}"


def has_error(page) -> bool:
    """True if page shows a server error (500 / Whoops / Stack trace)."""
    content = page.content()
    return (
        "Stack trace" in content
        or "Whoops" in content
        or page.title().startswith("500")
        or "<title>500" in content
    )


def is_404(page) -> bool:
    content = page.content()
    return "404" in page.title() or "404 not found" in content.lower()


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
    """Per-test authenticated page."""
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
