"""The v1 verification flow, shared by the REST routes and the MCP surface.

Flow: approve a plan, check alignment, check constraints, record the execution,
submit evidence, verify, read the proof. Every verdict on that path is computed
here from stored raw records. Nothing in this module reads a verdict from the
caller, and nothing returns a verified state without an exact Z3 proof.
"""

from __future__ import annotations

from typing import Any, Optional

from marketplace_verification import POLICY_VERSION, RECEIPT_VERSION

from . import API_VERSION, ENGINE_VERSION
from .alignment import evaluate_alignment, plan_hash as compute_plan_hash
from .canonical import canonical_hash, new_id, utc_now
from .constraints import evaluate_constraints
from .errors import (
    AGENT_IDENTITY_MISMATCH,
    EXECUTION_ALREADY_VERIFIED,
    EXECUTION_NOT_FOUND,
    PLAN_ALREADY_APPROVED,
    PLAN_HASH_MISMATCH,
    PLAN_NOT_APPROVED,
    PLAN_NOT_FOUND,
    PROOF_NOT_FOUND,
    ApiError,
)
from .evidence import EvidenceRejected, assess_evidence, assess_replay, ingest_artifact
from .models import (
    ApprovePlanRequest,
    Constraint,
    ConstraintsRequest,
    EvidenceSubmission,
    ExecutionCreate,
    ExecutionVerifyRequest,
    ObservedAction,
    PlanAlignmentRequest,
    PlanDocument,
)
from .store import get_store
from .verifier import ProofUnavailable, prove_decision

VERIFIED_EXECUTION_SKU = "verified_execution"

STATUS_DRAFT = "DRAFT"
STATUS_APPROVED = "APPROVED"
STATUS_RECORDED = "RECORDED"
STATUS_EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
STATUS_VERIFIED = "VERIFIED"

INDEPENDENT_VERIFICATION = {
    "verdicts_accepted_from_agent": False,
    "computed_by": "dsg",
    "engine_version": ENGINE_VERSION,
    "statement": (
        "plan alignment, constraint satisfaction, evidence completeness and replay match "
        "are recomputed by DSG from the stored raw plan, actions and artifacts"
    ),
}


# ------------------------------------------------------------------- plans
def create_plan(document: PlanDocument) -> dict[str, Any]:
    record = {
        "plan_id": new_id("plan"),
        "status": STATUS_DRAFT,
        "plan_hash": compute_plan_hash(document),
        "document": document.model_dump(mode="json"),
        "api_version": API_VERSION,
        "policy_version": POLICY_VERSION,
        "created_at": utc_now(),
        "approval": None,
    }
    get_store().put("plans", record["plan_id"], record)
    return _plan_view(record)


def get_plan_record(plan_id: str) -> dict[str, Any]:
    record = get_store().get("plans", plan_id)
    if record is None:
        raise ApiError(404, PLAN_NOT_FOUND, f"no plan with id '{plan_id}'", plan_id=plan_id)
    return record


def plan_document(record: dict[str, Any]) -> PlanDocument:
    return PlanDocument.model_validate(record["document"])


def _plan_view(record: dict[str, Any]) -> dict[str, Any]:
    view = dict(record)
    view["plan_hash_verified"] = compute_plan_hash(plan_document(record)) == record["plan_hash"]
    view["independent_verification"] = INDEPENDENT_VERIFICATION
    if record["status"] == STATUS_DRAFT:
        view["next_step"] = (
            f"POST /api/v1/plans/{record['plan_id']}/approve with plan_hash "
            f"{record['plan_hash']}"
        )
    return view


def read_plan(plan_id: str) -> dict[str, Any]:
    return _plan_view(get_plan_record(plan_id))


