"""Request and response models for the DSG ONE v1 verification API.

Design rule for this whole surface: an agent submits *raw* material — the plan
it was approved to run, the actions it actually took, the evidence it produced.
It never submits a verdict. Fields such as `plan_aligned`, `constraints_pass`,
`replay_match` or `verified` are computed by DSG from the stored raw records and
are rejected on input, so a compromised or over-eager agent cannot talk its way
to a PASS.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Scalar = str | int | float | bool | None

CHANNELS = Literal[
    "github",
    "stripe",
    "openai_plugin",
    "aws",
    "azure",
    "jetbrains",
    "vscode",
    "mcp",
    "api",
    "other",
]

ConstraintOp = Literal[
    "eq",
    "ne",
    "lt",
    "lte",
    "gt",
    "gte",
    "in",
    "not_in",
    "subset_of",
    "starts_with",
    "ends_with",
    "present",
    "absent",
]

ActionStatus = Literal["succeeded", "failed", "skipped"]

_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,63}$")
_HEX_64 = re.compile(r"^[0-9a-fA-F]{64}$")

#: Verdict fields DSG computes. Presenting one on input is a contract violation,
#: not a hint: it is the exact move that turns "verification" into "self-report".
ASSERTED_VERDICT_FIELDS = frozenset(
    {
        "plan_aligned",
        "aligned",
        "constraints_pass",
        "constraints_passed",
        "execution_succeeded",
        "replay_match",
        "replay_matched",
        "evidence_complete",
        "evidence_completeness",
        "authorized",
        "authorized_action_completion",
        "out_of_plan_rejection",
        "z3_constraint_correctness",
        "verified",
        "verification",
        "decision",
        "proof_hash",
        "receipt_hash",
        "risk_score",
    }
)

#: Sub-trees that carry the agent's own opaque data. A key called "verified"
#: inside a deploy parameter block is data, not a verdict, so scanning stops here.
OPAQUE_SUBTREES = frozenset({"parameters", "facts", "observed_facts", "metadata", "outputs", "content"})


def find_asserted_verdicts(payload: Any, path: str = "") -> list[str]:
    """Return the JSON paths of any verdict fields present in a request body."""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            here = f"{path}.{key}" if path else str(key)
            if key in ASSERTED_VERDICT_FIELDS:
                found.append(here)
                continue
            if key in OPAQUE_SUBTREES:
                continue
            found.extend(find_asserted_verdicts(value, here))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            found.extend(find_asserted_verdicts(item, f"{path}[{index}]"))
    return found


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _slug(value: str, label: str) -> str:
    if not _SLUG.fullmatch(value):
        raise ValueError(f"{label} must match {_SLUG.pattern}")
    return value


class PlanStep(Strict):
    step_id: str = Field(max_length=64)
    action: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=255)
    parameters: dict[str, Scalar] = Field(default_factory=dict)
    requires_evidence: bool = True
    optional: bool = False
    description: str | None = Field(default=None, max_length=512)

    @field_validator("step_id")
    @classmethod
    def _check_step_id(cls, value: str) -> str:
        return _slug(value, "step_id")

    @field_validator("parameters")
    @classmethod
    def _bound_parameters(cls, value: dict[str, Scalar]) -> dict[str, Scalar]:
        if len(value) > 32:
            raise ValueError("a step carries at most 32 parameters")
        for key, item in value.items():
            if len(key) > 64:
                raise ValueError("parameter names are at most 64 characters")
            if isinstance(item, str) and len(item) > 512:
                raise ValueError("parameter values are at most 512 characters")
        return value


class Constraint(Strict):
    constraint_id: str = Field(max_length=64)
    field: str = Field(min_length=1, max_length=64)
    op: ConstraintOp
    value: Scalar | list[Scalar] = None
    severity: Literal["block", "review"] = "block"
    description: str | None = Field(default=None, max_length=512)

    @field_validator("constraint_id")
    @classmethod
    def _check_constraint_id(cls, value: str) -> str:
        return _slug(value, "constraint_id")

    @field_validator("value")
    @classmethod
    def _bound_value(cls, value: Scalar | list[Scalar]) -> Scalar | list[Scalar]:
        if isinstance(value, list) and len(value) > 64:
            raise ValueError("a constraint list holds at most 64 values")
        return value

    @model_validator(mode="after")
    def _op_needs_value(self) -> "Constraint":
        set_ops = {"in", "not_in", "subset_of"}
        if self.op in set_ops and not isinstance(self.value, list):
            raise ValueError(f"op {self.op} requires a list value")
        if self.op in {"present", "absent"} and self.value is not None:
            raise ValueError(f"op {self.op} takes no value")
        if self.op not in set_ops | {"present", "absent"} and self.value is None:
            raise ValueError(f"op {self.op} requires a value")
        return self


class PlanDocument(Strict):
    """The raw plan a human approved. DSG hashes it; the agent never hashes it."""

    title: str = Field(min_length=1, max_length=255)
    agent_identity: str = Field(min_length=1, max_length=255)
    channel: CHANNELS = "api"
    steps: list[PlanStep] = Field(min_length=1, max_length=64)
    constraints: list[Constraint] = Field(default_factory=list, max_length=64)
    metadata: dict[str, Scalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_ids(self) -> "PlanDocument":
        step_ids = [step.step_id for step in self.steps]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("step_id values must be unique within a plan")
        constraint_ids = [item.constraint_id for item in self.constraints]
        if len(set(constraint_ids)) != len(constraint_ids):
            raise ValueError("constraint_id values must be unique within a plan")
        return self


class ApprovePlanRequest(Strict):
    approver: str = Field(min_length=1, max_length=255)
    plan_hash: str
    approval_note: str | None = Field(default=None, max_length=1024)

    @field_validator("plan_hash")
    @classmethod
    def _hex(cls, value: str) -> str:
        if not _HEX_64.fullmatch(value):
            raise ValueError("plan_hash must be a 64-character SHA-256 hex digest")
        return value.lower()


class ObservedAction(Strict):
    """One action the agent actually took. `status` is an observation; the
    question of whether it was allowed is DSG's to answer."""

    action: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=255)
    step_id: str | None = Field(default=None, max_length=64)
    parameters: dict[str, Scalar] = Field(default_factory=dict)
    status: ActionStatus = "succeeded"
    started_at: str | None = Field(default=None, max_length=64)
    finished_at: str | None = Field(default=None, max_length=64)
    output_sha256: str | None = None

    @field_validator("output_sha256")
    @classmethod
    def _hex_or_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _HEX_64.fullmatch(value):
            raise ValueError("output_sha256 must be a 64-character SHA-256 hex digest")
        return value.lower()


