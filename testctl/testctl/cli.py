import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
import yaml

from .engine.data_engine import DataEngine
from .engine.release_gate import ReleaseGate
from .engine.result_router import ResultRouter
from .engine.runner import Runner
from .engine.selector import TestSelector
from .models.results import RunResult


# ── config helpers ──────────────────────────────────────────────────────

def _load_config(config_path: Path) -> dict:
    p = config_path / "config" / "testctl.yaml"
    if not p.exists():
        raise FileNotFoundError(f"testctl.yaml not found in {config_path / 'config'}")
    with open(p) as f:
        raw = yaml.safe_load(f)
    return _expand_env(raw)


def _expand_env(obj):
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    if isinstance(obj, str):
        return os.path.expandvars(obj)
    return obj


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _run_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def _header(msg: str) -> None:
    click.echo(f"\n{'=' * 60}\n  {msg}\n{'=' * 60}\n")


# ── run command ─────────────────────────────────────────────────────────

@click.group()
def cli():
    """Boundaryless Test Control Engine"""


@cli.command()
@click.option("--changed",  "mode", flag_value="changed",  help="Test only changed modules (git diff)")
@click.option("--impacted", "mode", flag_value="impacted", help="Test changed + downstream modules")
@click.option("--full",     "mode", flag_value="full", default=True, help="Full test suite (default)")
@click.option("--modules",  default=None, help="Comma-separated modules, e.g. time,invoicing")
@click.option("--source",   default=None, type=click.Path(exists=True), help="SQL dump file to use as data source")
@click.option("--skip-anonymize", is_flag=True, help="Load source dump as-is without anonymizing")
@click.option("--no-provision",   is_flag=True, help="Skip DB provisioning; requires --db")
@click.option("--db",       default=None, help="Existing test DB name (use with --no-provision)")
def run(mode, modules, source, skip_anonymize, no_provision, db):
    """Run the test suite."""
    config_path = Path.cwd()
    config = _load_config(config_path)
    run_id = _run_id()

    module_list = [m.strip() for m in modules.split(",")] if modules else None
    if module_list:
        mode = "modules"

    _header(f"testctl run [{mode.upper()}]   run_id: {run_id}")

    selector = TestSelector(config_path)
    test_files = selector.select(mode, module_list)
    tested_modules = sorted({f.parent.name for f in test_files})
    print(f"  {len(test_files)} test file(s) across {len(tested_modules)} module(s): {', '.join(tested_modules) or 'none'}\n")

    anon_hash = ""
    test_db = db
    data_engine: Optional[DataEngine] = None

    if not no_provision:
        print("  Provisioning test database...")
        source_path = Path(source) if source else None
        data_engine = DataEngine(
            config_path, config["database"],
            config_path / "config" / "anonymization.yaml",
        )
        if skip_anonymize and source_path:
            test_db = f"testctl_run_{run_id}"
            data_engine._create_db(test_db)
            data_engine._import_dump(test_db, source_path)
            anon_hash = "skipped"
        else:
            test_db, anon_hash = data_engine.provision(run_id, source_path)
        print(f"  Test DB: {test_db}\n")

    if not test_db:
        raise click.UsageError("No test DB available. Either allow provisioning or pass --db <name>.")

    run_obj = RunResult(
        run_id=run_id,
        mode=mode,
        modules_tested=tested_modules,
        git_commit=_git_commit(),
        started_at=datetime.utcnow().isoformat() + "Z",
        anonymization_hash=anon_hash,
    )

    print("  Running tests...\n")
    Runner(config_path, config).run(test_files, run_obj, test_db)
    run_obj.finished_at = datetime.utcnow().isoformat() + "Z"

    gate = ReleaseGate(config_path, config.get("release_gate", {}))
    decision, reason = gate.evaluate(run_obj)
    gate.write_decision(run_obj, decision, reason)

    print("\n  Routing results...")
    ResultRouter(config_path).route(run_obj)

    if data_engine and test_db:
        data_engine.destroy(test_db)
        print(f"  Test DB destroyed: {test_db}")

    _header(
        f"{'✓ APPROVED' if decision == 'APPROVED' else '✗ REJECTED'}"
        f"  |  {run_obj.passed}/{run_obj.total} passed"
        f"  |  run: {run_id}"
    )
    raise SystemExit(0 if decision == "APPROVED" else 1)


# ── gate commands ───────────────────────────────────────────────────────

@cli.group()
def gate():
    """Manage release gate decisions."""


@gate.command("show")
@click.argument("run_id")
def gate_show(run_id):
    """Show the release decision for a completed run."""
    f = Path.cwd() / "runs" / run_id / "release_decision.json"
    if not f.exists():
        click.echo(f"No decision found for run {run_id}", err=True)
        raise SystemExit(1)
    click.echo(f.read_text())


@gate.command("approve")
@click.argument("run_id")
@click.option("--reason", required=True, help="Reason for manual override")
def gate_approve(run_id, reason):
    """Manually approve a previously rejected run."""
    f = Path.cwd() / "runs" / run_id / "release_decision.json"
    if not f.exists():
        click.echo(f"No decision found for run {run_id}", err=True)
        raise SystemExit(1)
    rec = json.loads(f.read_text())
    rec.update({
        "decision":        "APPROVED",
        "overridden":      True,
        "override_reason": reason,
        "approved_by":     "manual",
    })
    f.write_text(json.dumps(rec, indent=2))
    click.echo(f"Run {run_id} manually approved: {reason}")


# ── runs commands ───────────────────────────────────────────────────────

@cli.group()
def runs():
    """List and inspect test runs."""


@runs.command("list")
@click.option("--limit", default=10, show_default=True)
def runs_list(limit):
    """List the most recent test runs."""
    runs_dir = Path.cwd() / "runs"
    if not runs_dir.exists():
        click.echo("No runs yet.")
        return
    dirs = sorted([d for d in runs_dir.iterdir() if d.is_dir()], reverse=True)[:limit]
    click.echo(f"\n{'Run ID':<22}  {'Decision':<12}  {'Pass':<6}  {'Fail':<6}  Commit")
    click.echo("-" * 62)
    for d in dirs:
        df = d / "release_decision.json"
        if df.exists():
            r = json.loads(df.read_text())
            s = r.get("summary", {})
            click.echo(
                f"{d.name:<22}  {r.get('decision', '?'):<12}  "
                f"{s.get('passed', '?'):<6}  {s.get('failed', '?'):<6}  "
                f"{r.get('git_commit', '?')}"
            )


@runs.command("show")
@click.argument("run_id")
@click.option("--test",   default=None, help="Filter to a specific test_case name")
@click.option("--failed", is_flag=True,  help="Show only failed tests")
def runs_show(run_id, test, failed):
    """Show detailed results for a run."""
    f = Path.cwd() / "runs" / run_id / "result.json"
    if not f.exists():
        click.echo(f"No results for run {run_id}", err=True)
        raise SystemExit(1)
    results = json.loads(f.read_text())
    if test:
        results = [r for r in results if r["test_case"] == test]
    if failed:
        results = [r for r in results if r["result"] == "NOK"]
    click.echo(json.dumps(results, indent=2))


def main():
    cli()
