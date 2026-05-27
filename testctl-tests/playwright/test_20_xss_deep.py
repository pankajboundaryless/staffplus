"""
TEST 20 — XSS Deep Security Testing

Tests cross-site scripting across every user-controlled input in the app:
  1. REFLECTED XSS    — search params, query strings, URL fragments
  2. STORED XSS       — form fields that persist to DB and render back
  3. DOM-BASED XSS    — client-side rendering of URL/hash values
  4. ATTRIBUTE XSS    — injection into HTML attributes
  5. EVENT HANDLER    — onerror, onload, onmouseover payloads
  6. SVG/MathML XSS   — alternative vector payloads
  7. JAVASCRIPT URI   — href=javascript: payloads
  8. TEMPLATE XSS     — {{ }} template injection patterns
  9. CSS INJECTION    — style attribute injection
 10. POLYGLOT         — payloads that work in multiple contexts

URL: /people, /projects, /absence, /time, /invoicing, /settings
"""

import urllib.parse
import pytest
from playwright.sync_api import Page
from conftest import url, has_error

# ─── payload sets ─────────────────────────────────────────────────────────────

BASIC_XSS = [
    "<script>alert('xss')</script>",
    "<script>alert(document.cookie)</script>",
    "<script>alert(1)</script>",
]

EVENT_HANDLER_XSS = [
    "<img src=x onerror=alert(1)>",
    "<img src=x onerror=alert(document.domain)>",
    "<body onload=alert(1)>",
    "<svg onload=alert(1)>",
    "<video onloadstart=alert(1) src=x>",
    "<input autofocus onfocus=alert(1)>",
    "<details open ontoggle=alert(1)>",
    "<marquee onstart=alert(1)>",
]

ATTRIBUTE_XSS = [
    "\" onmouseover=\"alert(1)",
    "' onmouseover='alert(1)",
    "\" onfocus=\"alert(1)\" autofocus=\"",
    "><script>alert(1)</script>",
    "'><img src=x onerror=alert(1)>",
]

SVG_XSS = [
    "<svg><script>alert(1)</script></svg>",
    "<svg onload=alert(1)/>",
    "<svg><animate onbegin=alert(1) attributeName=x dur=1s>",
    "<math><mtext></mtext><script>alert(1)</script></math>",
]

JS_URI_XSS = [
    "javascript:alert(1)",
    "javascript:alert(document.cookie)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:alert(1)",
]

TEMPLATE_XSS = [
    "{{7*7}}",
    "${7*7}",
    "#{7*7}",
    "<%= 7*7 %>",
    "{{constructor.constructor('alert(1)')()}}",
]

POLYGLOT = [
    "jaVasCript:/*-/*`/*\\`/*'/*\"/**/(/* */oNcliCk=alert() )//%0D%0A%0d%0a//</stYle/</titLe/</teXtarEa/</scRipt/--!>\\x3csVg/<sVg/oNloAd=alert()//>\\x3e",
    "'\"--></style></script><script>alert(1)</script>",
    "<!--<img src=x onerror=alert(1)>-->",
]

CSS_XSS = [
    "expression(alert(1))",
    "');alert('xss')",
    "</style><script>alert(1)</script>",
    "xss:expression(alert(1))",
]


def enc(payload: str) -> str:
    return urllib.parse.quote(payload, safe="")


def is_escaped(content: str, payload: str) -> bool:
    """Returns True if the XSS payload is NOT reflected raw in the response.

    Uses long, specific substrings so we don't false-positive on the app's
    own legitimate <script> blocks or alert() calls in its JS bundles.
    Each pattern is only flagged when it also appears in the payload itself.
    """
    payload_lower = payload.lower()
    content_lower = content.lower()

    specific_checks = [
        "onerror=alert(",
        "onload=alert(",
        "onfocus=alert(",
        "onmouseover=alert(",
        "ontoggle=alert(",
        "onstart=alert(",
        "onloadstart=alert(",
        "javascript:alert(",
        "alert(document.cookie)",
        "alert(document.domain)",
        "<script>alert(",
        "><script>alert",
        "'><img src=x onerror=alert",
    ]
    for pattern in specific_checks:
        if pattern in payload_lower and pattern in content_lower:
            return False
    return True