def approve_plan(plan_id: str, request: ApprovePlanRequest) -> dict[str, Any]:
    record = get_plan_record(plan_id)
    if record["status"] == STATUS_APPROVED:
        raise ApiError(
            409,
            PLAN_ALREADY_APPROVED,
            f"plan '{plan_id}' was already approved",
            plan_id=plan_id,
            approved_at=record["approval"]["approved_at"],
        )
    if request.plan_hash != record["plan_hash"]:
        raise ApiError(
            409,
            PLAN_HASH_MISMATCH,
            "the approval names a plan_hash that does not match the stored plan",
            plan_id=plan_id,
            stored_plan_hash=record["plan_hash"],
            submitted_plan_hash=request.plan_hash,
        )

    approval = {
        "approver": request.approver,
        "approved_at": utc_now(),
        "approval_note": request.approval_note,
        "plan_hash": record["plan_hash"],
    }
    approval["approval_hash"] = canonical_hash(approval)

    def _apply(current: dict[str, Any]) -> dict[str, Any]:
        current["status"] = STATUS_APPROVED
        current["approval"] = approval
        return current

    updated = get_store().mutate("plans", plan_id, _apply)
    if updated is None:  # pragma: no cover - the record was read moments ago
        raise ApiError(404, PLAN_NOT_FOUND, f"no plan with id '{plan_id}'", plan_id=plan_id)
    view = _plan_view(updated)
    view["next_step"] = "POST /api/v1/verify/plan-alignment with the actions the agent proposes"
    return view


# --------------------------------------------------------------- alignment
def verify_plan_alignment(request: PlanAlignmentRequest) -> dict[str, Any]:
    if request.plan is not None:
        document = request.plan
        source = {"plan_source": "inline", "plan_id": None, "plan_status": "UNAPPROVED"}
    else:
        record = get_plan_record(str(request.plan_id))
        document = plan_document(record)
        source = {
            "plan_source": "stored",
            "plan_id": record["plan_id"],
            "plan_status": record["status"],
        }

    result = evaluate_alignment(document, request.actions)
    return {
        **source,
        **result,
        "independent_verification": INDEPENDENT_VERIFICATION,
        "evaluated_at": utc_now(),
    }


# -------------------------------------------------------------- constraints
def _resolve_constraints(request: ConstraintsRequest) -> tuple[list[Constraint], dict[str, Any]]:
    if request.constraints is not None:
        return request.constraints, {"constraint_source": "inline", "plan_id": None}
    record = get_plan_record(str(request.plan_id))
    document = plan_document(record)
    return list(document.constraints), {
        "constraint_source": "stored",
        "plan_id": record["plan_id"],
        "plan_status": record["status"],
    }


async def verify_constraints(request: ConstraintsRequest) -> dict[str, Any]:
    constraints, source = _resolve_constraints(request)
    result = evaluate_constraints(constraints, dict(request.facts))

    if not result["constraints_pass"]:
        target = "BLOCK"
    elif result["requires_review"]:
        target = "REVIEW"
    else:
        target = "ALLOW"

    proof = await _prove(target, f"constraints-{result['evaluation_hash'][:24]}", "dsg-one-constraints-v1")
    return {
        **source,
        **result,
        "decision": target,
        "verified": True,
        "verification": proof["verification"],
        "proof_hash": proof["proof_hash"],
        "request_hash": proof["request_hash"],
        "witness": proof.get("witness"),
        "energy_exact": proof.get("energy_exact"),
        "independent_verification": INDEPENDENT_VERIFICATION,
        "evaluated_at": utc_now(),
    }


async def _prove(target: str, request_id: str, preset: str) -> dict[str, Any]:
    try:
        return await prove_decision(target, request_id, preset)
    except ProofUnavailable as exc:
        raise ApiError(502, exc.code, exc.message) from exc


# --------------------------------------------------------------- executions
def _require_approved_plan(plan_id: str) -> dict[str, Any]:
    record = get_plan_record(plan_id)
    if record["status"] != STATUS_APPROVED:
        raise ApiError(
            409,
            PLAN_NOT_APPROVED,
            f"plan '{plan_id}' is {record['status']}, so no execution can be verified against it",
            plan_id=plan_id,
            plan_status=record["status"],
        )
    return record


