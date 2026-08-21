"""Deterministic evaluation of the bounded policy-constraint language.

The language is intentionally small — comparisons and set membership over flat,
declared facts. There is no arbitrary expression evaluation and no callable
input, so a constraint set is safe to accept from a marketplace caller and cheap
to replay. `constraints_pass` is derived here from the observed facts; a caller
that submits the answer instead of the facts is rejected before this runs.
"""

from __future__ import annotations

from typing import Any

from .canonical import canonical_hash
from .models import Constraint

_MISSING = object()

Number = (int, float)


def constraints_hash(constraints: list[Constraint]) -> str:
    return canonical_hash([item.model_dump(mode="json") for item in constraints])


def _numeric(value: Any) -> bool:
    return isinstance(value, Number) and not isinstance(value, bool)


def _compare(op: str, actual: Any, expected: Any) -> tuple[bool, str | None]:
    if op == "eq":
        return actual == expected, None
    if op == "ne":
        return actual != expected, None
    if op in {"lt", "lte", "gt", "gte"}:
        if not _numeric(actual) or not _numeric(expected):
            return False, "TYPE_MISMATCH"
        if op == "lt":
            return actual < expected, None
        if op == "lte":
            return actual <= expected, None
        if op == "gt":
            return actual > expected, None
        return actual >= expected, None
    if op == "in":
        return actual in expected, None
    if op == "not_in":
        return actual not in expected, None
    if op == "subset_of":
        if not isinstance(actual, list):
            return False, "TYPE_MISMATCH"
        return all(item in expected for item in actual), None
    if op in {"starts_with", "ends_with"}:
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False, "TYPE_MISMATCH"
        return (actual.startswith(expected) if op == "starts_with" else actual.endswith(expected)), None
    raise ValueError(f"unsupported constraint op: {op}")


def evaluate_constraints(
    constraints: list[Constraint],
    facts: dict[str, Any],
) -> dict[str, Any]:
    evaluated: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    for constraint in constraints:
        actual = facts.get(constraint.field, _MISSING)
        present = actual is not _MISSING

        if constraint.op == "present":
            satisfied = present and actual not in (None, "", [])
            reason = None if satisfied else "MISSING_FACT"
        elif constraint.op == "absent":
            satisfied = not present or actual in (None, "", [])
            reason = None if satisfied else "UNEXPECTED_FACT"
        elif not present:
            satisfied, reason = False, "MISSING_FACT"
        else:
            satisfied, reason = _compare(constraint.op, actual, constraint.value)
            if not satisfied and reason is None:
                reason = "CONSTRAINT_VIOLATED"

        record = {
            "constraint_id": constraint.constraint_id,
            "field": constraint.field,
            "op": constraint.op,
            "expected": constraint.value,
            "actual": None if actual is _MISSING else actual,
            "fact_present": present,
            "severity": constraint.severity,
            "satisfied": satisfied,
        }
        if reason:
            record["reason"] = reason
        evaluated.append(record)
        if not satisfied:
            violations.append(record)

    blocking = [item for item in violations if item["severity"] == "block"]
    review = [item for item in violations if item["severity"] == "review"]

    result = {
        "constraints_pass": not blocking,
        "requires_review": bool(review),
        "computed_by": "dsg",
        "constraints_total": len(constraints),
        "constraints_satisfied": len(constraints) - len(violations),
        "violations": violations,
        "evaluated": evaluated,
        "constraints_hash": constraints_hash(constraints),
        "facts_hash": canonical_hash(facts),
    }
    result["evaluation_hash"] = canonical_hash(
        {
            "constraints_hash": result["constraints_hash"],
            "facts_hash": result["facts_hash"],
            "constraints_pass": result["constraints_pass"],
            "violations": [item["constraint_id"] for item in violations],
        }
    )
    return result
