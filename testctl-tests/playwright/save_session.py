"""
Run this once to log in manually and save your session.
After this, all pytest runs will reuse the saved session (no login needed).

Usage:
    python save_session.py
"""

import pathlib
from playwright.sync_api import sync_playwright

AUTH_URL     = "https://auth.boundaryless.com/public/login_form.php?app=timetracker-ng-test"
DASHBOARD    = "https://robomon.boundaryless.com/test/timetracker/public/dashboard"
SESSION_FILE = pathlib.Path(__file__).parent / ".auth" / "session.json"

SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)

print("\n" + "="*60)
print("  StaffPlus — Session Login")
print("="*60)
print("\nA browser window will open.")
print("Log in with your Microsoft account.")
print("The window will close automatically once you reach the dashboard.")
print("\nWaiting...\n")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=200)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(AUTH_URL)

    # Wait up to 3 minutes for dashboard
    page.wait_for_url(f"{DASHBOARD}**", timeout=180_000)

    print("✓ Logged in! Saving session...")
    ctx.storage_state(path=str(SESSION_FILE))
    browser.close()

print(f"✓ Session saved to: {SESSION_FILE}")
print("\nNow run:  pytest")
print("="*60 + "\n")