def record_execution(request: ExecutionCreate) -> dict[str, Any]:
    plan_record = _require_approved_plan(request.plan_id)
    document = plan_document(plan_record)
    if document.agent_identity != request.agent_identity:
        raise ApiError(
            409,
            AGENT_IDENTITY_MISMATCH,
            (
                f"plan '{request.plan_id}' approves agent '{document.agent_identity}' "
                f"but the execution reports '{request.agent_identity}'"
            ),
            approved_agent_identity=document.agent_identity,
            submitted_agent_identity=request.agent_identity,
        )

    alignment = evaluate_alignment(document, request.actions)
    record = {
        "execution_id": new_id("exec"),
        "plan_id": plan_record["plan_id"],
        "plan_hash": plan_record["plan_hash"],
        "status": STATUS_RECORDED,
        "agent_identity": request.agent_identity,
        "environment": request.environment,
        "channel": request.channel,
        "trace_id": request.trace_id,
        "actions": [action.model_dump(mode="json") for action in request.actions],
        "observed_facts": dict(request.observed_facts),
        "cost_microunits": request.cost_microunits,
        "started_at": request.started_at,
        "finished_at": request.finished_at,
        "recorded_at": utc_now(),
        "action_trace_hash": alignment["action_trace_hash"],
        "evidence": [],
        "proof_id": None,
    }
    get_store().put("executions", record["execution_id"], record)
    return {
        **_execution_view(record),
        "alignment_preview": alignment,
        "next_step": f"POST /api/v1/executions/{record['execution_id']}/evidence",
    }


def get_execution_record(execution_id: str) -> dict[str, Any]:
    record = get_store().get("executions", execution_id)
    if record is None:
        raise ApiError(
            404,
            EXECUTION_NOT_FOUND,
            f"no execution with id '{execution_id}'",
            execution_id=execution_id,
        )
    return record


def _execution_view(record: dict[str, Any]) -> dict[str, Any]:
    view = dict(record)
    view["independent_verification"] = INDEPENDENT_VERIFICATION
    return view


def read_execution(execution_id: str) -> dict[str, Any]:
    return _execution_view(get_execution_record(execution_id))


def submit_evidence(execution_id: str, submission: EvidenceSubmission) -> dict[str, Any]:
    record = get_execution_record(execution_id)
    if record["status"] == STATUS_VERIFIED:
        raise ApiError(
            409,
            EXECUTION_ALREADY_VERIFIED,
            f"execution '{execution_id}' is already verified and its evidence is sealed",
            execution_id=execution_id,
            proof_id=record["proof_id"],
        )

    try:
        ingested = [ingest_artifact(artifact) for artifact in submission.artifacts]
    except EvidenceRejected as exc:
        raise ApiError(422, exc.code, exc.message, artifact_id=exc.artifact_id) from exc

    def _apply(current: dict[str, Any]) -> dict[str, Any]:
        merged = {item["artifact_id"]: item for item in current.get("evidence", [])}
        for item in ingested:
            merged[item["artifact_id"]] = item
        current["evidence"] = [merged[key] for key in sorted(merged)]
        current["status"] = STATUS_EVIDENCE_SUBMITTED
        return current

    updated = get_store().mutate("executions", execution_id, _apply)
    if updated is None:  # pragma: no cover - the record was read moments ago
        raise ApiError(404, EXECUTION_NOT_FOUND, f"no execution with id '{execution_id}'")

    document = plan_document(get_plan_record(updated["plan_id"]))
    actions = [ObservedAction.model_validate(item) for item in updated["actions"]]
    evidence = assess_evidence(document, actions, updated["evidence"])
    replay = assess_replay(document, actions, updated["evidence"])

    return {
        "execution_id": execution_id,
        "status": updated["status"],
        "accepted_artifacts": [item["artifact_id"] for item in ingested],
        "artifacts": updated["evidence"],
        "evidence": evidence,
        "replay": replay,
        "independent_verification": INDEPENDENT_VERIFICATION,
        "next_step": f"POST /api/v1/executions/{execution_id}/verify",
        "submitted_at": utc_now(),
    }


# -------------------------------------------------------------- verification
def derived_facts(execution: dict[str, Any], actions: list[ObservedAction]) -> dict[str, Any]:
    """Facts DSG observes for itself. These override anything the agent reported."""
    derived: dict[str, Any] = {
        "environment": execution["environment"],
        "channel": execution["channel"],
        "agent_identity": execution["agent_identity"],
        "cost_microunits": execution["cost_microunits"],
        "actions_total": len(actions),
        "actions_failed": sum(1 for action in actions if action.status == "failed"),
        "actions_skipped": sum(1 for action in actions if action.status == "skipped"),
        "targets": sorted({action.target for action in actions}),
        "actions": sorted({action.action for action in actions}),
        "evidence_artifacts": len(execution.get("evidence", [])),
    }
    facts = dict(execution.get("observed_facts", {}))
    facts.update(derived)
    return facts


