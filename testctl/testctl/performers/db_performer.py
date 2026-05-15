"""
DB performer — runs direct SQL assertions against the test database.

Validates expected column values after HTTP steps have been executed.
Context variables from the HTTP performer (e.g. {{ project_id }}) are
shared into this performer's context dict by the runner before each call.
"""

import time
from typing import Any, Optional

from ..engine.validator import compare
from ..models.results import CheckResult, Result, TestResult
from .base import BasePerformer


class DbPerformer(BasePerformer):
    def __init__(self, config: dict):
        super().__init__(config)
        self._conn = None

    def setup(self) -> None:
        db = self.config.get("database", {})
        try:
            import mariadb
            self._conn = mariadb.connect(
                host=db.get("host", "localhost"),
                port=int(db.get("port", 3306)),
                user=db["user"],
                password=db["password"],
                database=db["name"],
            )
        except Exception as exc:
            print(f"  [warn] DB performer not connected: {exc}")
            self._conn = None

    def teardown(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def execute_sql(self, sql: str) -> None:
        if not self._conn:
            return
        cursor = self._conn.cursor()
        cursor.execute(sql)
        self._conn.commit()

    def _resolve(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        for k, v in self.context.items():
            value = value.replace(f"{{{{ {k} }}}}", str(v))
        return value

    def run(self, test_case: dict) -> TestResult:
        db_validations = [v for v in test_case.get("validations", []) if v.get("source") == "database"]
        if not db_validations:
            return TestResult(
                test_case=test_case["test_case"],
                module=test_case["module"],
                result=Result.OK,
                duration_ms=0,
                checks=[],
            )

        if not self._conn:
            return TestResult(
                test_case=test_case["test_case"],
                module=test_case["module"],
                result=Result.SKIP,
                duration_ms=0,
                checks=[],
                error="DB performer not connected — skipping database checks",
            )

        start = time.monotonic()
        checks: list[CheckResult] = []
        error: Optional[str] = None
        overall = Result.OK

        try:
            for val in db_validations:
                table = val["table"]
                lookup = {k: self._resolve(v) for k, v in val.get("lookup", {}).items()}
                expect = val.get("expect", {})
                operators = val.get("operators", {})
                order_by = val.get("order_by", "id DESC")
                limit = val.get("limit", 1)

                where_clause = " AND ".join(f"`{k}` = ?" for k in lookup) if lookup else "1=1"
                query = f"SELECT * FROM `{table}` WHERE {where_clause} ORDER BY {order_by} LIMIT {limit}"
                values = list(lookup.values())

                cursor = self._conn.cursor(dictionary=True)
                cursor.execute(query, values)
                row = cursor.fetchone()

                expect_absent = val.get("expect_absent", False)

                if row is None:
                    checks.append(CheckResult(
                        check_id=f"db_{table}_exists",
                        source="database",
                        field="row_exists",
                        expected="absent" if expect_absent else True,
                        found="absent",
                        result=Result.OK if expect_absent else Result.NOK,
                        note=f"No row in `{table}` matching {lookup}" if not expect_absent else "",
                    ))
                    if not expect_absent:
                        overall = Result.NOK
                    continue

                if expect_absent:
                    checks.append(CheckResult(
                        check_id=f"db_{table}_absent",
                        source="database",
                        field="row_absent",
                        expected="absent",
                        found="present",
                        result=Result.NOK,
                        note=f"Row found in `{table}` but should not exist: {lookup}",
                    ))
                    overall = Result.NOK
                    continue

                if not expect:
                    checks.append(CheckResult(
                        check_id=f"db_{table}_exists",
                        source="database",
                        field="row_exists",
                        expected=True,
                        found=True,
                        result=Result.OK,
                    ))

                for col, expected_val in expect.items():
                    found_val = row.get(col)
                    op = operators.get(col, "eq")
                    ok = compare(expected_val, found_val, op)
                    checks.append(CheckResult(
                        check_id=f"db_{table}_{col}",
                        source="database",
                        field=col,
                        expected=expected_val,
                        found=found_val,
                        result=Result.OK if ok else Result.NOK,
                    ))
                    if not ok:
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
