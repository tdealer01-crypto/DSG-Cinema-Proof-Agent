"""Independent structural verifier for DSG agentic improvement envelopes.

This module verifies binding and evidence references. It deliberately does not
claim that referenced metric/test artifacts are truthful until their raw bytes
are independently inspected by the later evidence-verification stage.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "dsg-agentic-improvement-v1"


class EvidenceRef(BaseModel):
    kind: Literal[
        "commit",
        "workflow_run",
        "test_output",
        "build_output",
        "contract_check",
        "observation",
        "metric",
        "candidate",
        "proof",
        "pr",
        "deployment",
        "replay",
    ]
    uri: str = Field(min_length=1)
    repository: str | None = None
    commitSha: str | None = None
    sha256: str | None = None


class MetricValue(BaseModel):
    name: str = Field(min_length=1)
    value: float
    direction: Literal["HIGHER_IS_BETTER", "LOWER_IS_BETTER"]


class ImprovementEnvelope(BaseModel):
    schemaVersion: Literal["dsg-agentic-improvement-v1"]
    candidateId: str = Field(min_length=1)
    goalId: str = Field(min_length=1)
    approvedPlanHash: str = Field(min_length=1)
    targetRepository: str = Field(min_length=1)
    baselineCommit: str = Field(min_length=7)
    candidateCommit: str = Field(min_length=7)
    allowedPaths: list[str] = Field(min_length=1)
    baselineMetric: MetricValue
    candidateMetric: MetricValue
    constraintsPassed: bool
    evidence: list[EvidenceRef]
    simulationHash: str | None = None


class ImprovementEnvelopeProof(BaseModel):
    verified: bool
    verification: Literal["VERIFIED_ENVELOPE_BINDING", "BLOCKED"]
    proofHash: str
    boundCandidateCommit: str
    failures: list[str]
    evidenceKinds: list[str]


def _canonical_payload(envelope: ImprovementEnvelope) -> bytes:
    payload = envelope.model_dump(mode="json", exclude_none=True)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_improvement_envelope(envelope: ImprovementEnvelope) -> ImprovementEnvelopeProof:
    failures: list[str] = []
    evidence_kinds = sorted({item.kind for item in envelope.evidence})

    if envelope.baselineCommit == envelope.candidateCommit:
        failures.append("SAME_BASELINE_AND_CANDIDATE")

    required = {"commit", "metric", "test_output"}
    missing = sorted(required.difference(evidence_kinds))
    if missing:
        failures.append(f"EVIDENCE_KINDS_MISSING:{','.join(missing)}")

    candidate_bound_refs = [
        ref for ref in envelope.evidence
        if ref.commitSha == envelope.candidateCommit
    ]
    if not candidate_bound_refs:
        failures.append("NO_EVIDENCE_BOUND_TO_CANDIDATE_COMMIT")

    for ref in envelope.evidence:
        if ref.commitSha and ref.commitSha not in {envelope.baselineCommit, envelope.candidateCommit}:
            failures.append(f"EVIDENCE_COMMIT_MISMATCH:{ref.kind}")

    if envelope.baselineMetric.name != envelope.candidateMetric.name:
        failures.append("METRIC_NAME_MISMATCH")
    if envelope.baselineMetric.direction != envelope.candidateMetric.direction:
        failures.append("METRIC_DIRECTION_MISMATCH")

    proof_hash = hashlib.sha256(_canonical_payload(envelope)).hexdigest()
    verified = not failures
    return ImprovementEnvelopeProof(
        verified=verified,
        verification="VERIFIED_ENVELOPE_BINDING" if verified else "BLOCKED",
        proofHash=proof_hash,
        boundCandidateCommit=envelope.candidateCommit,
        failures=failures,
        evidenceKinds=evidence_kinds,
    )
