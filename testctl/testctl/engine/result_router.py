"""
Result Router — sends run output to configured endpoints.

Each endpoint is a driver identified by `type`. All drivers are opt-in
via config/endpoints.yaml. New drivers (Teams, PagerDuty, GitHub, etc.)
are added by implementing the relevant _<type> method and adding a
config entry — no changes to calling code required.
"""

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from ..models.results import Result, RunResult


class ResultRouter:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        ep_file = config_path / "config" / "endpoints.yaml"
        self.endpoints: list[dict] = []
        if ep_file.exists():
            with open(ep_file) as f:
                self.endpoints = yaml.safe_load(f).get("endpoints", [])

    def route(self, run: RunResult) -> None:
        run_dir = self.config_path / "runs" / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        for ep in self.endpoints:
            if not ep.get("enabled", True):
                continue
            try:
                driver = ep.get("type")
                if driver == "filesystem":
                    self._filesystem(run, ep, run_dir)
                elif driver == "webhook":
                    self._webhook(run, ep)
                elif driver == "jira":
                    self._jira(run, ep)
                elif driver == "html_report":
                    self._html(run, ep, run_dir)
            except Exception as exc:
                print(f"  [warn] reporter '{ep.get('name')}' failed: {exc}")

    # ── filesystem ──────────────────────────────────────────────────────

    def _filesystem(self, run: RunResult, ep: dict, run_dir: Path) -> None:
        base = Path(os.path.expandvars(ep.get("path", str(run_dir))))
        base.mkdir(parents=True, exist_ok=True)

        (base / "metadata.json").write_text(json.dumps({
            "run_id":             run.run_id,
            "mode":               run.mode,
            "modules_tested":     run.modules_tested,
            "git_commit":         run.git_commit,
            "started_at":         run.started_at,
            "finished_at":        run.finished_at,
            "total":              run.total,
            "passed":             run.passed,
            "failed":             run.failed,
            "errors":             run.errors,
            "anonymization_hash": run.anonymization_hash,
        }, indent=2))

        (base / "result.json").write_text(json.dumps(self._serialise(run), indent=2))
        (base / "junit.xml").write_text(self._junit(run))
        print(f"  → filesystem: {base}")

    def _serialise(self, run: RunResult) -> list[dict]:
        return [{
            "test_case":   t.test_case,
            "module":      t.module,
            "result":      t.result.value,
            "duration_ms": t.duration_ms,
            "error":       t.error,
            "timestamp":   t.timestamp,
            "checks": [{
                "check_id": c.check_id,
                "source":   c.source,
                "field":    c.field,
                "expected": c.expected,
                "found":    c.found,
                "result":   c.result.value,
                "note":     c.note,
            } for c in t.checks],
        } for t in run.tests]

    def _junit(self, run: RunResult) -> str:
        suite = ET.Element("testsuite", {
            "name":     f"testctl-{run.run_id}",
            "tests":    str(run.total),
            "failures": str(run.failed),
            "errors":   str(run.errors),
            "time":     str(sum(t.duration_ms for t in run.tests) / 1000),
        })
        for t in run.tests:
            tc = ET.SubElement(suite, "testcase", {
                "name":      t.test_case,
                "classname": t.module,
                "time":      str(t.duration_ms / 1000),
            })
            if t.result == Result.NOK:
                bad = [c for c in t.checks if c.result == Result.NOK]
                msg = "; ".join(
                    f"{c.field}: expected={c.expected!r} found={c.found!r}" for c in bad
                )
                ET.SubElement(tc, "failure", {"message": msg})
            elif t.result == Result.ERROR:
                ET.SubElement(tc, "error", {"message": t.error or "unknown"})
        return ET.tostring(suite, encoding="unicode")

    # ── webhook ─────────────────────────────────────────────────────────

    def _webhook(self, run: RunResult, ep: dict) -> None:
        import requests as req
        url = os.path.expandvars(ep.get("url", ""))
        if not url:
            return
        on = ep.get("on", ["APPROVED", "REJECTED", "NOK", "PASS"])
        label = run.release_decision or ("PASS" if run.failed == 0 else "NOK")
        if label not in on:
            return
        headers = {k: os.path.expandvars(str(v)) for k, v in ep.get("headers", {}).items()}
        req.post(url, json={
            "run_id":     run.run_id,
            "git_commit": run.git_commit,
            "decision":   run.release_decision,
            "total":      run.total,
            "passed":     run.passed,
            "failed":     run.failed,
            "modules":    run.modules_tested,
        }, headers=headers, timeout=10)
        print(f"  → webhook: {url}")

    # ── jira ────────────────────────────────────────────────────────────

    def _jira(self, run: RunResult, ep: dict) -> None:
        import requests as req
        if ep.get("create_on") != "NOK":
            return
        failed = [t for t in run.tests if t.result == Result.NOK]
        if not failed:
            return
        url = ep.get("url", "").rstrip("/")
        token = os.path.expandvars(ep.get("token", ""))
        project = ep.get("project_key", "")
        created = 0
        for t in failed:
            bad = [c for c in t.checks if c.result == Result.NOK]
            desc = "\n".join(
                f"- *{c.field}*: expected `{c.expected}`, found `{c.found}`" for c in bad
            )
            req.post(
                f"{url}/rest/api/2/issue",
                json={"fields": {
                    "project":     {"key": project},
                    "summary":     f"[testctl/{run.run_id}] {t.module}/{t.test_case} failed",
                    "description": desc,
                    "issuetype":   {"name": ep.get("issue_type", "Bug")},
                }},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            created += 1
        print(f"  → jira: {created} issue(s) created")

    # ── html report ─────────────────────────────────────────────────────

    def _html(self, run: RunResult, ep: dict, run_dir: Path) -> None:
        from ..reporters.html_report import HtmlReporter
        raw_path = ep.get("path", str(run_dir / "report.html"))
        out = Path(os.path.expandvars(raw_path).replace("{run_id}", run.run_id))
        HtmlReporter().write(run, out)
        print(f"  → html: {out}")
