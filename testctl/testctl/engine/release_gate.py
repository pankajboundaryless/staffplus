import json
from datetime import datetime
from pathlib import Path

from ..models.results import Result, RunResult


class ReleaseGate:
    def __init__(self, config_path: Path, gate_config: dict):
        self.config_path = config_path
        self.gate_config = gate_config

    def evaluate(self, run: RunResult) -> tuple[str, str]:
        critical = set(self.gate_config.get("critical_modules", []))
        for test in run.tests:
            if test.module in critical and test.result in (Result.NOK, Result.ERROR):
                return "REJECTED", f"Critical module '{test.module}' / '{test.test_case}' failed"
        threshold = self.gate_config.get("max_failures", 0)
        if run.failed > threshold:
            return "REJECTED", f"{run.failed} failure(s) exceed threshold of {threshold}"
        return "APPROVED", f"All {run.total} test(s) passed"

    def write_decision(
        self,
        run: RunResult,
        decision: str,
        reason: str,
        override: bool = False,
        override_reason: str = "",
    ) -> None:
        run_dir = self.config_path / "runs" / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "run_id":          run.run_id,
            "git_commit":      run.git_commit,
            "decision":        decision,
            "reason":          reason,
            "overridden":      override,
            "override_reason": override_reason,
            "approved_by":     "manual" if override else "testctl-auto",
            "timestamp":       datetime.utcnow().isoformat() + "Z",
            "summary": {
                "total":   run.total,
                "passed":  run.passed,
                "failed":  run.failed,
                "errors":  run.errors,
                "skipped": run.skipped,
            },
        }
        (run_dir / "release_decision.json").write_text(json.dumps(record, indent=2))
        run.release_decision = decision
