from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class Result(str, Enum):
    OK = "OK"
    NOK = "NOK"
    SKIP = "SKIP"
    ERROR = "ERROR"


@dataclass
class CheckResult:
    check_id: str
    source: str        # "http", "database"
    field: str
    expected: Any
    found: Any
    result: Result
    note: str = ""


@dataclass
class TestResult:
    test_case: str
    module: str
    result: Result
    duration_ms: int
    checks: list[CheckResult] = field(default_factory=list)
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


@dataclass
class RunResult:
    run_id: str
    mode: str
    modules_tested: list[str]
    git_commit: str
    started_at: str
    finished_at: str = ""
    tests: list[TestResult] = field(default_factory=list)
    anonymization_hash: str = ""
    release_decision: Optional[str] = None

    @property
    def total(self) -> int:
        return len(self.tests)

    @property
    def passed(self) -> int:
        return sum(1 for t in self.tests if t.result == Result.OK)

    @property
    def failed(self) -> int:
        return sum(1 for t in self.tests if t.result == Result.NOK)

    @property
    def errors(self) -> int:
        return sum(1 for t in self.tests if t.result == Result.ERROR)

    @property
    def skipped(self) -> int:
        return sum(1 for t in self.tests if t.result == Result.SKIP)
