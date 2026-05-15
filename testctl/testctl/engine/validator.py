from typing import Any

from ..models.results import CheckResult, Result


def compare(expected: Any, found: Any, op: str = "eq") -> bool:
    if op == "eq":
        if isinstance(expected, bool):
            return bool(found) == expected
        if isinstance(expected, (int, float)) and found is not None:
            try:
                return float(found) == float(expected)
            except (ValueError, TypeError):
                return False
        return str(found) == str(expected)
    if op == "gte":
        try:
            return float(found) >= float(expected)
        except (ValueError, TypeError):
            return False
    if op == "lte":
        try:
            return float(found) <= float(expected)
        except (ValueError, TypeError):
            return False
    if op == "contains":
        return str(expected) in str(found)
    if op == "not_null":
        return found is not None
    if op == "is_null":
        return found is None
    return False


def make_check(
    check_id: str,
    source: str,
    field: str,
    expected: Any,
    found: Any,
    op: str = "eq",
    note: str = "",
) -> CheckResult:
    ok = compare(expected, found, op)
    return CheckResult(
        check_id=check_id,
        source=source,
        field=field,
        expected=expected,
        found=found,
        result=Result.OK if ok else Result.NOK,
        note=note,
    )
