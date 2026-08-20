from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


POLICY_VERSION = "dsg-verified-execution-1.0.0"
RECEIPT_VERSION = "dsg-proof-receipt-1.0.0"

VerificationChannel = Literal[
    "github",
    "stripe",
    "aws",
    "azure",
    "jetbrains",
    "vscode",
    "api",
    "other",
]
Decision = Literal["ALLOW", "REVIEW", "BLOCK"]

_HEX_64 = re.compile(r"^[0-9a-fA-F]{64}$")


class VerificationRequest(BaseModel):
    execution_id: str = Field(min_length=4, max_length=128)
    trace_id: str | None = Field(default=None, max_length=128)
    channel: VerificationChannel = "api"
    agent_identity: str = Field(min_length=1, max_length=255)
    approved_plan_hash: str
    proposed_action_hash: str
    authorized: bool
    plan_aligned: bool
    constraints_pass: bool
    execution_succeeded: bool
    replay_match: bool
    evidence_complete: bool
    cost_microunits: int = Field(default=0, ge=0, le=10**15)

    @field_validator("approved_plan_hash", "proposed_action_hash")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _HEX_64.fullmatch(value):
            raise ValueError("must be a 64-character hexadecimal SHA-256 value")
        return value.lower()


def target_decision(request: VerificationRequest) -> tuple[Decision, list[str]]:
    blockers: list[str] = []
    reviews: list[str] = []

    if not request.authorized:
        blockers.append("action is not authorized")
    if not request.plan_aligned:
        blockers.append("action is outside the approved plan")
    if not request.constraints_pass:
        blockers.append("deterministic constraints failed")

    if blockers:
        return "BLOCK", blockers

    if not request.execution_succeeded:
        reviews.append("execution did not complete successfully")
    if not request.replay_match:
        reviews.append("replay does not match")
    if not request.evidence_complete:
        reviews.append("evidence is incomplete")

    if reviews:
        return "REVIEW", reviews

    return "ALLOW", ["authorized action completed with matching replay and complete evidence"]


def context_hash(request: VerificationRequest) -> str:
    canonical = {
        "execution_id": request.execution_id,
        "trace_id": request.trace_id,
        "channel": request.channel,
        "agent_identity": request.agent_identity,
        "approved_plan_hash": request.approved_plan_hash,
        "proposed_action_hash": request.proposed_action_hash,
        "authorized": request.authorized,
        "plan_aligned": request.plan_aligned,
        "constraints_pass": request.constraints_pass,
        "execution_succeeded": request.execution_succeeded,
        "replay_match": request.replay_match,
        "evidence_complete": request.evidence_complete,
        "cost_microunits": request.cost_microunits,
        "policy_version": POLICY_VERSION,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