def derive_decision(computed: dict[str, Any], constraint_result: dict[str, Any]) -> tuple[str, list[str]]:
    blockers: list[str] = []
    if not computed["authorized"]:
        blockers.append("the execution is not authorized by an approved plan")
    if not computed["plan_aligned"]:
        blockers.append("observed actions fall outside the approved plan")
    if not computed["constraints_pass"]:
        blockers.append("policy constraints were violated")
    if blockers:
        return "BLOCK", blockers

    reviews: list[str] = []
    if constraint_result["requires_review"]:
        reviews.append("policy constraints raised review-severity findings")
    if not computed["execution_succeeded"]:
        reviews.append("the execution did not complete every approved step successfully")
    if not computed["replay_match"]:
        reviews.append("replay does not match the recorded evidence")
    if not computed["evidence_complete"]:
        reviews.append("evidence is incomplete")
    if reviews:
        return "REVIEW", reviews

    return "ALLOW", ["authorized execution stayed in plan with matching replay and complete evidence"]


async def verify_execution(
    execution_id: str,
    request: ExecutionVerifyRequest,
    authorization: Any = None,
    meter: Any = None,
) -> dict[str, Any]:
    record = get_execution_record(execution_id)
    if record["status"] == STATUS_VERIFIED and record.get("proof_id"):
        raise ApiError(
            409,
            EXECUTION_ALREADY_VERIFIED,
            f"execution '{execution_id}' already has proof '{record['proof_id']}'",
            execution_id=execution_id,
            proof_id=record["proof_id"],
        )

    plan_record = _require_approved_plan(record["plan_id"])
    document = plan_document(plan_record)
    actions = [ObservedAction.model_validate(item) for item in record["actions"]]
    artifacts = record.get("evidence", [])

    alignment = evaluate_alignment(document, actions)
    facts = derived_facts(record, actions)
    constraint_result = evaluate_constraints(list(document.constraints), facts)
    evidence = assess_evidence(document, actions, artifacts, request.require_content_evidence)
    replay = assess_replay(document, actions, artifacts)

    executed_ok = all(action.status == "succeeded" for action in actions)
    computed = {
        "authorized": plan_record["status"] == STATUS_APPROVED
        and plan_record["plan_hash"] == record["plan_hash"]
        and document.agent_identity == record["agent_identity"],
        "plan_aligned": alignment["plan_aligned"],
        "constraints_pass": constraint_result["constraints_pass"],
        "execution_succeeded": executed_ok and alignment["plan_complete"],
        "replay_match": replay["replay_match"],
        "evidence_complete": evidence["evidence_complete"],
        "evidence_completeness": evidence["evidence_completeness"],
    }

    decision, reasons = derive_decision(computed, constraint_result)

    context = {
        "api_version": API_VERSION,
        "policy_version": POLICY_VERSION,
        "execution_id": execution_id,
        "plan_id": record["plan_id"],
        "plan_hash": record["plan_hash"],
        "action_trace_hash": alignment["action_trace_hash"],
        "alignment_hash": alignment["alignment_hash"],
        "constraints_hash": constraint_result["constraints_hash"],
        "facts_hash": constraint_result["facts_hash"],
        "evidence_hash": evidence["evidence_hash"],
        "replay_hash": replay["replay_hash"],
        "computed": computed,
        "decision": decision,
    }
    context_hash = canonical_hash(context)

    proof = await _prove(decision, f"exec-{context_hash[:24]}", "dsg-one-execution-v1")

    receipt = {
        "proof_id": new_id("proof"),
        "receipt_version": RECEIPT_VERSION,
        "policy_version": POLICY_VERSION,
        "api_version": API_VERSION,
        "execution_id": execution_id,
        "plan_id": record["plan_id"],
        "trace_id": record.get("trace_id"),
        "channel": record["channel"],
        "agent_identity": record["agent_identity"],
        "environment": record["environment"],
        "decision": decision,
        "reasons": reasons,
        "computed": computed,
        "inputs": {
            "plan_hash": record["plan_hash"],
            "approval_hash": plan_record["approval"]["approval_hash"],
            "action_trace_hash": alignment["action_trace_hash"],
            "alignment_hash": alignment["alignment_hash"],
            "constraints_hash": constraint_result["constraints_hash"],
            "facts_hash": constraint_result["facts_hash"],
            "evidence_hash": evidence["evidence_hash"],
            "replay_hash": replay["replay_hash"],
        },
        "findings": {
            "alignment": alignment["findings"],
            "constraints": constraint_result["violations"],
            "evidence": evidence["gaps"],
            "replay": replay["mismatches"],
        },
        "evidence_summary": {
            "artifacts_total": evidence["artifacts_total"],
            "artifacts_content_verified": evidence["artifacts_content_verified"],
            "artifacts_hash_only": evidence["artifacts_hash_only"],
            "required_steps": evidence["required_steps"],
            "covered_steps": evidence["covered_steps"],
            "evidence_completeness": evidence["evidence_completeness"],
        },
        "cost_microunits": record["cost_microunits"],
        "verified": True,
        "verification": proof["verification"],
        "proof_hash": proof["proof_hash"],
        "request_hash": proof["request_hash"],
        "context_hash": context_hash,
        "witness": proof.get("witness"),
        "energy_exact": proof.get("energy_exact"),
        "independent_verification": INDEPENDENT_VERIFICATION,
        "verified_at": utc_now(),
    }
    if meter is not None and authorization is not None:
        billing_block = await meter(
            authorization,
            sku=VERIFIED_EXECUTION_SKU,
            receipt=receipt,
            channel=record["channel"],
        )
        if billing_block is not None:
            receipt["billing"] = billing_block

    receipt["receipt_hash"] = canonical_hash(receipt)

    store = get_store()
    store.put("proofs", receipt["proof_id"], receipt)

    def _seal(current: dict[str, Any]) -> dict[str, Any]:
        current["status"] = STATUS_VERIFIED
        current["proof_id"] = receipt["proof_id"]
        current["verified_at"] = receipt["verified_at"]
        return current

    store.mutate("executions", execution_id, _seal)
    return receipt


