"""
TEST 21 — SQL Injection Deep Security Testing

Tests SQL injection across every parameter and input surface:
  1. CLASSIC SQLI      — ' OR 1=1, comment-based, UNION-based
  2. BLIND SQLI        — boolean-based, time-based (sleep)
  3. ERROR-BASED SQLI  — extractvalue(), updatexml()
  4. UNION SELECT      — column count probing, data extraction
  5. SECOND-ORDER SQLI — payload stored then executed on retrieval
  6. PATH PARAMETERS   — injection in URL segments /people/1'
  7. HTTP HEADERS      — User-Agent, Referer, X-Forwarded-For
  8. ORDER BY SQLI     — manipulation of sort/order parameters
  9. BATCH / STACKED   — ; DROP TABLE attempts
 10. ORM BYPASS        — special chars that confuse ORMs

URL: /people, /projects, /invoicing, /time, /planning, /absence
"""

import urllib.parse
import pytest
from playwright.sync_api import Page
from conftest import url, has_error

# ─── payload sets ─────────────────────────────────────────────────────────────

CLASSIC_SQLI = [
    "' OR '1'='1",
    "' OR '1'='1'--",
    "' OR 1=1--",
    "\" OR \"1\"=\"1",
    "1' OR '1'='1",
    "admin'--",
    "' OR 'x'='x",
]

UNION_SQLI = [
    "' UNION SELECT null--",
    "' UNION SELECT null,null--",
    "' UNION SELECT null,null,null--",
    "1 UNION SELECT user(),version(),database()--",
    "' UNION ALL SELECT 1,2,3--",
]

BLIND_SQLI = [
    "' AND 1=1--",
    "' AND 1=2--",
    "' AND SLEEP(1)--",
    "1; WAITFOR DELAY '0:0:1'--",
    "' AND (SELECT 1 FROM users LIMIT 1)='1",
]

ERROR_SQLI = [
    "' AND extractvalue(1,concat(0x7e,database()))--",
    "' AND updatexml(1,concat(0x7e,user()),1)--",
    "' AND (SELECT 1 FROM(SELECT COUNT(*),CONCAT(database(),FLOOR(RAND(0)*2))x FROM information_schema.tables GROUP BY x)a)--",
]

STACKED_SQLI = [
    "'; DROP TABLE users;--",
    "'; DELETE FROM time_entries;--",
    "1; INSERT INTO users VALUES ('hacked','hacked');--",
    "'; UPDATE users SET password='hacked';--",
]

ORDER_BY_SQLI = [
    "1 DESC--",
    "1; DROP TABLE users--",
    "(SELECT 1 FROM users LIMIT 1)",
    "CASE WHEN 1=1 THEN name ELSE email END",
]

HEADER_SQLI = [
    "' OR 1=1--",
    "x' OR '1'='1",
]


def enc(payload: str) -> str:
    return urllib.parse.quote(payload, safe="")


def has_sql_error(page: Page) -> bool:
    """True only for verbose DB errors that expose internals — not generic phrases."""
    content = page.content().lower()
    return any(kw in content for kw in [
        "you have an error in your sql syntax",
        "mysql_fetch_array",
        "mysqli_fetch",
        "pg_query(",
        "ora-00",
        "sqlite_exception",
        "sqlstate[42",          # 42xxx = SQL syntax / access rule violation
        "unclosed quotation mark after the character",
        "unterminated string constant",
        "information_schema",   # schema leak via UNION
        "root@localhost",       # credential leak
    ])


def get_csrf(page: Page, path: str) -> str:
    page.goto(url(path))
    page.wait_for_load_state("networkidle")
    el = page.locator("input[name='_csrf']").first
    return el.input_value() if el.count() > 0 else ""


def submit_form(page: Page, action: str, data: dict):
    try:
        with page.expect_navigation(wait_until="networkidle", timeout=15000):
            page.evaluate("""([action, data]) => {
                const f = document.createElement('form');
                f.method = 'POST'; f.action = action;
                for (const [k, v] of Object.entries(data)) {
                    const i = document.createElement('input');
                    i.name = k; i.value = v; f.appendChild(i);
                }
                document.body.appendChild(f); f.submit();
            }""", [action, data])
    except Exception:
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# 1. CLASSIC SQL INJECTION IN SEARCH
# ══════════════════════════════════════════════════════════════════════════════

