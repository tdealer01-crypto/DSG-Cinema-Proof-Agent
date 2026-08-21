"""Independent plan-alignment computation.

DSG does not ask whether the agent believes it stayed inside the plan. It takes
the approved plan and the observed action trace and decides for itself, action
by action. The result is reproducible: same plan plus same trace always yields
the same findings and the same `alignment_hash`.
"""

from __future__ import annotations

from typing import Any

from .canonical import canonical_hash
from .models import ObservedAction, PlanDocument

BLOCKING_CODES = frozenset(
    {"OUT_OF_PLAN_ACTION", "PARAMETER_MISMATCH", "UNKNOWN_STEP_ID", "STEP_REPEATED"}
)


def plan_hash(plan: PlanDocument) -> str:
    """Hash the plan exactly as DSG canonicalised it, ignoring any agent claim."""
    return canonical_hash(plan.model_dump(mode="json"))


def action_trace_hash(actions: list[ObservedAction]) -> str:
    return canonical_hash([action.model_dump(mode="json") for action in actions])


def _finding(code: str, severity: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "detail": detail, **extra}


def evaluate_alignment(plan: PlanDocument, actions: list[ObservedAction]) -> dict[str, Any]:
    steps = {step.step_id: step for step in plan.steps}
    consumed: dict[str, int] = {}
    findings: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []

    for index, action in enumerate(actions):
        step = None
        if action.step_id is not None:
            step = steps.get(action.step_id)
            if step is None:
                findings.append(
                    _finding(
                        "UNKNOWN_STEP_ID",
                        "block",
                        f"action references step_id '{action.step_id}', which is not in the approved plan",
                        action_index=index,
                    )
                )
                continue
        else:
            for candidate in plan.steps:
                if (
                    candidate.action == action.action
                    and candidate.target == action.target
                    and candidate.step_id not in consumed
                ):
                    step = candidate
                    break
            if step is None:
                findings.append(
                    _finding(
                        "OUT_OF_PLAN_ACTION",
                        "block",
                        f"action '{action.action}' on '{action.target}' matches no unconsumed approved step",
                        action_index=index,
                    )
                )
                continue

        if step.step_id in consumed:
            findings.append(
                _finding(
                    "STEP_REPEATED",
                    "block",
                    f"step '{step.step_id}' was executed more than once",
                    action_index=index,
                    step_id=step.step_id,
                )
            )
            continue

        if step.action != action.action or step.target != action.target:
            findings.append(
                _finding(
                    "OUT_OF_PLAN_ACTION",
                    "block",
                    (
                        f"step '{step.step_id}' approves '{step.action}' on '{step.target}' "
                        f"but the agent ran '{action.action}' on '{action.target}'"
                    ),
                    action_index=index,
                    step_id=step.step_id,
                )
            )
            continue

        mismatched = [
            key
            for key, value in step.parameters.items()
            if action.parameters.get(key) != value
        ]
        if mismatched:
            findings.append(
                _finding(
                    "PARAMETER_MISMATCH",
                    "block",
                    f"step '{step.step_id}' parameters differ from the approved plan: {', '.join(sorted(mismatched))}",
                    action_index=index,
                    step_id=step.step_id,
                    parameters=sorted(mismatched),
                )
            )
            continue

        undeclared = sorted(set(action.parameters) - set(step.parameters))
        if undeclared:
            findings.append(
                _finding(
                    "UNDECLARED_PARAMETER",
                    "review",
                    f"step '{step.step_id}' carried parameters the plan does not declare: {', '.join(undeclared)}",
                    action_index=index,
                    step_id=step.step_id,
                    parameters=undeclared,
                )
            )

        consumed[step.step_id] = index
        matches.append({"action_index": index, "step_id": step.step_id})

    missing = [step.step_id for step in plan.steps if step.step_id not in consumed and not step.optional]
    missing_optional = [step.step_id for step in plan.steps if step.step_id not in consumed and step.optional]
    for step_id in missing:
        findings.append(
            _finding(
                "STEP_NOT_EXECUTED",
                "review",
                f"approved step '{step_id}' has no observed action",
                step_id=step_id,
            )
        )

    aligned = not any(item["severity"] == "block" for item in findings)
    result = {
        "plan_aligned": aligned,
        "computed_by": "dsg",
        "plan_hash": plan_hash(plan),
        "action_trace_hash": action_trace_hash(actions),
        "steps_total": len(plan.steps),
        "steps_matched": len(matches),
        "steps_missing": missing,
        "optional_steps_missing": missing_optional,
        "plan_complete": not missing,
        "matches": matches,
        "findings": findings,
    }
    result["alignment_hash"] = canonical_hash(
        {
            "plan_hash": result["plan_hash"],
            "action_trace_hash": result["action_trace_hash"],
            "plan_aligned": aligned,
            "findings": findings,
        }
    )
    return result
