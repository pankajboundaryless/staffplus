"""
create_ci_session.py — Generate a fresh auth session using JWT_SECRET.

WHY THIS EXISTS
───────────────
The Microsoft SSO session saved by save_session.py expires in ~1 hour
(the bljwt cookie has exp = iat + 3600). That is fine for local dev but
breaks CI/CD pipelines that run hours or days after the session was saved.

This script takes a different approach that works forever in CI:
  1.  Build a signed HS256 JWT (same format the app issues after SSO login).
  2.  POST it to /auth/callback — the app verifies the signature, syncs the
      user into the DB if needed, and creates a fresh PHP session cookie.
  3.  Save the resulting cookies to .auth/session.json — the same file that
      conftest.py loads for every test.

REQUIREMENTS
────────────
  pip install pyjwt requests playwright

ENVIRONMENT VARIABLES (or .env file)
──────────────────────────────────────
  JWT_SECRET        The HS256 signing secret from config/auth.php
                    (same value as in testctl.yaml / .env.example)
  AUTH_APP_SLUG     Audience claim, e.g. "timetracker-ng"   (default: timetracker-ng)
  TEST_BASE_URL     App base URL  (default: https://robomon.boundaryless.com/test/timetracker/public)

USAGE
─────
  # One-time / manual refresh
  JWT_SECRET=your_secret python create_ci_session.py

  # With .env file
  python create_ci_session.py

  # In GitHub Actions (JWT_SECRET stored as a GitHub Secret)
  JWT_SECRET=${{ secrets.JWT_SECRET }} python create_ci_session.py

WHICH USER IS CREATED?
──────────────────────
  By default creates the "admin" test user (auth_uid=90001).
  Pass --role employee|project_manager|line_manager to get a different role.

  python create_ci_session.py --role employee
"""

import argparse
import pathlib
import sys
import time
import json
import os

import jwt          # pip install pyjwt
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# ── load .env if present ──────────────────────────────────────────────────────
load_dotenv(pathlib.Path(__file__).parent / ".env")

BASE_URL      = os.getenv("TEST_BASE_URL",
                           "https://robomon.boundaryless.com/test/timetracker/public")
JWT_SECRET    = os.getenv("JWT_SECRET", "")
AUTH_APP_SLUG = os.getenv("AUTH_APP_SLUG", "timetracker-ng")
SESSION_FILE  = pathlib.Path(__file__).parent / ".auth" / "session.json"

# Test users (mirrors testctl.yaml)
TEST_USERS = {
    "admin": {
        "auth_uid": 90001,
        "email":    "testadmin@example.test",
        "name":     "Test Admin",
        "role":     "admin",
        "roles":    ["admin"],
    },
    "project_manager": {
        "auth_uid": 90002,
        "email":    "testpm@example.test",
        "name":     "Test PM",
        "role":     "project_manager",
        "roles":    ["project_manager"],
    },
    "employee": {
        "auth_uid": 90003,
        "email":    "testemployee@example.test",
        "name":     "Test Employee",
        "role":     "employee",
        "roles":    ["employee"],
    },
    "line_manager": {
        "auth_uid": 90004,
        "email":    "testmanager@example.test",
        "name":     "Test Manager",
        "role":     "line_manager",
        "roles":    ["line_manager"],
    },
}


# ── helpers ───────────────────────────────────────────────────────────────────

