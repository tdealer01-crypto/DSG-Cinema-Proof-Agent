"""Evidence ingestion, completeness, and replay comparison.

Two honesty rules live here:

1. When an artifact carries bytes, DSG hashes the bytes itself. A `declared_sha256`
   that disagrees with the computed digest is a rejected submission, not a warning.
2. When an artifact carries only a hash, it is recorded as HASH_ONLY and never
   counts as independently verified evidence. Attestation is not verification.

Replay match is likewise computed: an action's declared `output_sha256` counts as
replayed only when some content-verified artifact hashes to exactly that value.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

from .canonical import canonical_hash, sha256_hex, utc_now
from .models import EvidenceArtifact, ObservedAction, PlanDocument

CONTENT_VERIFIED = "CONTENT_VERIFIED"
HASH_ONLY = "HASH_ONLY"


class EvidenceRejected(ValueError):
    def __init__(self, code: str, message: str, artifact_id: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.artifact_id = artifact_id


def ingest_artifact(artifact: EvidenceArtifact) -> dict[str, Any]:
    """Normalise one artifact, computing its digest from the bytes when present."""
    payload: bytes | None = None
    encoding = None

    if artifact.content is not None:
        payload = artifact.content.encode("utf-8")
        encoding = "utf-8"
    elif artifact.content_base64 is not None:
        try:
            payload = base64.b64decode(artifact.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise EvidenceRejected(
                "EVIDENCE_DECODE_FAILED",
                f"artifact '{artifact.artifact_id}' content_base64 is not valid base64",
                artifact.artifact_id,
            ) from exc
        encoding = "base64"

    if payload is None:
        return {
            "artifact_id": artifact.artifact_id,
            "source": artifact.source,
            "step_id": artifact.step_id,
            "media_type": artifact.media_type,
            "sha256": artifact.declared_sha256,
            "declared_sha256": artifact.declared_sha256,
            "size_bytes": None,
            "verification": HASH_ONLY,
            "encoding": None,
            "recorded_at": artifact.recorded_at or utc_now(),
            "ingested_at": utc_now(),
        }

    computed = sha256_hex(payload)
    if artifact.declared_sha256 is not None and artifact.declared_sha256 != computed:
        raise EvidenceRejected(
            "EVIDENCE_HASH_MISMATCH",
            (
                f"artifact '{artifact.artifact_id}' declares sha256 {artifact.declared_sha256} "
                f"but its content hashes to {computed}"
            ),
            artifact.artifact_id,
        )

    return {
        "artifact_id": artifact.artifact_id,
        "source": artifact.source,
        "step_id": artifact.step_id,
        "media_type": artifact.media_type,
        "sha256": computed,
        "declared_sha256": artifact.declared_sha256,
        "size_bytes": len(payload),
        "verification": CONTENT_VERIFIED,
        "encoding": encoding,
        "recorded_at": artifact.recorded_at or utc_now(),
        "ingested_at": utc_now(),
    }


def evidence_hash(records: list[dict[str, Any]]) -> str:
    return canonical_hash(
        sorted(
            (
                {
                    "artifact_id": record["artifact_id"],
                    "sha256": record["sha256"],
                    "step_id": record["step_id"],
                    "verification": record["verification"],
                }
                for record in records
            ),
            key=lambda item: item["artifact_id"],
        )
    )


def assess_evidence(
    plan: PlanDocument,
    actions: list[ObservedAction],
    records: list[dict[str, Any]],
    require_content_evidence: bool = True,
) -> dict[str, Any]:
    """Compute evidence completeness against the steps the plan says need it."""
    required = [step.step_id for step in plan.steps if step.requires_evidence and not step.optional]
    executed = {action.step_id for action in actions if action.step_id}

    by_step: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record["step_id"]:
            by_step.setdefault(record["step_id"], []).append(record)

    covered: list[str] = []
    gaps: list[dict[str, Any]] = []
    for step_id in required:
        artifacts = by_step.get(step_id, [])
        usable = [
            item
            for item in artifacts
            if item["verification"] == CONTENT_VERIFIED or not require_content_evidence
        ]
        if usable:
            covered.append(step_id)
        elif artifacts:
            gaps.append(
                {
                    "step_id": step_id,
                    "code": "EVIDENCE_NOT_CONTENT_VERIFIED",
                    "detail": f"step '{step_id}' has only hash-only attestations",
                }
            )
        else:
            gaps.append(
                {
                    "step_id": step_id,
                    "code": "EVIDENCE_MISSING",
                    "detail": f"step '{step_id}' requires evidence and none was submitted",
                }
            )

    unassigned = [item["artifact_id"] for item in records if not item["step_id"]]
    unknown_step = sorted(
        {
            item["step_id"]
            for item in records
            if item["step_id"] and item["step_id"] not in {step.step_id for step in plan.steps}
        }
    )
    for step_id in unknown_step:
        gaps.append(
            {
                "step_id": step_id,
                "code": "EVIDENCE_FOR_UNKNOWN_STEP",
                "detail": f"evidence references step '{step_id}', which is not in the approved plan",
            }
        )

    completeness = (len(covered) / len(required)) if required else 1.0
    return {
        "evidence_complete": not gaps and len(covered) == len(required),
        "computed_by": "dsg",
        "evidence_completeness": round(completeness, 6),
        "required_steps": required,
        "covered_steps": covered,
        "executed_steps": sorted(step for step in executed if step),
        "gaps": gaps,
        "artifacts_total": len(records),
        "artifacts_content_verified": sum(
            1 for item in records if item["verification"] == CONTENT_VERIFIED
        ),
        "artifacts_hash_only": sum(1 for item in records if item["verification"] == HASH_ONLY),
        "unassigned_artifacts": unassigned,
        "evidence_hash": evidence_hash(records),
    }


def assess_replay(
    plan: PlanDocument,
    actions: list[ObservedAction],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare each action's declared output digest against verified artifacts."""
    verified_digests = {
        item["sha256"] for item in records if item["verification"] == CONTENT_VERIFIED and item["sha256"]
    }
    steps_by_id = {step.step_id: step for step in plan.steps}

    comparisons: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        step = steps_by_id.get(action.step_id or "")
        needs_replay = step.requires_evidence and not step.optional if step else True
        if action.output_sha256 is None:
            record = {
                "action_index": index,
                "step_id": action.step_id,
                "declared_output_sha256": None,
                "matched": False,
                "reason": "NO_DECLARED_OUTPUT",
            }
            comparisons.append(record)
            if needs_replay:
                mismatches.append(record)
            continue
        matched = action.output_sha256 in verified_digests
        record = {
            "action_index": index,
            "step_id": action.step_id,
            "declared_output_sha256": action.output_sha256,
            "matched": matched,
            "reason": None if matched else "NO_VERIFIED_ARTIFACT_WITH_THIS_DIGEST",
        }
        comparisons.append(record)
        if not matched:
            mismatches.append(record)

    checked = [item for item in comparisons if item["declared_output_sha256"] is not None]
    return {
        "replay_match": not mismatches and bool(checked),
        "computed_by": "dsg",
        "actions_checked": len(checked),
        "actions_matched": sum(1 for item in checked if item["matched"]),
        "mismatches": mismatches,
        "comparisons": comparisons,
        "replay_hash": canonical_hash(comparisons),
    }