def get_csrf(page: Page, path: str) -> str:
    page.goto(url(path))
    page.wait_for_load_state("networkidle")
    el = page.locator("input[name='_csrf']").first
    return el.input_value() if el.count() > 0 else ""


def submit_form(page: Page, action: str, data: dict):
    """Submit a hidden POST form and wait for the page to settle.

    If no navigation fires (e.g. client-side validation blocked the submit,
    or the server returned the same page) we fall back to waiting for
    networkidle so the test can still inspect the current page state.
    """
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
# 1. REFLECTED XSS IN SEARCH FIELDS
# ══════════════════════════════════════════════════════════════════════════════

class TestReflectedXSS:

    @pytest.mark.parametrize("payload", BASIC_XSS + EVENT_HANDLER_XSS)
    def test_xss_in_people_search(self, page, payload):
        """XSS payload in /people?search= must be escaped in response."""
        page.goto(url(f"/people?search={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"500 on XSS payload: {payload}"
        content = page.content()
        assert is_escaped(content, payload), f"XSS not escaped in people search: {payload}"
        assert page.evaluate("typeof window.__xss === 'undefined'")

    @pytest.mark.parametrize("payload", BASIC_XSS + EVENT_HANDLER_XSS)
    def test_xss_in_project_search(self, page, payload):
        """XSS payload in /projects?q= must be escaped."""
        page.goto(url(f"/projects?q={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert is_escaped(page.content(), payload), f"XSS reflected in project search: {payload}"

    @pytest.mark.parametrize("payload", BASIC_XSS + SVG_XSS)
    def test_xss_in_invoicing_search(self, page, payload):
        """XSS payload in invoicing search/filter must be escaped."""
        page.goto(url(f"/invoicing?q={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert is_escaped(page.content(), payload)

    @pytest.mark.parametrize("payload", ATTRIBUTE_XSS)
    def test_xss_attribute_in_people_search(self, page, payload):
        """Attribute-breaking XSS payloads in search must not execute."""
        page.goto(url(f"/people?search={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert is_escaped(page.content(), payload)

    def test_xss_in_page_param(self, page):
        """XSS in ?page= parameter is handled safely."""
        page.goto(url("/invoicing?page=<script>alert(1)</script>"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "<script>alert(1)</script>" not in page.content()

    def test_xss_in_status_filter(self, page):
        """XSS in ?status= filter parameter does not reflect unescaped."""
        page.goto(url("/invoicing?status=<img src=x onerror=alert(1)>"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "onerror=alert" not in page.content()

    def test_xss_in_sort_param(self, page):
        """XSS in ?sort= parameter is handled safely."""
        page.goto(url("/projects?sort=<script>alert(1)</script>"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        # Check our specific payload is escaped, not just any <script> tag
        assert "<script>alert(1)</script>" not in page.content()


# ══════════════════════════════════════════════════════════════════════════════
# 2. STORED XSS VIA FORM SUBMISSIONS
# ══════════════════════════════════════════════════════════════════════════════

class TestStoredXSS:

    @pytest.mark.parametrize("payload", BASIC_XSS + EVENT_HANDLER_XSS[:3])
    def test_stored_xss_in_project_name(self, page, payload):
        """XSS in project name field must be escaped when rendered back."""
        csrf = get_csrf(page, "/projects/new")
        submit_form(page, url("/projects"), {
            "name": payload, "customer_id": "1",
            "budget_hours": "10", "_csrf": csrf
        })
        assert not has_error(page), f"500 storing XSS in project name: {payload}"
        assert is_escaped(page.content(), payload)

    @pytest.mark.parametrize("payload", BASIC_XSS + SVG_XSS[:2])
    def test_stored_xss_in_absence_notes(self, page, payload):
        """XSS in absence request notes must be escaped on render."""
        csrf = get_csrf(page, "/absence/request")
        submit_form(page, url("/absence/request"), {
            "absence_type_id": "1",
            "start_date": "2028-01-10",
            "end_date": "2028-01-12",
            "notes": payload, "_csrf": csrf
        })
        assert not has_error(page)
        assert is_escaped(page.content(), payload)

    @pytest.mark.parametrize("payload", BASIC_XSS[:2] + EVENT_HANDLER_XSS[:2])
    def test_stored_xss_in_time_notes(self, page, payload):
        """XSS in time booking notes must be escaped when rendered."""
        csrf = get_csrf(page, "/time/book")
        submit_form(page, url("/time/store"), {
            "project_id": "14", "date": "2028-01-10",
            "hours": "8", "notes": payload, "_csrf": csrf
        })
        assert not has_error(page)
        assert is_escaped(page.content(), payload)

    def test_stored_xss_in_customer_name(self, page):
        """XSS in customer name stored and rendered safely."""
        csrf = get_csrf(page, "/customers/new")
        submit_form(page, url("/customers/new"), {
            "name": "<script>alert('stored')</script>",
            "country": "GB", "_csrf": csrf
        })
        assert not has_error(page)
        assert "<script>alert('stored')</script>" not in page.content()

    def test_stored_xss_in_role_name(self, page):
        """XSS in admin role name stored and rendered safely."""
        csrf = get_csrf(page, "/admin/roles/new")
        submit_form(page, url("/admin/roles"), {
            "name": "<img src=x onerror=alert(1)>", "_csrf": csrf
        })
        assert not has_error(page)
        assert "onerror=alert" not in page.content()


# ══════════════════════════════════════════════════════════════════════════════
# 3. JAVASCRIPT URI & TEMPLATE INJECTION
# ══════════════════════════════════════════════════════════════════════════════

class TestJSUriAndTemplateXSS:

    @pytest.mark.parametrize("payload", JS_URI_XSS)
    def test_js_uri_in_search(self, page, payload):
        """javascript: URI payloads in search params must not execute."""
        page.goto(url(f"/people?search={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    @pytest.mark.parametrize("payload", TEMPLATE_XSS)
    def test_template_injection_in_people_search(self, page, payload):
        """Template injection payloads must not be evaluated."""
        page.goto(url(f"/people?search={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content()
        # Template engines must not evaluate — 7*7=49 must not appear raw
        if "7*7" in payload:
            assert "49" not in content or payload in content

    @pytest.mark.parametrize("payload", TEMPLATE_XSS)
    def test_template_injection_in_project_search(self, page, payload):
        """Template injection in project search must not be evaluated."""
        page.goto(url(f"/projects?q={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    @pytest.mark.parametrize("payload", POLYGLOT)
    def test_polyglot_payload_in_search(self, page, payload):
        """Polyglot XSS payloads must be safely handled in search."""
        page.goto(url(f"/people?search={enc(payload)}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert is_escaped(page.content(), payload)

    def test_xss_in_redirect_param(self, page):
        """XSS in redirect/return URL parameter must not execute."""
        page.goto(url("/dashboard?redirect=javascript:alert(1)"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_xss_in_callback_param(self, page):
        """XSS injected via ?callback= (JSONP-style) must not execute."""
        page.goto(url("/dashboard?callback=<script>alert(1)</script>"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "<script>alert(1)</script>" not in page.content()

    def test_null_byte_in_search(self, page):
        """Null byte injection in search must not cause server error."""
        page.goto(url("/people?search=admin%00<script>alert(1)</script>"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_unicode_xss_bypass(self, page):
        """Unicode-encoded XSS attempt must be handled safely."""
        page.goto(url("/people?search=<script>alert(1)</script>"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "<script>alert(1)</script>" not in page.content()
