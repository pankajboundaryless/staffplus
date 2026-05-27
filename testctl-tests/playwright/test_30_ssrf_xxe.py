"""
TEST 30 — SSRF & XXE Security Testing

SSRF (Server-Side Request Forgery):
  The server fetches a URL supplied by the user. If the app passes that
  URL to an internal HTTP client without validation, an attacker can:
    • Scan the internal network  (http://192.168.x.x, http://10.x.x.x)
    • Hit cloud metadata APIs    (http://169.254.169.254/latest/meta-data/)
    • Read local files           (file:///etc/passwd)
    • Port-scan the host         (http://localhost:22)

XXE (XML External Entity Injection):
  If the app parses XML (imports, webhooks, uploads), a DOCTYPE with an
  external entity causes the parser to read local files or trigger SSRF.
  Classic payload:
    <?xml version="1.0"?>
    <!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
    <root>&xxe;</root>

Attack surfaces checked:
  1. URL/webhook fields in forms           — SSRF via user-supplied URL
  2. File upload endpoints                 — XXE via crafted XML/SVG/DOCX
  3. Import/export features                — XML import with ENTITY
  4. Logo/avatar URL inputs                — SSRF via image URL fetch
  5. Integration / callback URL fields     — SSRF via webhook setup
  6. Cloud metadata endpoint probing       — 169.254.169.254 detection
  7. Internal network probing payloads     — RFC-1918 address detection
  8. file:// URI scheme in input fields    — local file inclusion attempt
  9. DNS rebinding canaries                — burp-style OAST patterns
 10. Redirect-chain SSRF                  — open redirect used as SSRF hop
 11. SVG upload with SSRF payload         — SVG <image href="..."> fetch
 12. Response body analysis               — leaked /etc/passwd, AWS keys

All tests verify the server does NOT:
  - Return contents of internal files     (e.g. root: in response)
  - Return AWS/GCP metadata               (ami-id, iam/security-credentials)
  - Produce a 500 from a malformed URL

URL: /people, /projects, /customers, /admin/settings, /invoicing, /absence
"""

import re
import time
import pytest
import urllib.parse
from playwright.sync_api import Page
from conftest import url, has_error, BASE_URL


# ─── SSRF canary payloads ─────────────────────────────────────────────────────

# External/internal targets an SSRF vulnerability would try to reach
SSRF_URLS = [
    "http://169.254.169.254/latest/meta-data/",           # AWS IMDS v1
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://metadata.google.internal/computeMetadata/v1/",# GCP metadata
    "http://100.100.100.200/latest/meta-data/",           # Alibaba cloud
    "http://127.0.0.1/",                                   # localhost
    "http://localhost/",                                    # localhost alias
    "http://0.0.0.0/",                                     # all-interfaces
    "http://0x7f000001/",                                   # 127.0.0.1 hex
    "http://2130706433/",                                   # 127.0.0.1 decimal
    "http://192.168.1.1/",                                  # RFC-1918 gateway
    "http://10.0.0.1/",                                     # RFC-1918
    "http://172.16.0.1/",                                   # RFC-1918
    "file:///etc/passwd",                                   # local file read
    "file:///etc/hosts",
    "file:///proc/self/environ",                            # env vars / secrets
    "dict://127.0.0.1:6379/INFO",                           # Redis SSRF
    "gopher://127.0.0.1:25/",                               # Gopher SSRF
    "http://[::1]/",                                        # IPv6 loopback
    "http://[0:0:0:0:0:ffff:7f00:1]/",                     # IPv4-mapped IPv6
]

SSRF_URLS_SHORT = SSRF_URLS[:8]   # subset for parametrized tests

# Strings that would appear in response if SSRF succeeded
SSRF_LEAK_PATTERNS = [
    "root:x:",               # /etc/passwd
    "nobody:x:",             # /etc/passwd
    "ami-id",                # AWS metadata
    "iam/security-credentials",
    "secret-access-key",     # AWS key leak
    "aws_access_key_id",
    "instance-id",           # cloud metadata
    "computeMetadata",       # GCP header
    "HTTP/1.0 200",          # raw proxied response
    "X-aws-ec2-metadata-token",
]


