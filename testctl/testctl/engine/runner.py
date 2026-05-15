"""
Runner — orchestrates test file execution across performers.

For each test YAML file:
  1. Run setup_sql statements (if any)
  2. Execute HTTP steps + HTTP validations via HttpPerformer
  3. Share HTTP context into DbPerformer
  4. Execute DB validations via DbPerformer
  5. Merge results, re-evaluate overall pass/fail
  6. Run teardown_sql statements (if any)
"""

from pathlib import Path

import yaml

from ..models.results import Result, RunResult
from ..performers.db_performer import DbPerformer
from ..performers.http_performer import HttpPerformer


class Runner:
    def __init__(self, config_path: Path, config: dict):
        self.config_path = config_path
        self.config = config

    def run(self, test_files: list[Path], run: RunResult, test_db: str) -> None:
        db_cfg = {**self.config.get("database", {}), "name": test_db}
        combined_cfg = {**self.config, "database": db_cfg}

        http = HttpPerformer(combined_cfg)
        db = DbPerformer({"database": db_cfg})
        http.setup()
        db.setup()

        try:
            for path in test_files:
                with open(path) as f:
                    test_case = yaml.safe_load(f)

                # Setup SQL (e.g. seed a known project/person for this test)
                for sql in test_case.get("setup_sql", []):
                    db.execute_sql(sql)

                # HTTP steps + HTTP validations
                http_result = http.run(test_case)

                # Share context variables (e.g. extracted IDs) into DB performer
                db.context = dict(http.context)

                # DB validations
                db_result = db.run(test_case)
                http_result.checks.extend(db_result.checks)

                # Re-evaluate overall result
                if any(c.result == Result.NOK for c in http_result.checks):
                    http_result.result = Result.NOK
                elif db_result.result in (Result.ERROR, Result.SKIP) and http_result.result == Result.OK:
                    http_result.result = db_result.result
                    http_result.error = db_result.error

                run.tests.append(http_result)

                icon = {
                    Result.OK:    "✓",
                    Result.NOK:   "✗",
                    Result.SKIP:  "⊘",
                    Result.ERROR: "!",
                }.get(http_result.result, "?")
                print(f"  {icon}  [{http_result.module}] {http_result.test_case}  ({http_result.duration_ms}ms)")

                # Teardown SQL (always runs, even if test failed)
                for sql in test_case.get("teardown_sql", []):
                    try:
                        db.execute_sql(sql)
                    except Exception as exc:
                        print(f"    [warn] teardown_sql failed: {exc}")

        finally:
            db.teardown()
            http.teardown()