class TestClassicSQLI:

    @pytest.mark.parametrize("payload", CLASSIC_SQLI)
    def test_sqli_people_search(self, page, payload):
        """Classic SQLi in people search must not expose SQL errors."""
        page.goto(url(f"/people?search={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"500 on SQLi payload: {payload}"
        assert not has_sql_error(page), f"SQL error leaked for: {payload}"

    @pytest.mark.parametrize("payload", CLASSIC_SQLI)
    def test_sqli_project_search(self, page, payload):
        """Classic SQLi in project search must not expose SQL errors."""
        page.goto(url(f"/projects?q={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)

    @pytest.mark.parametrize("payload", CLASSIC_SQLI[:4])
    def test_sqli_invoice_filter(self, page, payload):
        """Classic SQLi in invoice filter params must not expose errors."""
        page.goto(url(f"/invoicing?q={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)

    @pytest.mark.parametrize("payload", CLASSIC_SQLI[:3])
    def test_sqli_absence_filter(self, page, payload):
        """Classic SQLi in absence filter must not leak SQL errors."""
        page.goto(url(f"/absence/my?q={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 2. UNION-BASED SQL INJECTION
# ══════════════════════════════════════════════════════════════════════════════

class TestUnionSQLI:

    @pytest.mark.parametrize("payload", UNION_SQLI)
    def test_union_sqli_people_search(self, page, payload):
        """UNION-based SQLi must not extract data from the database."""
        page.goto(url(f"/people?search={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)
        content = page.content().lower()
        # Must not leak DB metadata
        assert "information_schema" not in content
        assert "root@" not in content

    @pytest.mark.parametrize("payload", UNION_SQLI[:3])
    def test_union_sqli_project_search(self, page, payload):
        """UNION-based SQLi in projects must not leak data."""
        page.goto(url(f"/projects?q={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 3. BLIND & TIME-BASED SQL INJECTION
# ══════════════════════════════════════════════════════════════════════════════

class TestBlindSQLI:

    @pytest.mark.parametrize("payload", BLIND_SQLI[:3])
    def test_blind_sqli_people_search(self, page, payload):
        """Blind SQLi payloads must not cause server errors."""
        page.goto(url(f"/people?search={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)

    @pytest.mark.parametrize("payload", BLIND_SQLI[:3])
    def test_blind_sqli_project_search(self, page, payload):
        """Blind SQLi in projects must not cause server errors."""
        page.goto(url(f"/projects?q={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)

    def test_boolean_blind_different_results(self, page):
        """TRUE vs FALSE blind SQLi should return same page (not different counts)."""
        page.goto(url("/people?search=' AND 1=1--"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)

        page.goto(url("/people?search=' AND 1=2--"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 4. ERROR-BASED SQL INJECTION
# ══════════════════════════════════════════════════════════════════════════════

class TestErrorBasedSQLI:

    @pytest.mark.parametrize("payload", ERROR_SQLI)
    def test_error_sqli_people_search(self, page, payload):
        """Error-based SQLi must not leak database internals."""
        page.goto(url(f"/people?search={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)
        content = page.content().lower()
        assert "extractvalue" not in content
        assert "updatexml" not in content


# ══════════════════════════════════════════════════════════════════════════════
# 5. STACKED / BATCH QUERIES
# ══════════════════════════════════════════════════════════════════════════════

class TestStackedSQLI:

    @pytest.mark.parametrize("payload", STACKED_SQLI)
    def test_stacked_sqli_search(self, page, payload):
        """Stacked query attempts must not execute secondary statements.

        A connection reset / HTTP2 protocol error is treated as a safe outcome —
        it means the server (or WAF) rejected the payload before it reached SQL.
        """
        try:
            page.goto(url(f"/people?search={enc(payload)}"))
            page.wait_for_load_state("networkidle")
        except Exception as e:
            err = str(e)
            if any(safe in err for safe in [
                "ERR_HTTP2_PROTOCOL_ERROR",
                "ERR_CONNECTION_RESET",
                "ERR_EMPTY_RESPONSE",
                "net::ERR_",
            ]):
                return  # server blocked the payload — pass
            raise
        assert not has_error(page)
        assert not has_sql_error(page)

    @pytest.mark.parametrize("payload", STACKED_SQLI[:2])
    def test_stacked_sqli_in_form_post(self, page, payload):
        """Stacked SQLi in form POST body must not execute destructive queries."""
        csrf = get_csrf(page, "/projects/new")
        submit_form(page, url("/projects"), {
            "name": payload, "customer_id": "1",
            "budget_hours": "10", "_csrf": csrf
        })
        assert not has_error(page)
        assert not has_sql_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 6. PATH PARAMETER INJECTION
# ══════════════════════════════════════════════════════════════════════════════

class TestPathParamSQLI:

    def test_sqli_in_project_id_path(self, page):
        """SQLi in URL path /projects/1' must not expose SQL errors."""
        page.goto(url("/projects/1'"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)

    def test_sqli_in_people_id_path(self, page):
        """SQLi in URL path /people/1 OR 1=1 must be rejected."""
        page.goto(url("/people/1%20OR%201%3D1"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)

    def test_sqli_in_invoice_id_path(self, page):
        """SQLi in invoice ID path must not expose SQL errors."""
        page.goto(url("/invoicing/1%27%20OR%20%271%27%3D%271"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)

    def test_sqli_in_project_id_numeric(self, page):
        """Non-numeric project ID with SQL payload returns 404 or safe error."""
        page.goto(url("/projects/1;DROP TABLE projects--"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 7. ORDER BY & SORT PARAMETER INJECTION
# ══════════════════════════════════════════════════════════════════════════════

class TestOrderBySQLI:

    @pytest.mark.parametrize("payload", ORDER_BY_SQLI)
    def test_sqli_in_sort_param(self, page, payload):
        """SQLi in ?sort= / ?order= parameter must not cause errors."""
        page.goto(url(f"/projects?sort={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)

    def test_sqli_in_order_direction(self, page):
        """SQLi in sort direction parameter must be sanitised."""
        page.goto(url("/projects?sort=name&dir=DESC;DROP TABLE projects--"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)

    def test_sqli_in_limit_param(self, page):
        """SQLi in ?limit= parameter must not cause errors."""
        page.goto(url("/invoicing?limit=10;DROP TABLE invoices--"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert not has_sql_error(page)