class PlanAlignmentRequest(Strict):
    plan_id: str | None = Field(default=None, max_length=64)
    plan: PlanDocument | None = None
    actions: list[ObservedAction] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def _one_plan_source(self) -> "PlanAlignmentRequest":
        if bool(self.plan_id) == bool(self.plan):
            raise ValueError("provide exactly one of plan_id or plan")
        return self


class ConstraintsRequest(Strict):
    plan_id: str | None = Field(default=None, max_length=64)
    constraints: list[Constraint] | None = Field(default=None, max_length=64)
    facts: dict[str, Scalar | list[Scalar]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_constraint_source(self) -> "ConstraintsRequest":
        if (self.plan_id is None) == (self.constraints is None):
            raise ValueError("provide exactly one of plan_id or constraints")
        if len(self.facts) > 64:
            raise ValueError("at most 64 facts may be submitted")
        return self


class ExecutionCreate(Strict):
    plan_id: str = Field(min_length=1, max_length=64)
    agent_identity: str = Field(min_length=1, max_length=255)
    environment: str = Field(default="unknown", max_length=128)
    channel: CHANNELS = "api"
    actions: list[ObservedAction] = Field(min_length=1, max_length=128)
    observed_facts: dict[str, Scalar | list[Scalar]] = Field(default_factory=dict)
    cost_microunits: int = Field(default=0, ge=0, le=10**15)
    started_at: str | None = Field(default=None, max_length=64)
    finished_at: str | None = Field(default=None, max_length=64)
    trace_id: str | None = Field(default=None, max_length=128)


class EvidenceArtifact(Strict):
    artifact_id: str = Field(max_length=64)
    source: str = Field(min_length=1, max_length=128)
    step_id: str | None = Field(default=None, max_length=64)
    media_type: str = Field(default="application/json", max_length=128)
    content: str | None = Field(default=None, max_length=65536)
    content_base64: str | None = Field(default=None, max_length=87400)
    declared_sha256: str | None = None
    recorded_at: str | None = Field(default=None, max_length=64)

    @field_validator("artifact_id")
    @classmethod
    def _check_artifact_id(cls, value: str) -> str:
        return _slug(value, "artifact_id")

    @field_validator("declared_sha256")
    @classmethod
    def _hex_or_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _HEX_64.fullmatch(value):
            raise ValueError("declared_sha256 must be a 64-character SHA-256 hex digest")
        return value.lower()

    @model_validator(mode="after")
    def _needs_a_body(self) -> "EvidenceArtifact":
        if self.content is not None and self.content_base64 is not None:
            raise ValueError("provide content or content_base64, not both")
        if self.content is None and self.content_base64 is None and self.declared_sha256 is None:
            raise ValueError("an artifact needs content, content_base64, or declared_sha256")
        return self


class EvidenceSubmission(Strict):
    artifacts: list[EvidenceArtifact] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def _unique_artifact_ids(self) -> "EvidenceSubmission":
        ids = [artifact.artifact_id for artifact in self.artifacts]
        if len(set(ids)) != len(ids):
            raise ValueError("artifact_id values must be unique within a submission")
        return self


class ExecutionVerifyRequest(Strict):
    note: str | None = Field(default=None, max_length=1024)
    require_content_evidence: bool = True
