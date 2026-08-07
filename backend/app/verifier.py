from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from z3 import And, Bool, BoolVal, If, Implies, Or, Solver, Sum, get_version_string, sat, unknown

from .models import ConstraintResult, PolicyConstraint, VerificationRequest


@dataclass(frozen=True)
class VerificationOutcome:
    status: str
    accepted: bool
    constraint_results: list[ConstraintResult]
    unsat_core: list[str]
    active_rule_ids: list[int]
    total_cost: float
    active_count: int
    solver_version: str


def _to_cents(value: float) -> int:
    return int((Decimal(str(value)) * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _constraint_expression(constraint: PolicyConstraint, variables: dict[int, Any], costs: dict[int, int]):
    if constraint.type == "implication":
        return Implies(variables[constraint.if_rule], variables[constraint.then_rule])
    if constraint.type == "equivalence":
        head = variables[constraint.rules[0]]
        return And(*[variables[rule_id] == head for rule_id in constraint.rules[1:]]) if len(constraint.rules) > 1 else BoolVal(True)
    if constraint.type == "mutual_exclusion":
        return Sum(*[If(variables[rule_id], 1, 0) for rule_id in constraint.rules]) <= 1
    if constraint.type == "at_least_one_of":
        return Or(*[variables[rule_id] for rule_id in constraint.rules])
    if constraint.type == "min_active":
        return Sum(*[If(variable, 1, 0) for variable in variables.values()]) >= constraint.minimum
    if constraint.type == "max_cost":
        return Sum(*[If(variables[rule_id], cost, 0) for rule_id, cost in costs.items()]) <= _to_cents(constraint.budget)
    raise ValueError(f"Unsupported constraint type: {constraint.type}")


def _evaluate_constraint(
    constraint: PolicyConstraint,
    selected: dict[int, bool],
    costs: dict[int, int],
) -> tuple[bool, str]:
    if constraint.type == "implication":
        satisfied = (not selected[constraint.if_rule]) or selected[constraint.then_rule]
        detail = f"rule {constraint.if_rule} -> rule {constraint.then_rule}"
    elif constraint.type == "equivalence":
        values = [selected[rule_id] for rule_id in constraint.rules]
        satisfied = len(set(values)) <= 1
        detail = f"rules {constraint.rules} must have equal states"
    elif constraint.type == "mutual_exclusion":
        active = [rule_id for rule_id in constraint.rules if selected[rule_id]]
        satisfied = len(active) <= 1
        detail = f"at most one active; active={active}"
    elif constraint.type == "at_least_one_of":
        active = [rule_id for rule_id in constraint.rules if selected[rule_id]]
        satisfied = bool(active)
        detail = f"at least one active; active={active}"
    elif constraint.type == "min_active":
        active_count = sum(selected.values())
        satisfied = active_count >= constraint.minimum
        detail = f"active_count={active_count}, minimum={constraint.minimum}"
    elif constraint.type == "max_cost":
        total_cents = sum(costs[rule_id] for rule_id, is_active in selected.items() if is_active)
        budget_cents = _to_cents(constraint.budget)
        satisfied = total_cents <= budget_cents
        detail = f"total_cost={total_cents / 100:.2f}, budget={budget_cents / 100:.2f}"
    else:
        raise ValueError(f"Unsupported constraint type: {constraint.type}")
    return satisfied, detail


def verify_candidate(request: VerificationRequest) -> VerificationOutcome:
    variables = {rule.id: Bool(f"rule_{rule.id}") for rule in request.rules}
    costs = {rule.id: _to_cents(rule.cost) for rule in request.rules}
    selected = {
        rule.id: request.configuration[index] == 1
        for index, rule in enumerate(request.rules)
    }

    solver = Solver()
    tracked_names: dict[str, int] = {}
    constraint_results: list[ConstraintResult] = []

    for index, constraint in enumerate(request.constraints):
        label_name = f"constraint_{index}"
        label = Bool(label_name)
        tracked_names[label_name] = index
        solver.assert_and_track(_constraint_expression(constraint, variables, costs), label)
        satisfied, detail = _evaluate_constraint(constraint, selected, costs)
        constraint_results.append(
            ConstraintResult(
                index=index,
                type=constraint.type,
                description=constraint.description,
                satisfied=satisfied,
                detail=detail,
            )
        )

    for rule_id, value in selected.items():
        solver.add(variables[rule_id] == BoolVal(value))

    check_result = solver.check()
    if check_result == sat:
        status = "SAT"
        accepted = True
        unsat_core: list[str] = []
    elif check_result == unknown:
        status = "UNKNOWN"
        accepted = False
        unsat_core = []
    else:
        status = "UNSAT"
        accepted = False
        core_indexes = sorted(
            tracked_names[str(item)]
            for item in solver.unsat_core()
            if str(item) in tracked_names
        )
        unsat_core = [
            request.constraints[index].description or f"constraint_{index}"
            for index in core_indexes
        ]

    active_rule_ids = [rule_id for rule_id, is_active in selected.items() if is_active]
    total_cost_cents = sum(costs[rule_id] for rule_id in active_rule_ids)

    return VerificationOutcome(
        status=status,
        accepted=accepted,
        constraint_results=constraint_results,
        unsat_core=unsat_core,
        active_rule_ids=active_rule_ids,
        total_cost=total_cost_cents / 100,
        active_count=len(active_rule_ids),
        solver_version=get_version_string(),
    )
