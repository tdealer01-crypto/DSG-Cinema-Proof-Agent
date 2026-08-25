"""Raw-evidence verification for governed agentic improvement candidates.

This is the stage after structural envelope binding. A successful result means
Cinema independently verified GitHub Actions identity plus the exact raw bytes
for metric, test, and build evidence against SHA-256 digests in the candidate
envelope. It still does not authorize promotion; the DSG Control Plane does.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from typing import Literal

import httpx
from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .github_actions_oidc import (
    GitHubActionsIdentity,
    OidcVerificationError,
    fetch_github_actions_jwks,
    verify_github_actions_oidc,
)
from .improvement_proof import ImprovementEnvelope, verify_improvement_envelope

MAX_RAW_ARTIFACT_BYTES = 2 * 1024 * 1024
RAW_KINDS = ("metric", "test_output", "build_output")

router = APIRouter(prefix="/api/v1/improvement", tags=["agentic-improvement-proof"])


class RawEvidenceArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["metric", "test_output", "build_output"]
    commitSha: str = Field(min_length=7)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    contentBase64: str = Field(min_length=1, max_length=4_000_000)


class ImprovementAttestationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    oidcToken: str = Field(min_length=32)
    envelope: ImprovementEnvelope
    artifacts: list[RawEvidenceArtifact] = Field(min_length=3, max_length=3)


class RawEvidenceProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proofId: str
    proofHash: str
    verified: bool
    verification: Literal["VERIFIED_RAW_EVIDENCE", "BLOCKED"]
    rawEvidenceVerified: bool
    boundCandidateCommit: str
    structuralProofId: str
    structuralProofHash: str
    failures: list[str]
    artifactDigests: dict[str, str]
    githubIdentity: GitHubActionsIdentity


def _decode_artifact(artifact: RawEvidenceArtifact) -> bytes:
    try:
        raw = base64.b64decode(artifact.contentBase64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"RAW_ARTIFACT_BASE64_INVALID:{artifact.kind}") from exc
    if not raw:
        raise ValueError(f"RAW_ARTIFACT_EMPTY:{artifact.kind}")
    if len(raw) > MAX_RAW_ARTIFACT_BYTES:
        raise ValueError(f"RAW_ARTIFACT_TOO_LARGE:{artifact.kind}")
    return raw


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def verify_raw_improvement_evidence(
    envelope: ImprovementEnvelope,
    artifacts: list[RawEvidenceArtifact],
    identity: GitHubActionsIdentity,
) -> RawEvidenceProof:
    structural = verify_improvement_envelope(envelope)
    failures = [f"STRUCTURAL:{item}" for item in structural.failures]
    artifact_digests: dict[str, str] = {}

    if identity.repository != envelope.targetRepository:
        failures.append("OIDC_TARGET_REPOSITORY_MISMATCH")

    commit_refs = [item for item in envelope.evidence if item.kind == "commit"]
    expected_commit_uri = f"git://{envelope.targetRepository}@{envelope.candidateCommit}"
    if not any(
        item.uri == expected_commit_uri and item.commitSha == envelope.candidateCommit
        for item in commit_refs
    ):
        failures.append("CANDIDATE_COMMIT_EVIDENCE_INVALID")

    artifact_by_kind = {item.kind: item for item in artifacts}
    if len(artifact_by_kind) != len(artifacts):
        failures.append("RAW_ARTIFACT_KIND_DUPLICATE")

    decoded: dict[str, bytes] = {}
    for kind in RAW_KINDS:
        refs = [
            item for item in envelope.evidence
            if item.kind == kind and item.commitSha == envelope.candidateCommit
        ]
        if len(refs) != 1:
            failures.append(f"RAW_EVIDENCE_REF_COUNT_INVALID:{kind}")
            continue
        ref = refs[0]
        if not ref.uri.startswith(f"artifact://github-actions/{identity.runId}/"):
            failures.append(f"RAW_EVIDENCE_RUN_BINDING_MISMATCH:{kind}")
        if not ref.sha256 or len(ref.sha256) != 64:
            failures.append(f"RAW_EVIDENCE_DIGEST_MISSING:{kind}")
            continue

        artifact = artifact_by_kind.get(kind)
        if artifact is None:
            failures.append(f"RAW_ARTIFACT_MISSING:{kind}")
            continue
        if artifact.commitSha != envelope.candidateCommit:
            failures.append(f"RAW_ARTIFACT_COMMIT_MISMATCH:{kind}")
        if artifact.sha256 != ref.sha256:
            failures.append(f"RAW_ARTIFACT_DECLARED_DIGEST_MISMATCH:{kind}")
        try:
            raw = _decode_artifact(artifact)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        actual = hashlib.sha256(raw).hexdigest()
        artifact_digests[kind] = actual
        decoded[kind] = raw
        if actual != ref.sha256 or actual != artifact.sha256:
            failures.append(f"RAW_ARTIFACT_DIGEST_MISMATCH:{kind}")

    metric_raw = decoded.get("metric")
    if metric_raw is not None:
        try:
            metric = json.loads(metric_raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            failures.append("RAW_METRIC_JSON_INVALID")
        else:
            if not isinstance(metric, dict):
                failures.append("RAW_METRIC_OBJECT_REQUIRED")
            else:
                previous = metric.get("previousBestFitness")
                current = metric.get("newBestFitness")
                if not isinstance(previous, (int, float)) or isinstance(previous, bool) or not _close(float(previous), envelope.baselineMetric.value):
                    failures.append("RAW_METRIC_BASELINE_MISMATCH")
                if not isinstance(current, (int, float)) or isinstance(current, bool) or not _close(float(current), envelope.candidateMetric.value):
                    failures.append("RAW_METRIC_CANDIDATE_MISMATCH")
                if metric.get("verificationPassed") is not True:
                    failures.append("RAW_METRIC_SIMULATION_NOT_VERIFIED")
                if envelope.simulationHash and metric.get("simulationHash") != envelope.simulationHash:
                    failures.append("RAW_METRIC_SIMULATION_HASH_MISMATCH")

    proof_material = {
        "schemaVersion": "dsg-agentic-raw-evidence-v1",
        "envelope": envelope.model_dump(mode="json", exclude_none=True),
        "structuralProofHash": structural.proofHash,
        "artifactDigests": artifact_digests,
        "githubIdentity": identity.model_dump(mode="json"),
        "failures": sorted(failures),
    }
    proof_hash = hashlib.sha256(_canonical_bytes(proof_material)).hexdigest()
    verified = structural.verified and not failures and set(artifact_digests) == set(RAW_KINDS)

    return RawEvidenceProof(
        proofId=f"cinema-raw-improvement-{proof_hash[:24]}",
        proofHash=proof_hash,
        verified=verified,
        verification="VERIFIED_RAW_EVIDENCE" if verified else "BLOCKED",
        rawEvidenceVerified=verified,
        boundCandidateCommit=envelope.candidateCommit,
        structuralProofId=structural.proofId,
        structuralProofHash=structural.proofHash,
        failures=failures,
        artifactDigests=artifact_digests,
        githubIdentity=identity,
    )


@router.post("/attest", response_model=RawEvidenceProof)
async def attest_improvement_evidence(request: ImprovementAttestationRequest) -> RawEvidenceProof:
    try:
        jwks = await fetch_github_actions_jwks()
    except (httpx.HTTPError, OidcVerificationError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="GITHUB_OIDC_JWKS_UNAVAILABLE") from exc

    try:
        identity = verify_github_actions_oidc(request.oidcToken, jwks)
    except OidcVerificationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return verify_raw_improvement_evidence(request.envelope, request.artifacts, identity)


def install(app: FastAPI) -> None:
    app.include_router(router)