def build_jwt(user: dict, secret: str, aud: str, ttl_seconds: int = 300) -> str:
    """
    Create a signed HS256 JWT matching the format expected by /auth/callback.

    Payload fields:
      sub       — unique user identifier (auth_uid as string)
      email     — user email
      name      — display name
      role      — primary role string
      roles     — list of roles
      aud       — audience (AUTH_APP_SLUG)
      iat       — issued-at timestamp
      exp       — expiry (iat + ttl_seconds)  — 5 min is plenty for a test login
    """
    now = int(time.time())
    payload = {
        "sub":   str(user["auth_uid"]),
        "email": user["email"],
        "name":  user["name"],
        "role":  user["role"],
        "roles": user["roles"],
        "aud":   aud,
        "iat":   now,
        "exp":   now + ttl_seconds,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def create_session_via_callback(token: str) -> dict:
    """
    POST the JWT to /auth/callback.
    The app verifies the JWT, syncs the user, and sets PHP session cookies.
    Returns a Playwright-compatible storage_state dict.
    """
    callback_url = f"{BASE_URL.rstrip('/')}/auth/callback"

    session = requests.Session()
    resp = session.post(
        callback_url,
        data={"token": token},
        allow_redirects=True,
        timeout=15,
    )

    if resp.status_code not in (200, 302):
        raise RuntimeError(
            f"Auth callback returned HTTP {resp.status_code}.\n"
            f"URL: {callback_url}\n"
            f"Response: {resp.text[:300]}"
        )

    # Check we landed on the dashboard (not back at login)
    if "login" in resp.url.lower() or "login" in resp.text.lower()[:500]:
        raise RuntimeError(
            "Auth callback redirected back to login — JWT was rejected.\n"
            "Check that JWT_SECRET and AUTH_APP_SLUG match the app config.\n"
            f"Final URL: {resp.url}"
        )

    # Convert requests cookies → Playwright storage_state format
    cookies = []
    for c in session.cookies:
        cookies.append({
            "name":     c.name,
            "value":    c.value,
            "domain":   c.domain or "",
            "path":     c.path or "/",
            "expires":  c.expires or -1,
            "httpOnly": False,
            "secure":   c.secure,
            "sameSite": "Lax",
        })

    return {"cookies": cookies, "origins": []}


def verify_session(storage_state: dict) -> bool:
    """
    Open a headless Playwright browser with the saved session and confirm
    it reaches the dashboard (not redirected to login).
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=storage_state)
        page = ctx.new_page()
        page.goto(f"{BASE_URL.rstrip('/')}/dashboard")
        page.wait_for_load_state("networkidle")
        ok = "dashboard" in page.url and "login" not in page.url
        browser.close()
    return ok


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate a CI auth session via JWT callback (no browser login needed)."
    )
    parser.add_argument(
        "--role",
        choices=list(TEST_USERS.keys()),
        default="admin",
        help="Which test user to create the session for (default: admin)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        default=True,
        help="Open headless browser to verify session after creation (default: True)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  StaffPlus — CI Session Generator")
    print("=" * 60)

    # ── Validate JWT_SECRET ───────────────────────────────────────────────────
    if not JWT_SECRET:
        print("\n❌  JWT_SECRET environment variable is not set.")
        print(
            "\nOptions:\n"
            "  1. Add JWT_SECRET=<your_secret> to testctl-tests/playwright/.env\n"
            "  2. Export it:  export JWT_SECRET=<your_secret>\n"
            "  3. In CI: add JWT_SECRET as a GitHub Secret\n"
            "\nIf you don't have JWT_SECRET, use save_session.py instead\n"
            "(requires a browser and interactive Microsoft login).\n"
        )
        sys.exit(1)

    user = TEST_USERS[args.role]
    print(f"\n  User:   {user['name']}  ({user['email']})")
    print(f"  Role:   {user['role']}")
    print(f"  App:    {BASE_URL}")

    # ── Step 1: Build JWT ─────────────────────────────────────────────────────
    print("\n  [1/3] Building JWT... ", end="", flush=True)
    token = build_jwt(user, JWT_SECRET, AUTH_APP_SLUG)
    print("done")

    # ── Step 2: Exchange JWT for session via /auth/callback ───────────────────
    print("  [2/3] Posting to /auth/callback... ", end="", flush=True)
    try:
        storage_state = create_session_via_callback(token)
    except RuntimeError as e:
        print(f"\n\n❌  {e}\n")
        sys.exit(1)
    print(f"done  ({len(storage_state['cookies'])} cookies received)")

    # ── Step 3: Save session file ─────────────────────────────────────────────
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(storage_state, indent=2))
    print(f"  [3/3] Session saved → {SESSION_FILE}")

    # ── Step 4: Optional Playwright verification ──────────────────────────────
    if args.verify:
        print("\n  Verifying session in headless browser... ", end="", flush=True)
        ok = verify_session(storage_state)
        if ok:
            print("✓ reached dashboard")
        else:
            print("⚠️  could not verify (may still work — check manually)")

    print(f"\n✓ Session ready. Run:  pytest")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
