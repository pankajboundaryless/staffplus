"""
HTTP performer — drives the application via its HTTP layer.

Auth strategy: POST to /auth/callback with a crafted JWT. The PHP app
validates the JWT, runs syncUser(), and sets a session cookie. All
subsequent requests carry that cookie automatically via requests.Session.

CSRF: the app stores the token in $_SESSION['_csrf_token'] and renders it
as <input name="_csrf">. The performer extracts it from the last GET
response and auto-injects it into POST bodies unless `skip_csrf: true`
is set on the step.
"""

import re
import time
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

from ..engine.auth_helper import generate
from ..models.results import CheckResult, Result, TestResult
from .base import BasePerformer


class HttpPerformer(BasePerformer):
    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url: str = config.get("app", {}).get("base_url", "").rstrip("/")
        self.auth_cfg: dict = config.get("auth", {})
        self.session = requests.Session()
        self._last_html: str = ""
        self._last_location: str = ""
        self._logged_in_as: Optional[str] = None

    def setup(self) -> None:
        self.session = requests.Session()
        self.context = {}
        self._last_html = ""
        self._last_location = ""
        self._logged_in_as = None

    def teardown(self) -> None:
        self.session.close()

    # ── internal helpers ────────────────────────────────────────────────

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _resolve(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        for k, v in self.context.items():
            value = value.replace(f"{{{{ {k} }}}}", str(v))
        return value

    def _resolve_dict(self, d: dict) -> dict:
        return {k: self._resolve(v) for k, v in d.items()}

    def _csrf_from(self, html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        el = soup.find("input", {"name": "_csrf"})
        if el:
            return el.get("value")
        meta = soup.find("meta", {"name": "csrf-token"})
        if meta:
            return meta.get("content")
        return None

    def _extract(self, html: str, extractions: list[dict]) -> None:
        soup = BeautifulSoup(html, "html.parser")
        for ex in extractions:
            name = ex["name"]
            selector = ex.get("selector", "")
            attr = ex.get("attribute", "text")
            regex = ex.get("regex")
            source = ex.get("from", "body")
            search_text = self._last_location if source == "location_header" else html
            if regex:
                m = re.search(regex, search_text)
                if m:
                    self.context[name] = m.group(1) if m.lastindex else m.group(0)
            elif selector:
                el = soup.select_one(selector)
                if el:
                    self.context[name] = (
                        el.get_text(strip=True) if attr == "text" else el.get(attr, "")
                    )

    # ── authentication ──────────────────────────────────────────────────

    def _login(self, role: str) -> None:
        if self._logged_in_as == role:
            return
        users = self.auth_cfg.get("test_users", {})
        user_cfg = users.get(role)
        if not user_cfg:
            raise RuntimeError(f"No test user configured for role '{role}'")

        token = generate(
            secret=self.auth_cfg["jwt_secret"],
            uid=user_cfg["auth_uid"],
            email=user_cfg["email"],
            name=user_cfg.get("name", user_cfg["email"]),
            role=user_cfg.get("role", role),
            roles=user_cfg.get("roles", [role]),
            aud=self.auth_cfg["jwt_aud"],
        )
        callback_url = self.auth_cfg.get("callback_url", "/auth/callback")
        resp = self.session.post(
            self._url(callback_url),
            data={"token": token},
            allow_redirects=True,
            timeout=15,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Auth callback returned {resp.status_code}")
        self._last_html = resp.text
        self._logged_in_as = role

    # ── main run ────────────────────────────────────────────────────────

    def run(self, test_case: dict) -> TestResult:
        start = time.monotonic()
        checks: list[CheckResult] = []
        error: Optional[str] = None
        overall = Result.OK

        try:
            auth = test_case.get("auth", {})
            if auth:
                self._login(auth.get("role", "admin"))

            for step in test_case.get("steps", []):
                method = step.get("action", "GET").upper()
                path = self._resolve(step.get("path", ""))
                url = self._url(path)
                follow = step.get("follow_redirect", True)
                skip_csrf = step.get("skip_csrf", False)

                if method == "GET":
                    resp = self.session.get(url, allow_redirects=follow, timeout=15)
                    self._last_html = resp.text
                    self._last_location = resp.headers.get("Location", "")
                    if "extract" in step:
                        self._extract(resp.text, step["extract"])
                else:
                    body = self._resolve_dict(step.get("body", {}))
                    if not skip_csrf and "_csrf" not in body:
                        csrf = self._csrf_from(self._last_html)
                        if not csrf:
                            get_resp = self.session.get(url, timeout=15)
                            self._last_html = get_resp.text
                            csrf = self._csrf_from(get_resp.text)
                        if csrf:
                            body["_csrf"] = csrf
                    resp = self.session.request(
                        method, url, data=body,
                        allow_redirects=follow, timeout=15,
                    )
                    self._last_html = resp.text
                    self._last_location = resp.headers.get("Location", "")
                    if "extract" in step:
                        self._extract(resp.text, step["extract"])

                expected_status = step.get("expect_status")
                if expected_status is not None:
                    ok = resp.status_code == expected_status
                    checks.append(CheckResult(
                        check_id=f"{method}_{path}_status",
                        source="http",
                        field="status_code",
                        expected=expected_status,
                        found=resp.status_code,
                        result=Result.OK if ok else Result.NOK,
                    ))
                    if not ok:
                        overall = Result.NOK

                # Inline step-level validations
                for sv in step.get("validations", []):
                    v_type = sv.get("type", "")
                    v_value = sv.get("value", "")
                    negate = sv.get("negate", False)
                    check_id = f"{method}_{path}_{v_type}"
                    if v_type in ("text_contains", "text"):
                        found = v_value in resp.text
                        ok = (not found) if negate else found
                        checks.append(CheckResult(
                            check_id=check_id,
                            source="http",
                            field=v_type,
                            expected=f"{'not ' if negate else ''}contains:{v_value}",
                            found=found,
                            result=Result.OK if ok else Result.NOK,
                        ))
                        if not ok:
                            overall = Result.NOK

            # HTTP validations (source: http)
            for val in test_case.get("validations", []):
                if val.get("source") != "http":
                    continue
                path = self._resolve(val.get("path", ""))
                resp = self.session.get(self._url(path), allow_redirects=True, timeout=15)
                soup = BeautifulSoup(resp.text, "html.parser")
                selector = val.get("selector", "")
                for key, expected_val in val.get("expect", {}).items():
                    check_id = f"http_{selector}_{key}"
                    if key == "count_gte":
                        found_count = len(soup.select(selector))
                        ok = found_count >= int(expected_val)
                        c = CheckResult(check_id=check_id, source="http",
                                        field="element_count",
                                        expected=f">={expected_val}", found=found_count,
                                        result=Result.OK if ok else Result.NOK)
                    elif key == "count_eq":
                        found_count = len(soup.select(selector))
                        ok = found_count == int(expected_val)
                        c = CheckResult(check_id=check_id, source="http",
                                        field="element_count",
                                        expected=expected_val, found=found_count,
                                        result=Result.OK if ok else Result.NOK)
                    elif key == "text":
                        el = soup.select_one(selector)
                        found_text = el.get_text(strip=True) if el else None
                        ok = found_text == expected_val
                        c = CheckResult(check_id=check_id, source="http",
                                        field="element_text",
                                        expected=expected_val, found=found_text,
                                        result=Result.OK if ok else Result.NOK)
                    elif key == "text_contains":
                        el = soup.select_one(selector)
                        found_text = el.get_text(strip=True) if el else ""
                        ok = str(expected_val) in found_text
                        c = CheckResult(check_id=check_id, source="http",
                                        field="element_text_contains",
                                        expected=f"contains:{expected_val}",
                                        found=found_text,
                                        result=Result.OK if ok else Result.NOK)
                    elif key == "exists":
                        el = soup.select_one(selector)
                        ok = (el is not None) == bool(expected_val)
                        c = CheckResult(check_id=check_id, source="http",
                                        field="element_exists",
                                        expected=expected_val, found=el is not None,
                                        result=Result.OK if ok else Result.NOK)
                    else:
                        continue
                    checks.append(c)
                    if c.result == Result.NOK:
                        overall = Result.NOK

        except Exception as exc:
            error = str(exc)
            overall = Result.ERROR

        return TestResult(
            test_case=test_case["test_case"],
            module=test_case["module"],
            result=overall,
            duration_ms=int((time.monotonic() - start) * 1000),
            checks=checks,
            error=error,
        )
