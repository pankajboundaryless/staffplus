"""
conftest_report.py — Structured Schema Report Plugin
═════════════════════════════════════════════════════
Generates a numbered, URL-annotated JSON + HTML results schema after every run.

Output files
────────────
  reports/results_schema.json   — machine-readable schema (for CI/integrations)
  reports/results_schema.html   — human-readable numbered test table

Schema per test
───────────────
  {
    "number":      1,
    "id":          "test_01_login.py::TestLogin::test_login_page_loads",
    "file":        "test_01_login.py",
    "class":       "TestLogin",
    "name":        "test_login_page_loads",
    "url":         "/public/login_form.php",      ← parsed from docstring "URL:" line
    "description": "Login page renders correctly", ← first sentence of docstring
    "status":      "PASSED",                       ← PASSED / FAILED / SKIPPED / ERROR
    "duration_s":  0.42,
    "error":       null                            ← failure message if failed
  }

URL extraction
──────────────
Each test docstring should have a line starting with "URL:" e.g.:
    \"\"\"
    URL: /dashboard
    Checks the dashboard loads correctly.
    \"\"\"
If no URL: line exists the plugin scans the docstring for the first path
that looks like /something.
"""

import json
import pathlib
import re
import time
import textwrap
from typing import Optional

import pytest

# ── storage for the run ───────────────────────────────────────────────────────
_results: list[dict] = []
_counter = 0


def _extract_url(docstring: Optional[str]) -> str:
    """Pull URL from docstring 'URL: /path' line or first /path-looking string."""
    if not docstring:
        return "—"
    # Explicit "URL: /foo" line
    m = re.search(r"URL:\s*(\S+)", docstring)
    if m:
        return m.group(1)
    # Fallback: first /word pattern
    m = re.search(r"(/[a-z][a-z0-9/_\-]*)", docstring)
    if m:
        return m.group(1)
    return "—"


def _extract_description(docstring: Optional[str]) -> str:
    """Return first meaningful sentence from docstring (skip 'URL:' lines)."""
    if not docstring:
        return "—"
    lines = textwrap.dedent(docstring).strip().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("URL:") or line.startswith("═"):
            continue
        # Return first real sentence (up to 100 chars)
        return line[:100]
    return "—"


# ── pytest hooks ──────────────────────────────────────────────────────────────

def pytest_runtest_logreport(report):
    """Called after each test phase (setup / call / teardown)."""
    global _counter
    # Only record the call phase (the actual test body)
    if report.when != "call":
        # Handle skips that happen at setup phase
        if report.when == "setup" and report.skipped:
            pass
        else:
            return

    _counter += 1

    # Get docstring from the test item stored in report
    doc = getattr(report, "_doc", None)
    url = getattr(report, "_url", "—")
    desc = getattr(report, "_desc", "—")

    if report.passed:
        status = "PASSED"
        error = None
    elif report.failed:
        status = "FAILED"
        error = str(report.longrepr).split("\n")[-1][:200] if report.longrepr else None
    else:
        status = "SKIPPED"
        error = None

    parts = report.nodeid.split("::")
    file_  = parts[0] if len(parts) > 0 else "—"
    class_ = parts[1] if len(parts) > 2 else "—"
    name_  = parts[-1]

    _results.append({
        "number":      _counter,
        "id":          report.nodeid,
        "file":        file_,
        "class":       class_,
        "name":        name_,
        "url":         url,
        "description": desc,
        "status":      status,
        "duration_s":  round(getattr(report, "duration", 0), 3),
        "error":       error,
    })




@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    doc = item.function.__doc__ or ""
    report._doc  = doc
    report._url  = _extract_url(doc)
    report._desc = _extract_description(doc)


