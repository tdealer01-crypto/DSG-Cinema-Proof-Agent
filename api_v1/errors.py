"""Refusals for the v1 API, each carrying the one next action that fixes it.

The v1 codes extend the revenue vocabulary rather than replacing it, so a caller
handles every denial from this service with one code path.
"""

from __future__ import annotations

from typing import Any

from revenue.remediation import Remediation, remediation_for as _revenue_remediation

DOCS = "https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/main/docs/API_V1_CONTRACT.md"

AGENT_ASSERTED_VERDICT_REJECTED = "AGENT_ASSERTED_VERDICT_REJECTED"
PLAN_NOT_FOUND = "PLAN_NOT_FOUND"
PLAN_NOT_APPROVED = "PLAN_NOT_APPROVED"
PLAN_ALREADY_APPROVED = "PLAN_ALREADY_APPROVED"
PLAN_HASH_MISMATCH = "PLAN_HASH_MISMATCH"
AGENT_IDENTITY_MISMATCH = "AGENT_IDENTITY_MISMATCH"
EXECUTION_NOT_FOUND = "EXECUTION_NOT_FOUND"
EXECUTION_ALREADY_VERIFIED = "EXECUTION_ALREADY_VERIFIED"
EVIDENCE_HASH_MISMATCH = "EVIDENCE_HASH_MISMATCH"
EVIDENCE_DECODE_FAILED = "EVIDENCE_DECODE_FAILED"
PROOF_NOT_FOUND = "PROOF_NOT_FOUND"
MUTATION_NOT_FOUND = "MUTATION_NOT_FOUND"
IDEMPOTENCY_KEY_CONFLICT = "IDEMPOTENCY_KEY_CONFLICT"
GUARDED_STORAGE_NOT_READY = "GUARDED_STORAGE_NOT_READY"
GUARDED_EVIDENCE_UNREADABLE = "GUARDED_EVIDENCE_UNREADABLE"

