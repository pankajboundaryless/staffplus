"""
Save session after manual SSO login.

Usage:
  python save_session.py                                    # saves admin session
  python save_session.py --output .auth/session_employee.json  # saves employee session
  python save_session.py --output .auth/session_manager.json   # saves manager session
  python save_session.py --output .auth/session_deputy.json    # saves deputy session

Sessions available in the test environment (/debug/users):
  tester-1@test.internal   role: admin
  tester-4@test.internal   role: employee
  tester-5@test.internal   role: employee
  (ask your admin for the test account passwords)
"""

import json
import pathlib
import argparse
from playwright.sync_api import sync_playwright

DASHBOARD    = "https://robomon.boundaryless.com/test/timetracker/public/dashboard"
DEFAULT_FILE = pathlib.Path(__file__).parent / ".auth" / "session.json"

parser = argparse.ArgumentParser(description="Save Playwright session after SSO login.")
parser.add_argument(
    "--output", "-o",
    type=pathlib.Path,
    default=DEFAULT_FILE,
    help="Path to save the session JSON (default: .auth/session.json)"
)
args = parser.parse_args()

SESSION_FILE = args.output
SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)

print(f"\nSaving session to: {SESSION_FILE}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx     = browser.new_context()
    page    = ctx.new_page()

    try:
        page.goto(DASHBOARD, timeout=20_000, wait_until="commit")
    except Exception:
        pass

    print("\n" + "="*60)
    if SESSION_FILE == DEFAULT_FILE:
        print("  Log in with your ADMIN account (Microsoft SSO).")
    else:
        role = SESSION_FILE.stem.replace("session_", "")
        print(f"  Log in as the {role.upper()} user.")
        print(f"  Available test accounts: tester-1, tester-4, tester-5, etc.")
        print(f"  Use @test.internal email addresses.")
    print("  When you reach the DASHBOARD, press ENTER here to save the session.")
    print("="*60 + "\n")

    input("Press ENTER after you're logged in and on the dashboard > ")

    current_url = page.url
    print(f"\nCurrent URL: {current_url}")

    if "dashboard" not in current_url.lower():
        print(f"⚠️  Warning: URL doesn't look like dashboard. Are you sure you're logged in?")
        confirm = input("Save anyway? (y/N) > ")
        if confirm.lower() != "y":
            print("Aborted.")
            browser.close()
            exit(1)

    # Save full storage state (cookies + localStorage) — required for auth
    ctx.storage_state(path=str(SESSION_FILE))
    saved = json.loads(SESSION_FILE.read_text())
    cookies = saved.get("cookies", [])
    print(f"✓ Session saved to {SESSION_FILE}")
    print(f"  {len(cookies)} cookies + localStorage")
    browser.close()

print("✓ Done. You can now run tests with this session.")