def pytest_sessionfinish(session, exitstatus):
    """Write schema files after the full run."""
    if not _results:
        return

    report_dir = pathlib.Path(__file__).parent / "reports"
    report_dir.mkdir(exist_ok=True)

    # ── Totals ────────────────────────────────────────────────────────────────
    total   = len(_results)
    passed  = sum(1 for r in _results if r["status"] == "PASSED")
    failed  = sum(1 for r in _results if r["status"] == "FAILED")
    skipped = sum(1 for r in _results if r["status"] == "SKIPPED")

    summary = {
        "run_at":  time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "base_url": "https://robomon.boundaryless.com/test/timetracker/public",
        "browser":  "chromium",
        "totals": {
            "total":   total,
            "passed":  passed,
            "failed":  failed,
            "skipped": skipped,
        },
        "tests": _results,
    }

    # ── JSON schema ───────────────────────────────────────────────────────────
    json_path = report_dir / "results_schema.json"
    json_path.write_text(json.dumps(summary, indent=2))

    # ── HTML schema ───────────────────────────────────────────────────────────
    STATUS_COLOUR = {
        "PASSED":  ("#f0fdf4", "#166534", "✅"),
        "FAILED":  ("#fef2f2", "#991b1b", "❌"),
        "SKIPPED": ("#fefce8", "#854d0e", "⏭️"),
    }

    rows_html = ""
    for r in _results:
        bg, fg, icon = STATUS_COLOUR.get(r["status"], ("#fff", "#000", "?"))
        err = f'<br><span style="color:#dc2626;font-size:.75rem">{r["error"]}</span>' if r["error"] else ""
        rows_html += f"""
        <tr style="background:{bg}">
          <td style="color:#64748b;font-size:.8rem;text-align:center">{r['number']:03d}</td>
          <td style="font-family:monospace;font-size:.78rem">{r['url']}</td>
          <td style="font-size:.82rem">{r['description']}{err}</td>
          <td style="font-size:.78rem;color:#475569">{r['file']}<br><span style="color:#94a3b8">{r['class']}</span></td>
          <td style="text-align:center;font-weight:600;color:{fg}">{icon} {r['status']}</td>
          <td style="text-align:right;color:#94a3b8;font-size:.78rem">{r['duration_s']}s</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>StaffPlus E2E Test Results</title>
<style>
  body {{ font-family: Inter, system-ui, sans-serif; margin: 0; background: #f8fafc; color: #1e293b; }}
  .header {{ background: #0f172a; color: #fff; padding: 32px 40px; }}
  .header h1 {{ margin: 0 0 4px; font-size: 1.5rem; }}
  .header p  {{ margin: 0; color: #94a3b8; font-size: .9rem; }}
  .stats {{ display: flex; gap: 16px; padding: 24px 40px; background: #fff; border-bottom: 1px solid #e2e8f0; }}
  .stat {{ text-align: center; padding: 16px 28px; border-radius: 10px; }}
  .stat .n {{ font-size: 2.2rem; font-weight: 700; line-height: 1; }}
  .stat .l {{ font-size: .78rem; color: #64748b; margin-top: 4px; text-transform: uppercase; letter-spacing: .05em; }}
  .total   {{ background: #f1f5f9; }}
  .pass    {{ background: #f0fdf4; color: #166534; }}
  .fail    {{ background: #fef2f2; color: #991b1b; }}
  .skip    {{ background: #fefce8; color: #854d0e; }}
  table  {{ width: 100%; border-collapse: collapse; font-size: .85rem; }}
  th     {{ background: #0f172a; color: #94a3b8; font-size: .72rem; text-transform: uppercase;
             letter-spacing: .06em; padding: 10px 12px; text-align: left; position: sticky; top: 0; }}
  td     {{ padding: 9px 12px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }}
  .wrap  {{ padding: 0 40px 40px; }}
  .meta  {{ padding: 12px 40px; font-size: .78rem; color: #64748b; background:#fff; border-bottom:1px solid #e2e8f0; }}
</style>
</head>
<body>
<div class="header">
  <h1>🎭 StaffPlus — Playwright E2E Test Results</h1>
  <p>Generated: {summary['run_at']} · Browser: {summary['browser']} (desktop 1280×800)</p>
</div>
<div class="stats">
  <div class="stat total"><div class="n">{total}</div><div class="l">Total</div></div>
  <div class="stat pass" ><div class="n">{passed}</div><div class="l">Passed</div></div>
  <div class="stat fail" ><div class="n">{failed}</div><div class="l">Failed</div></div>
  <div class="stat skip" ><div class="n">{skipped}</div><div class="l">Skipped</div></div>
</div>
<div class="meta">
  Base URL: <code>{summary['base_url']}</code> &nbsp;|&nbsp;
  Pass rate: <strong>{round(passed/total*100)}%</strong>
</div>
<div class="wrap">
<table>
  <thead>
    <tr>
      <th style="width:46px">#</th>
      <th style="width:160px">URL</th>
      <th>Description</th>
      <th style="width:200px">File · Class</th>
      <th style="width:90px">Status</th>
      <th style="width:60px">Time</th>
    </tr>
  </thead>
  <tbody>
    {rows_html}
  </tbody>
</table>
</div>
</body>
</html>"""

    html_path = report_dir / "results_schema.html"
    html_path.write_text(html)

    # ── Console summary ───────────────────────────────────────────────────────
    print(f"""
╔══════════════════════════════════════════════════════╗
║         Playwright Browser Tests (E2E)               ║
╠══════════════════════════════════════════════════════╣
║  {total:>4}  Total                                       ║
║  {passed:>4}  Passed   ✅                                ║
║  {failed:>4}  Failed   ❌                                ║
║  {skipped:>4}  Skipped  ⏭️                                ║
╠══════════════════════════════════════════════════════╣
║  Pass rate: {round(passed/total*100):>3}%                                  ║
╠══════════════════════════════════════════════════════╣
║  Schema → reports/results_schema.json                ║
║  Report → reports/results_schema.html                ║
╚══════════════════════════════════════════════════════╝""")