# -------------------------------------------------------------------- proofs
def read_proof(proof_id: str) -> dict[str, Any]:
    record = get_store().get("proofs", proof_id)
    if record is None:
        raise ApiError(404, PROOF_NOT_FOUND, f"no proof with id '{proof_id}'", proof_id=proof_id)
    stored_hash = record.get("receipt_hash")
    recomputed = canonical_hash({k: v for k, v in record.items() if k != "receipt_hash"})
    view = dict(record)
    view["receipt_hash_verified"] = stored_hash == recomputed
    view["receipt_hash_recomputed"] = recomputed
    view["read_at"] = utc_now()
    return view


def store_summary() -> dict[str, Any]:
    store = get_store()
    return {
        "mode": store.mode,
        "durable": store.durable,
        "records": store.counts(),
    }


def flow_definition() -> list[dict[str, str]]:
    return [
        {"step": "approve_plan", "endpoint": "POST /api/v1/plans/{plan_id}/approve"},
        {"step": "plan_alignment", "endpoint": "POST /api/v1/verify/plan-alignment"},
        {"step": "constraints", "endpoint": "POST /api/v1/verify/constraints"},
        {"step": "execute", "endpoint": "POST /api/v1/executions"},
        {"step": "evidence", "endpoint": "POST /api/v1/executions/{execution_id}/evidence"},
        {"step": "replay_verify", "endpoint": "POST /api/v1/executions/{execution_id}/verify"},
        {"step": "proof", "endpoint": "GET /api/v1/proofs/{proof_id}"},
    ]


__all__ = [
    "approve_plan",
    "create_plan",
    "derive_decision",
    "flow_definition",
    "read_execution",
    "read_plan",
    "read_proof",
    "record_execution",
    "store_summary",
    "submit_evidence",
    "verify_constraints",
    "verify_execution",
    "verify_plan_alignment",
]