_CATALOG: dict[str, Remediation] = {
    AGENT_ASSERTED_VERDICT_REJECTED: Remediation(
        code=AGENT_ASSERTED_VERDICT_REJECTED,
        problem="The request carried a verdict instead of evidence.",
        cause=(
            "Fields such as plan_aligned, constraints_pass, replay_match or verified are "
            "computed by DSG. Accepting them from the caller would make the receipt a "
            "self-report."
        ),
        next_step=(
            "Remove the verdict fields and send the raw material instead: the approved "
            "plan, the observed actions, the recorded evidence artifacts."
        ),
        self_service=True,
        docs=DOCS,
    ),
    PLAN_NOT_FOUND: Remediation(
        code=PLAN_NOT_FOUND,
        problem="No plan exists with that identifier.",
        cause="The plan_id was never created on this deployment, or its store was reset.",
        next_step="Create the plan with POST /api/v1/plans and use the returned plan_id.",
        self_service=True,
        endpoint="POST /api/v1/plans",
        docs=DOCS,
    ),
    PLAN_NOT_APPROVED: Remediation(
        code=PLAN_NOT_APPROVED,
        problem="The plan has not been approved.",
        cause="Executions and proofs are only issued against an approved, locked plan.",
        next_step=(
            "Approve the plan with POST /api/v1/plans/{plan_id}/approve, echoing the "
            "plan_hash DSG computed."
        ),
        self_service=True,
        endpoint="POST /api/v1/plans/{plan_id}/approve",
        docs=DOCS,
    ),
    PLAN_ALREADY_APPROVED: Remediation(
        code=PLAN_ALREADY_APPROVED,
        problem="The plan is already approved and locked.",
        cause="An approved plan is immutable so the proof can name exactly what was approved.",
        next_step="Create a new plan for the changed work and approve that one.",
        self_service=True,
        endpoint="POST /api/v1/plans",
        docs=DOCS,
    ),
    PLAN_HASH_MISMATCH: Remediation(
        code=PLAN_HASH_MISMATCH,
        problem="The approval names a different plan than the one stored.",
        cause=(
            "The plan_hash in the approval does not match the hash DSG computed over the "
            "stored plan, so the approver may be approving text they have not seen."
        ),
        next_step="Read the plan with GET /api/v1/plans/{plan_id} and approve its plan_hash.",
        self_service=True,
        endpoint="GET /api/v1/plans/{plan_id}",
        docs=DOCS,
    ),
    AGENT_IDENTITY_MISMATCH: Remediation(
        code=AGENT_IDENTITY_MISMATCH,
        problem="The executing agent is not the agent the plan approves.",
        cause="The execution's agent_identity differs from the approved plan's agent_identity.",
        next_step="Run the execution under the approved agent identity, or approve a plan for this agent.",
        self_service=True,
        docs=DOCS,
    ),
    EXECUTION_NOT_FOUND: Remediation(
        code=EXECUTION_NOT_FOUND,
        problem="No execution exists with that identifier.",
        cause="The execution_id was never recorded on this deployment, or its store was reset.",
        next_step="Record the execution with POST /api/v1/executions and use the returned execution_id.",
        self_service=True,
        endpoint="POST /api/v1/executions",
        docs=DOCS,
    ),
    EXECUTION_ALREADY_VERIFIED: Remediation(
        code=EXECUTION_ALREADY_VERIFIED,
        problem="This execution already has a proof.",
        cause="Verification is single-shot so one execution cannot produce two conflicting receipts.",
        next_step="Read the existing proof with GET /api/v1/proofs/{proof_id}.",
        self_service=True,
        endpoint="GET /api/v1/proofs/{proof_id}",
        docs=DOCS,
    ),
    EVIDENCE_HASH_MISMATCH: Remediation(
        code=EVIDENCE_HASH_MISMATCH,
        problem="An artifact's declared digest does not match its content.",
        cause="DSG hashes submitted bytes itself and refuses a submission that misdescribes them.",
        next_step="Recompute sha256 over the exact bytes you are submitting, or omit declared_sha256.",
        self_service=True,
        docs=DOCS,
    ),
    EVIDENCE_DECODE_FAILED: Remediation(
        code=EVIDENCE_DECODE_FAILED,
        problem="An artifact's base64 content could not be decoded.",
        cause="content_base64 was not valid, canonical base64.",
        next_step="Re-encode the artifact bytes as standard base64 and resubmit.",
        self_service=True,
        docs=DOCS,
    ),
    PROOF_NOT_FOUND: Remediation(
        code=PROOF_NOT_FOUND,
        problem="No proof exists with that identifier.",
        cause="The proof_id was never issued on this deployment, or its store was reset.",
        next_step="Verify the execution with POST /api/v1/executions/{execution_id}/verify.",
        self_service=True,
        endpoint="POST /api/v1/executions/{execution_id}/verify",
        docs=DOCS,
    ),
    MUTATION_NOT_FOUND: Remediation(
        code=MUTATION_NOT_FOUND,
        problem="No guarded mutation exists with that identifier for this tenant.",
        cause=(
            "Guarded evidence rows are tenant-bound. The id was never written by this "
            "tenant, or it belongs to a different one."
        ),
        next_step=(
            "Execute the mutation with POST /api/v1/control/mutations and read back the "
            "mutation_id it returns, using the same X-DSG-API-Key."
        ),
        self_service=True,
        endpoint="POST /api/v1/control/mutations",
        docs=DOCS,
    ),
    IDEMPOTENCY_KEY_CONFLICT: Remediation(
        code=IDEMPOTENCY_KEY_CONFLICT,
        problem="This idempotency key is already bound to a different action.",
        cause=(
            "A stored guarded mutation carries this key with another action_hash. Serving "
            "the stored row would answer a retry that is not a retry."
        ),
        next_step=(
            "Retry the identical action to receive the original record, or use a new "
            "idempotency_key for the changed action."
        ),
        self_service=True,
        endpoint="POST /api/v1/control/mutations",
        docs=DOCS,
    ),
    GUARDED_STORAGE_NOT_READY: Remediation(
        code=GUARDED_STORAGE_NOT_READY,
        problem="Guarded mutation evidence has no durable store.",
        cause=(
            "Paid enforcement is requested while guarded evidence would be held in process "
            "memory, which forgets every idempotency key on restart."
        ),
        next_step=(
            "Configure DSG_REVENUE_DATABASE_URL so guarded evidence is written to "
            "PostgreSQL/Supabase, then retry."
        ),
        self_service=True,
        docs=DOCS,
    ),
    GUARDED_EVIDENCE_UNREADABLE: Remediation(
        code=GUARDED_EVIDENCE_UNREADABLE,
        problem="The guarded evidence row could not be read back after it was written.",
        cause=(
            "The write transaction found no row for this tenant and key. DSG answers with "
            "the stored row or with nothing; it will not report a mutation it cannot show."
        ),
        next_step=(
            "Retry the identical request with the same idempotency_key. It is safe: the "
            "unique constraint means a retry can only return the stored row."
        ),
        self_service=True,
        endpoint="POST /api/v1/control/mutations",
        docs=DOCS,
    ),
}


def remediation_for(code: str) -> Remediation:
    known = _CATALOG.get(code)
    return known if known is not None else _revenue_remediation(code)


def all_codes() -> list[str]:
    return sorted(_CATALOG)


class ApiError(Exception):
    """A refused v1 request, rendered identically over REST and MCP."""

    def __init__(self, status_code: int, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "error": self.code,
            "message": self.message,
            "remediation": remediation_for(self.code).to_dict(),
        }
        if self.details:
            body["details"] = self.details
        return body
