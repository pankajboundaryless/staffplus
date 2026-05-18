# StaffPlus Playwright Test Suite

Browser-based end-to-end tests for the Boundaryless Management Platform.
Covers login, all modules, security, and UI/UX quality checks.

## Quick Start

```bash
# 1. Install dependencies
cd testctl-tests/playwright
pip install -r requirements.txt
playwright install chromium

# 2. First run — log in manually (saves session for future runs)
HEADED=1 pytest test_01_login.py::TestAuthenticatedSession::test_dashboard_accessible_after_login -s

# 3. Run all tests (headless, reuses saved session)
pytest

# 4. Open the HTML report
open reports/report.html
```

## Auth Strategy

Since the app uses Microsoft SSO, the first run must be headed so you can
complete the login manually. The session is saved to `.auth/session.json`
and reused for all subsequent headless runs.

```bash
# Step 1: Run headed to complete Microsoft login
HEADED=1 pytest test_01_login.py -k "test_dashboard_accessible" -s
# → A browser window opens. Log in with Microsoft. Close when done.

# Step 2: Run all tests headlessly
pytest
```

## Test Files

| File | What It Tests |
|---|---|
| `test_01_login.py` | Login page, bad credentials, session, logout |
| `test_02_dashboard.py` | Dashboard layout, nav menu, all module links |
| `test_03_people.py` | People list, create, search, XSS in name |
| `test_04_projects.py` | Projects list, create, detail page |
| `test_05_time.py` | Time booking, form validation, timer, approval |
| `test_06_invoicing.py` | Invoice list, create draft, rate cards |
| `test_07_security.py` | XSS, SQL injection, CSRF, auth bypass, IDOR, headers |
| `test_08_ui_ux.py` | All pages 500-free, broken links, long strings, responsive |
| `test_09_reports_admin.py` | Reports, settings, customers, absence, tasks |

## Run Specific Modules

```bash
# Only security tests
pytest test_07_security.py -v

# Only dashboard tests
pytest test_02_dashboard.py -v

# All tests except slow ones
pytest -m "not slow"

# Run headed (visible browser) for debugging
HEADED=1 pytest test_03_people.py -v -s
```

## Output

Every run produces:
- `reports/report.html` — full HTML report, open in browser
- Console output with pass/fail per test

## Adding New Tests

1. Create `test_10_mymodule.py`
2. Import `from conftest import url`
3. Use the `page` fixture for authenticated tests
4. Use the `fresh_page` fixture for unauthenticated/security tests
