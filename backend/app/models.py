from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

ConstraintType = Literal[
    "implication",
    "equivalence",
    "mutual_exclusion",
    "at_least_one_of",
    "min_active",
    "max_cost",
]


class PolicyRule(BaseModel):
    id: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=200)
    cost: float = Field(ge=0)
    risk_reduction: float
    business_value: float
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)


class PolicyConstraint(BaseModel):
    type: ConstraintType
    description: str = Field(default="", max_length=2000)
    if_rule: int | None = Field(default=None, ge=0)
    then_rule: int | None = Field(default=None, ge=0)
    rules: list[int] = Field(default_factory=list)
    minimum: int | None = Field(default=None, ge=0)
    budget: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_shape(self) -> "PolicyConstraint":
        if self.type == "implication" and (self.if_rule is None or self.then_rule is None):
            raise ValueError("implication requires if_rule and then_rule")
        if self.type in {"equivalence", "mutual_exclusion", "at_least_one_of"} and not self.rules:
            raise ValueError(f"{self.type} requires rules")
        if self.type == "min_active" and self.minimum is None:
            raise ValueError("min_active requires minimum")
        if self.type == "max_cost" and self.budget is None:
            raise ValueError("max_cost requires budget")
        return self


class SolverEvidence(BaseModel):
    seed: int
    iterations: int = Field(ge=0)
    qubo_energy: float
    solution_hash: str = Field(min_length=1, max_length=256)


class VerificationRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=200)
    preset_name: str = Field(min_length=1, max_length=200)
    configuration: list[int] = Field(min_length=1, max_length=1000)
    rules: list[PolicyRule] = Field(min_length=1, max_length=1000)
    constraints: list[PolicyConstraint] = Field(default_factory=list, max_length=5000)
    solver: SolverEvidence
    client_name: str = Field(default="android", max_length=100)
    client_version: str = Field(default="unknown", max_length=100)

    @model_validator(mode="after")
    def validate_request(self) -> "VerificationRequest":
        if len(self.configuration) != len(self.rules):
            raise ValueError("configuration length must equal rules length")
        if any(value not in (0, 1) for value in self.configuration):
            raise ValueError("configuration values must be 0 or 1")
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique")
        valid_ids = set(ids)
        for constraint in self.constraints:
            referenced: set[int] = set(constraint.rules)
            if constraint.if_rule is not None:
                referenced.add(constraint.if_rule)
            if constraint.then_rule is not None:
                referenced.add(constraint.then_rule)
            unknown = referenced - valid_ids
            if unknown:
                raise ValueError(f"constraint references unknown rule ids: {sorted(unknown)}")
        return self


class ConstraintResult(BaseModel):
    index: int
    type: ConstraintType
    description: str
    satisfied: bool
    detail: str


class AuditChainProof(BaseModel):
    sequence: int
    previous_hash: str
    event_hash: str


class VerificationResponse(BaseModel):
    request_id: str
    accepted: bool
    z3_status: Literal["SAT", "UNSAT", "UNKNOWN"]
    all_constraints_satisfied: bool
    constraint_results: list[ConstraintResult]
    unsat_core: list[str]
    active_rule_ids: list[int]
    total_cost: float
    active_count: int
    input_hash: str
    proof_hash: str
    proof_signature: str | None = None
    client_solution_hash: str
    solver_name: str = "Z3"
    solver_version: str
    verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    audit: AuditChainProof