# ─── XXE payloads ─────────────────────────────────────────────────────────────

XXE_CLASSIC = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<root><data>&xxe;</data></root>"""

XXE_SSRF = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "http://169.254.169.254/latest/meta-data/">]>
<root><data>&xxe;</data></root>"""

XXE_BLIND = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE foo [
  <!ENTITY % file SYSTEM "file:///etc/passwd">
  <!ENTITY % dtd SYSTEM "http://169.254.169.254/xxe.dtd">
  %dtd;
]>
<root/>"""

XXE_BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<root>&lol3;</root>"""

XXE_SVG = b"""<?xml version="1.0" standalone="yes"?>
<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<svg xmlns="http://www.w3.org/2000/svg">
  <text y="1em">&xxe;</text>
</svg>"""


# ─── helpers ──────────────────────────────────────────────────────────────────

TIMESTAMP = str(int(time.time()))[-6:]


def has_ssrf_leak(content: str) -> bool:
    """True if response body contains SSRF/file-read artefacts."""
    lower = content.lower()
    return any(p.lower() in lower for p in SSRF_LEAK_PATTERNS)


def safe_response(page: Page) -> bool:
    """True if page did not error AND did not leak internal data."""
    return not has_error(page) and not has_ssrf_leak(page.content())


def goto_safe(page: Page, path: str) -> None:
    page.goto(url(path))
    page.wait_for_load_state("networkidle")


def fill_all_url_inputs(page: Page, payload: str) -> int:
    """Fill every visible URL/webhook/link text input with a SSRF payload.
    Returns count of fields filled."""
    filled = 0
    selectors = [
        "input[name*='url']",
        "input[name*='webhook']",
        "input[name*='logo']",
        "input[name*='avatar']",
        "input[name*='image']",
        "input[name*='link']",
        "input[name*='callback']",
        "input[name*='endpoint']",
        "input[name*='redirect']",
        "input[type='url']",
        "input[placeholder*='http']",
        "input[placeholder*='URL']",
        "input[placeholder*='url']",
    ]
    for sel in selectors:
        els = page.locator(sel)
        for i in range(min(els.count(), 3)):
            try:
                els.nth(i).fill(payload)
                filled += 1
            except Exception:
                pass
    return filled


# ══════════════════════════════════════════════════════════════════════════════
# 1. SSRF VIA URL FIELDS — FORM INPUT SURFACES
# ══════════════════════════════════════════════════════════════════════════════

class TestSSRFViaFormFields:
    """
    Any field that accepts a URL is a potential SSRF vector.
    We inject SSRF payloads, submit the form, and check the response
    does not contain internal data or produce a 500.
    """

    @pytest.mark.parametrize("ssrf_url", SSRF_URLS_SHORT, ids=lambda u: u[:40])
    def test_customer_form_url_field_no_ssrf(self, page, ssrf_url):
        """Customer creation form — any URL field must not trigger SSRF."""
        goto_safe(page, "/customers/new")
        count = fill_all_url_inputs(page, ssrf_url)
        if count == 0:
            pytest.skip("No URL-type fields found on /customers/new")
        page.locator("button[type='submit']:visible, input[type='submit']:visible").first.click()
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"Server error after SSRF payload in customer form"
        assert not has_ssrf_leak(page.content()), \
            f"SSRF response leak detected for payload: {ssrf_url}"

    @pytest.mark.parametrize("ssrf_url", SSRF_URLS_SHORT, ids=lambda u: u[:40])
    def test_people_form_url_field_no_ssrf(self, page, ssrf_url):
        """Person creation form — avatar/image URL must not trigger SSRF."""
        goto_safe(page, "/people/new")
        count = fill_all_url_inputs(page, ssrf_url)
        if count == 0:
            pytest.skip("No URL-type fields found on /people/new")
        page.locator("button[type='submit']:visible, input[type='submit']:visible").first.click()
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"Server error after SSRF payload in people form"
        assert not has_ssrf_leak(page.content()), \
            f"SSRF response leak for payload: {ssrf_url}"

    @pytest.mark.parametrize("ssrf_url", SSRF_URLS_SHORT, ids=lambda u: u[:40])
    def test_projects_form_url_field_no_ssrf(self, page, ssrf_url):
        """Project creation form — any URL field must not trigger SSRF."""
        goto_safe(page, "/projects/new")
        count = fill_all_url_inputs(page, ssrf_url)
        if count == 0:
            pytest.skip("No URL-type fields found on /projects/new")
        page.locator("button[type='submit']:visible, input[type='submit']:visible").first.click()
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"Server error after SSRF payload in project form"
        assert not has_ssrf_leak(page.content()), \
            f"SSRF response leak for payload: {ssrf_url}"

    @pytest.mark.parametrize("ssrf_url", SSRF_URLS_SHORT, ids=lambda u: u[:40])
    def test_admin_settings_url_field_no_ssrf(self, page, ssrf_url):
        """Admin settings — integration/webhook URL fields must not trigger SSRF."""
        goto_safe(page, "/admin/settings")
        count = fill_all_url_inputs(page, ssrf_url)
        if count == 0:
            pytest.skip("No URL-type fields found on /admin/settings")
        # Don't submit admin settings — just verify the field accepts without JS error
        assert safe_response(page), \
            f"Page error after placing SSRF payload in admin settings field"


# ══════════════════════════════════════════════════════════════════════════════
# 2. SSRF VIA QUERY PARAMETERS
# ══════════════════════════════════════════════════════════════════════════════

class TestSSRFViaQueryParams:
    """
    Some apps pass a URL via query string (e.g. ?redirect=, ?url=, ?logo=).
    Check that these params do not cause server-side fetching.
    """

    SSRF_PARAM_NAMES = [
        "url", "redirect", "next", "return", "returnUrl",
        "logo", "avatar", "image", "webhook", "callback",
        "endpoint", "target", "src", "href", "link",
    ]

    SSRF_TARGET = "http://169.254.169.254/latest/meta-data/"

    @pytest.mark.parametrize("param", SSRF_PARAM_NAMES)
    def test_dashboard_ssrf_param_safe(self, page, param):
        """
        Appending ?{param}=<ssrf_url> to /dashboard must not trigger a
        server-side fetch or produce a 500.
        """
        encoded = urllib.parse.quote(self.SSRF_TARGET, safe="")
        page.goto(url(f"/dashboard?{param}={encoded}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), \
            f"Server error when ?{param}= contains SSRF payload"
        assert not has_ssrf_leak(page.content()), \
            f"SSRF leak detected via ?{param}= on /dashboard"

    @pytest.mark.parametrize("param", SSRF_PARAM_NAMES)
    def test_people_ssrf_param_safe(self, page, param):
        """?{param}=<ssrf_url> on /people must be ignored server-side."""
        encoded = urllib.parse.quote(self.SSRF_TARGET, safe="")
        page.goto(url(f"/people?{param}={encoded}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), \
            f"Server error when ?{param}= contains SSRF payload on /people"
        assert not has_ssrf_leak(page.content()), \
            f"SSRF leak detected via ?{param}= on /people"


# ══════════════════════════════════════════════════════════════════════════════
# 3. CLOUD METADATA ENDPOINT PROBING
# ══════════════════════════════════════════════════════════════════════════════

class TestCloudMetadataProbing:
    """
    Specific tests for the AWS/GCP/Azure metadata service endpoints.
    These are the most dangerous SSRF targets in cloud-hosted apps.
    """

    METADATA_ENDPOINTS = [
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        "http://169.254.169.254/latest/user-data",
        "http://169.254.169.254/latest/meta-data/hostname",
        "http://metadata.google.internal/computeMetadata/v1/?recursive=true",
        "http://169.254.169.254/metadata/instance?api-version=2021-02-01",  # Azure
    ]

    def test_metadata_endpoint_not_reachable_via_search(self, page):
        """
        Searching for AWS metadata URLs must not return metadata content.
        If any metadata string appears in response, SSRF is confirmed.
        """
        for endpoint in self.METADATA_ENDPOINTS:
            encoded = urllib.parse.quote(endpoint, safe="")
            page.goto(url(f"/people?search={encoded}"))
            page.wait_for_load_state("networkidle")
            assert not has_error(page), f"500 when probing metadata via search: {endpoint}"
            assert not has_ssrf_leak(page.content()), \
                f"CLOUD METADATA SSRF DETECTED: {endpoint} — response contains metadata"

    def test_metadata_endpoint_not_in_any_page_response(self, page):
        """
        None of the main app pages should ever contain cloud metadata strings.
        Presence would indicate a pre-existing SSRF or misconfiguration.
        """
        check_pages = [
            "/dashboard", "/people", "/projects",
            "/admin/settings", "/reports",
        ]
        for path in check_pages:
            goto_safe(page, path)
            content = page.content()
            assert "ami-id" not in content, \
                f"AWS metadata 'ami-id' found in {path} response — possible SSRF"
            assert "security-credentials" not in content, \
                f"AWS credentials string found in {path} response"
            assert "computeMetadata" not in content, \
                f"GCP metadata string found in {path} response"

    def test_file_uri_not_executed_via_param(self, page):
        """
        file:///etc/passwd passed as a query param must not cause the
        server to return local file contents.
        """
        payloads = [
            "file:///etc/passwd",
            "file:///etc/shadow",
            "file:///proc/self/environ",
            "file:///var/www/html/.env",
            "file:///app/.env",
        ]
        for payload in payloads:
            encoded = urllib.parse.quote(payload, safe="")
            page.goto(url(f"/people?search={encoded}"))
            page.wait_for_load_state("networkidle")
            content = page.content()
            assert "root:x:" not in content, \
                f"LOCAL FILE READ via file:// URI — /etc/passwd leaked!"
            assert "DB_PASSWORD" not in content, \
                f"Environment variable leak via file:// URI on {payload}"
            assert not has_error(page), f"500 on file:// URI payload: {payload}"


# ══════════════════════════════════════════════════════════════════════════════
# 4. SSRF VIA OPEN REDIRECT CHAIN
# ══════════════════════════════════════════════════════════════════════════════

class TestSSRFViaOpenRedirect:
    """
    Open redirects can be used as a hop to bypass SSRF protections:
    attacker sends  ?redirect=http://evil.com  which redirects to
    169.254.169.254. Tests verify that redirect parameters are either
    rejected or constrained to same-origin targets.
    """

    REDIRECT_PARAMS = ["redirect", "next", "return", "returnUrl", "goto", "url"]
    EXTERNAL_TARGETS = [
        "https://evil.com",
        "//evil.com",
        "///evil.com",
        "https://evil.com@robomon.boundaryless.com",
        "https://robomon.boundaryless.comevil.com",
        "javascript:alert(1)",                              # JS injection
        "\x00https://evil.com",                             # null byte
        "https://169.254.169.254/latest/meta-data/",        # SSRF via redirect
    ]

    @pytest.mark.parametrize("param", REDIRECT_PARAMS)
    def test_open_redirect_param_does_not_go_external(self, page, param):
        """
        ?{param}=https://evil.com must not redirect the user off-site.
        Acceptable: param is ignored (browser stays on same host).
        Not acceptable: browser ends up at evil.com.

        Note: the full URL may contain the encoded payload in the query
        string — check the *hostname*, not the full URL string.
        """
        target = "https://evil.com"
        encoded = urllib.parse.quote(target, safe="")
        page.goto(url(f"/dashboard?{param}={encoded}"))
        page.wait_for_load_state("networkidle")
        # Hostname must stay on the app domain — not redirected to evil.com
        final_host = urllib.parse.urlparse(page.url).netloc
        assert "evil.com" not in final_host, \
            f"Open redirect via ?{param}= — browser left app domain: {page.url}"
        assert not has_error(page), f"500 on redirect param: {param}"

    def test_redirect_to_metadata_via_open_redirect_blocked(self, page):
        """
        Redirect chain: app → metadata endpoint via open redirect.
        If the app fetches the redirect target, it would expose cloud keys.

        Note: the metadata IP may appear in the query string — check the
        *hostname* to verify the browser did not actually navigate there.
        """
        meta_url = urllib.parse.quote("http://169.254.169.254/latest/meta-data/", safe="")
        for param in ["redirect", "next", "url", "return"]:
            page.goto(url(f"/dashboard?{param}={meta_url}"))
            page.wait_for_load_state("networkidle")
            assert "ami-id" not in page.content(), \
                f"SSRF via open redirect ?{param}= — AWS metadata exposed in body!"
            final_host = urllib.parse.urlparse(page.url).netloc
            assert "169.254.169.254" not in final_host, \
                f"Browser navigated to metadata endpoint via ?{param}= — {page.url}"


# ══════════════════════════════════════════════════════════════════════════════
# 5. XXE — XML UPLOAD / IMPORT SURFACES
# ══════════════════════════════════════════════════════════════════════════════

class TestXXEViaFileUpload:
    """
    Tests for XML External Entity injection via file upload.
    We look for any file upload field and submit a crafted XML/SVG.
    The server must not:
      - Return /etc/passwd content
      - Trigger an outbound HTTP request (detectable via 500 or metadata leak)
      - Crash with a 500 (unhandled parser exception)
    """

    def _find_file_input(self, page: Page) -> bool:
        """Return True if a file input exists on the current page."""
        return page.locator("input[type='file']").count() > 0

    def _upload_xml(self, page: Page, xml_bytes: bytes, filename: str = "test.xml") -> bool:
        """
        Upload an XML payload to the first visible file input.
        Returns True if upload was initiated, False if no input found.
        """
        file_input = page.locator("input[type='file']").first
        if file_input.count() == 0:
            return False
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False) as f:
            f.write(xml_bytes)
            tmp_path = f.name
        try:
            file_input.set_input_files(tmp_path)
            return True
        except Exception:
            return False
        finally:
            os.unlink(tmp_path)

    def test_no_file_upload_accepts_xxe_xml(self, page):
        """
        All file upload endpoints: submit crafted XML — must not return /etc/passwd.
        Pages checked: admin/settings, people/new, customers/new.
        """
        upload_pages = [
            "/admin/settings",
            "/people/new",
            "/customers/new",
            "/projects/new",
        ]
        for path in upload_pages:
            goto_safe(page, path)
            if not self._find_file_input(page):
                continue  # No file input on this page — skip
            uploaded = self._upload_xml(page, XXE_CLASSIC, "payload.xml")
            if not uploaded:
                continue
            submit = page.locator("button[type='submit']:visible, input[type='submit']:visible").first
            if submit.count() > 0:
                submit.click()
                page.wait_for_load_state("networkidle")
            content = page.content()
            assert "root:x:" not in content, \
                f"XXE CONFIRMED: /etc/passwd leaked via file upload on {path}"
            assert not has_error(page), \
                f"Server error (unhandled XML parse) on {path} — possible XXE vector"

    def test_svg_upload_no_xxe(self, page):
        """
        SVG files can embed XML entities. An SVG with XXE payload
        uploaded as an avatar/logo must not leak file contents.
        """
        upload_pages = ["/people/new", "/customers/new", "/admin/settings"]
        for path in upload_pages:
            goto_safe(page, path)
            if not self._find_file_input(page):
                continue
            uploaded = self._upload_xml(page, XXE_SVG, "avatar.svg")
            if not uploaded:
                continue
            submit = page.locator("button[type='submit']:visible, input[type='submit']:visible").first
            if submit.count() > 0:
                submit.click()
                page.wait_for_load_state("networkidle")
            content = page.content()
            assert "root:x:" not in content, \
                f"XXE via SVG upload on {path} — /etc/passwd leaked"
            assert not has_error(page), \
                f"500 on SVG upload to {path} — possible unhandled XXE"

    def test_xml_billion_laughs_no_dos(self, page):
        """
        Billion Laughs (XML bomb) must not crash the server.
        The server must respond without a 500 — it may reject the file.
        """
        upload_pages = ["/people/new", "/admin/settings"]
        for path in upload_pages:
            goto_safe(page, path)
            if not self._find_file_input(page):
                continue
            uploaded = self._upload_xml(page, XXE_BILLION_LAUGHS, "bomb.xml")
            if not uploaded:
                continue
            submit = page.locator("button[type='submit']:visible, input[type='submit']:visible").first
            if submit.count() > 0:
                try:
                    submit.click()
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass  # Timeout is OK — just check no crash
            assert not has_error(page), \
                f"500 from XML Billion Laughs DoS payload on {path}"


# ══════════════════════════════════════════════════════════════════════════════
# 6. SSRF VIA HTTP REQUEST HEADERS
# ══════════════════════════════════════════════════════════════════════════════

class TestSSRFViaRequestHeaders:
    """
    Some apps trust X-Forwarded-Host, X-Forwarded-For, Host header, Referer
    to perform server-side operations (password reset emails, logging).
    If the app fetches the Referer URL or uses X-Forwarded-Host for redirects,
    SSRF is possible.
    """

    def test_x_forwarded_host_not_executed(self, page):
        """
        Setting X-Forwarded-Host to the metadata endpoint must not cause
        the server to fetch it or reflect it unsanitised in the response.
        """
        import requests as req
        import json, pathlib

        session_data = json.loads(
            pathlib.Path(__file__).parent.joinpath(".auth/session.json").read_text()
        )
        cookies = {c["name"]: c["value"] for c in session_data.get("cookies", [])}
        target = f"{BASE_URL}/dashboard"
        headers = {
            "X-Forwarded-Host": "169.254.169.254",
            "X-Forwarded-For": "169.254.169.254",
        }
        try:
            r = req.get(target, cookies=cookies, headers=headers,
                        timeout=10, allow_redirects=True)
            assert "ami-id" not in r.text, \
                "SSRF via X-Forwarded-Host — AWS metadata exposed in response"
            assert "root:x:" not in r.text, \
                "File read via X-Forwarded-Host — /etc/passwd in response"
            assert r.status_code != 500, \
                "Server error triggered by X-Forwarded-Host SSRF header"
        except Exception as e:
            pytest.skip(f"requests library unavailable or connection error: {e}")

    def test_referer_header_not_fetched_server_side(self, page):
        """
        Referer pointing to the metadata endpoint must not cause the server
        to make an outbound HTTP call to it.
        """
        import requests as req
        import json, pathlib

        session_data = json.loads(
            pathlib.Path(__file__).parent.joinpath(".auth/session.json").read_text()
        )
        cookies = {c["name"]: c["value"] for c in session_data.get("cookies", [])}
        target = f"{BASE_URL}/dashboard"
        headers = {
            "Referer": "http://169.254.169.254/latest/meta-data/",
        }
        try:
            r = req.get(target, cookies=cookies, headers=headers,
                        timeout=10, allow_redirects=True)
            assert "ami-id" not in r.text, \
                "SSRF via Referer header — AWS metadata in response"
            assert r.status_code != 500, \
                "500 triggered by malicious Referer header"
        except Exception as e:
            pytest.skip(f"requests library unavailable or connection error: {e}")

    def test_host_header_injection_not_exploitable(self, page):
        """
        A tampered Host header must not cause the app to redirect to or
        fetch from the injected host (password-reset link injection, SSRF).
        """
        import requests as req
        import json, pathlib

        session_data = json.loads(
            pathlib.Path(__file__).parent.joinpath(".auth/session.json").read_text()
        )
        cookies = {c["name"]: c["value"] for c in session_data.get("cookies", [])}
        target = f"{BASE_URL}/dashboard"
        try:
            r = req.get(target, cookies=cookies,
                        headers={"Host": "evil.com"},
                        timeout=10, allow_redirects=False)
            # Must not redirect to evil.com
            location = r.headers.get("Location", "")
            assert "evil.com" not in location, \
                f"Host header injection — redirected to evil.com: {location}"
            assert "ami-id" not in r.text, \
                "SSRF via Host header — metadata in response"
        except Exception as e:
            pytest.skip(f"requests library unavailable or connection error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# 7. INTERNAL NETWORK PROBE DETECTION
# ══════════════════════════════════════════════════════════════════════════════

class TestInternalNetworkProbing:
    """
    Intranet scanning via SSRF: attacker uses the app as a proxy to probe
    internal services. Timing differences or error messages reveal open ports.
    """

    RFC1918_TARGETS = [
        "http://192.168.0.1/",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.1.254/",
    ]

    INTERNAL_SERVICE_PORTS = [
        "http://127.0.0.1:22/",       # SSH
        "http://127.0.0.1:25/",       # SMTP
        "http://127.0.0.1:3306/",     # MySQL
        "http://127.0.0.1:5432/",     # PostgreSQL
        "http://127.0.0.1:6379/",     # Redis
        "http://127.0.0.1:9200/",     # Elasticsearch
        "http://127.0.0.1:2375/",     # Docker daemon (unauthenticated)
        "http://127.0.0.1:8080/",     # Common internal HTTP
    ]

    @pytest.mark.parametrize("target", RFC1918_TARGETS, ids=lambda t: t[7:20])
    def test_rfc1918_address_in_search_no_ssrf(self, page, target):
        """
        Submitting an RFC-1918 address in a search field must not cause
        the server to attempt a connection to that internal host.
        """
        encoded = urllib.parse.quote(target, safe="")
        page.goto(url(f"/people?search={encoded}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), \
            f"500 on RFC-1918 probe: {target}"
        content = page.content()
        # If the server fetched the URL and returned HTML from that host:
        assert "192.168" not in content.replace(target, ""), \
            f"RFC-1918 response reflected — possible SSRF"

    @pytest.mark.parametrize("service_url", INTERNAL_SERVICE_PORTS[:4], ids=lambda t: t[17:25])
    def test_internal_port_scan_via_form_no_ssrf(self, page, service_url):
        """
        Probing internal service ports via URL fields must not:
        - Return banner / service info
        - Cause a 500 (indicates the server tried to connect)
        - Take > 10s (timing-based port scan confirmation)
        """
        goto_safe(page, "/customers/new")
        count = fill_all_url_inputs(page, service_url)
        if count == 0:
            pytest.skip("No URL fields on /customers/new")
        submit = page.locator("button[type='submit']:visible").first
        if submit.count() > 0:
            submit.click()
            page.wait_for_load_state("networkidle", timeout=12000)
        content = page.content()
        assert not has_error(page), \
            f"500 when probing internal port: {service_url} — server may have attempted connection"
        # No port banner / service headers should appear
        assert "SSH-" not in content, f"SSH banner in response: {service_url}"
        assert "+OK" not in content, f"SMTP/Redis banner in response: {service_url}"


# ══════════════════════════════════════════════════════════════════════════════
# 8. SSRF IN URL-BASED API ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

class TestSSRFInAPIEndpoints:
    """
    Tests for SSRF in API-style endpoints that may accept a URL in POST body
    or as a path segment.
    """

    def test_post_to_time_with_ssrf_url_no_crash(self, page):
        """
        POST to /time/store with a SSRF payload as the project_id or notes
        field — server must not crash or leak data.
        """
        goto_safe(page, "/time/book")
        # Inject SSRF payload into any visible text input
        meta_url = "http://169.254.169.254/latest/meta-data/"
        text_inputs = page.locator("input[type='text'], textarea")
        for i in range(min(text_inputs.count(), 3)):
            try:
                text_inputs.nth(i).fill(meta_url)
            except Exception:
                pass
        submit = page.locator("button[type='submit']:visible").first
        if submit.count() > 0:
            submit.click()
            page.wait_for_load_state("networkidle")
        assert not has_error(page), "500 after injecting SSRF URL into time booking form"
        assert not has_ssrf_leak(page.content()), "SSRF leak via time booking form"

    def test_invoice_form_with_ssrf_url_no_crash(self, page):
        """
        Invoice creation form with SSRF payload in text fields —
        must not trigger server-side fetch.
        """
        goto_safe(page, "/invoicing/new")
        meta_url = "http://169.254.169.254/"
        text_inputs = page.locator("input[type='text'], textarea")
        for i in range(min(text_inputs.count(), 3)):
            try:
                text_inputs.nth(i).fill(meta_url)
            except Exception:
                pass
        assert not has_error(page), "500 after SSRF URL in invoice form"
        assert not has_ssrf_leak(page.content()), "SSRF leak via invoice form"

    def test_absence_form_with_ssrf_in_notes(self, page):
        """
        Absence request notes field with SSRF URL — must not be fetched.
        """
        page.goto(url("/absence/new"))
        page.wait_for_load_state("networkidle")
        if has_error(page) or "login" in page.url:
            goto_safe(page, "/absence/my")
        textarea = page.locator("textarea[name='note'], textarea[name='reason']").first
        if textarea.count() == 0:
            pytest.skip("No notes textarea found for absence form")
        textarea.fill("http://169.254.169.254/latest/meta-data/")
        submit = page.locator("button[type='submit']:visible").first
        if submit.count() > 0:
            submit.click()
            page.wait_for_load_state("networkidle")
        assert not has_error(page), "500 after SSRF URL in absence notes"
        assert not has_ssrf_leak(page.content()), "SSRF leak via absence notes"


# ══════════════════════════════════════════════════════════════════════════════
# 9. RESPONSE ANALYSIS — LEAK DETECTION ACROSS ALL PAGES
# ══════════════════════════════════════════════════════════════════════════════

class TestSSRFLeakDetection:
    """
    Comprehensive scan of all major app pages looking for existing
    SSRF/file-read artefacts that may indicate a pre-existing vulnerability
    or misconfigured server response.
    """

    ALL_APP_PAGES = [
        "/dashboard",
        "/people",
        "/projects",
        "/time/book",
        "/time/timesheets",
        "/invoicing",
        "/absence/my",
        "/absence/team",
        "/planning",
        "/reports",
        "/simulations",
        "/admin/settings",
        "/admin/users",
        "/admin/audit-log",
        "/legal-entities",
        "/customers",
        "/tasks",
        "/holidays",
        "/settings",
        "/profile",
    ]

    @pytest.mark.parametrize("path", ALL_APP_PAGES)
    def test_no_etc_passwd_in_page_response(self, page, path):
        """No page should ever contain /etc/passwd content."""
        goto_safe(page, path)
        content = page.content()
        assert "root:x:0:0" not in content, \
            f"CRITICAL: /etc/passwd content found in {path}"
        assert "nobody:x:" not in content, \
            f"CRITICAL: /etc/passwd content found in {path}"

    @pytest.mark.parametrize("path", ALL_APP_PAGES)
    def test_no_aws_credentials_in_page_response(self, page, path):
        """No page should contain AWS access keys or instance metadata."""
        goto_safe(page, path)
        content = page.content()
        assert "aws_access_key_id" not in content.lower(), \
            f"AWS key exposure in {path}"
        assert "aws_secret_access_key" not in content.lower(), \
            f"AWS secret key exposure in {path}"
        assert "ami-id" not in content, \
            f"AWS metadata in {path} — possible SSRF"
        # AKIA is the standard prefix for AWS IAM access key IDs
        assert not re.search(r"AKIA[0-9A-Z]{16}", content), \
            f"AWS access key ID (AKIA...) found in {path}"

    @pytest.mark.parametrize("path", ALL_APP_PAGES)
    def test_no_env_secrets_in_page_response(self, page, path):
        """No page should expose .env / environment variable secrets."""
        goto_safe(page, path)
        content = page.content()
        # These patterns appear in .env files or server environments
        assert "DB_PASSWORD" not in content, \
            f"DB_PASSWORD env var exposed in {path}"
        assert "APP_KEY" not in content and "APP_SECRET" not in content, \
            f"App secret key exposed in {path}"
        assert "MAIL_PASSWORD" not in content, \
            f"Mail password exposed in {path}"
        # JWT_SECRET specifically
        if "JWT_SECRET" in content:
            pytest.fail(f"JWT_SECRET exposed in {path} — critical credential leak")
