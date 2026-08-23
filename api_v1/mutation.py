"""Guarded mutation execution: authorize, write, read back, answer with the row.

`/api/v1/control/preflight` says whether an action is allowed. This endpoint is
what happens next when the action actually changes something: DSG re-runs the
same Decision Core check, and only on `ALLOW` does it perform the mutation —
writing one tenant-bound guarded evidence row and reading it back inside the same
transaction.

What the caller gets is that read-back. Not an echo of the request, not a value
this process kept in a variable: the row as the database returned it, with its
`evidence_hash` recomputed from the read-back so a client can see that storage
and digest agree. `WAITING_PERMISSION` and `BLOCK` write nothing at all, because
an unauthorized mutation must not leave a record that looks like an authorized
one.

Idempotency is a database constraint, not a convention. `(tenant_id,
idempotency_key)` is unique, so a retried request returns the original row with
`created: false`, and the same key presented for a *different* action is refused
with `IDEMPOTENCY_KEY_CONFLICT` instead of silently returning the wrong receipt.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Response
from pydantic import Field, field_validator

from revenue import api as billing
from revenue.remediation import UNKNOWN_KEY

from . import guarded_store, service
from .canonical import canonical_hash, utc_now
from .capability_broker import CapabilityRequirement
from .control import UnifiedPreflightRequest, evaluate_unified_preflight
from .errors import (
    GUARDED_STORAGE_NOT_READY,
    IDEMPOTENCY_KEY_CONFLICT,
    MUTATION_NOT_FOUND,
    ApiError,
)
from .models import ObservedAction, Scalar, Strict
from .router import reject_agent_verdicts

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{7,127}$")

router = APIRouter(
    prefix="/api/v1/control",
    tags=["dsg-guarded-mutation"],
    dependencies=[Depends(reject_agent_verdicts)],
)


class GuardedMutationRequest(Strict):
    """One state-changing action the executor performed, offered for guarded record.

    `outputs` is the executor's own observed result. It is opaque data, stored as
    written and never read as a verdict.
    """

    plan_id: str = Field(min_length=1, max_length=64)
    agent_identity: str = Field(min_length=1, max_length=255)
    action: ObservedAction
    idempotency_key: str = Field(min_length=8, max_length=128)
    required_capabilities: list[CapabilityRequirement] = Field(default_factory=list, max_length=32)
    channel: str = Field(default="api", min_length=1, max_length=64)
    trace_id: str | None = Field(default=None, max_length=128)
    outputs: dict[str, Scalar] = Field(default_factory=dict)

    @field_validator("idempotency_key")
    @classmethod
    def _check_idempotency_key(cls, value: str) -> str:
        if not _IDEMPOTENCY_KEY.fullmatch(value):
            raise ValueError(f"idempotency_key must match {_IDEMPOTENCY_KEY.pattern}")
        return value

    @field_validator("outputs")
    @classmethod
    def _bound_outputs(cls, value: dict[str, Scalar]) -> dict[str, Scalar]:
        if len(value) > 32:
            raise ValueError("outputs carries at most 32 values")
        for name, item in value.items():
            if len(name) > 64:
                raise ValueError("output names are at most 64 characters")
            if isinstance(item, str) and len(item) > 512:
                raise ValueError("output values are at most 512 characters")
        return value


def action_hash(
    *,
    plan_id: str,
    plan_hash: str,
    agent_identity: str,
    channel: str,
    action: ObservedAction,
) -> str:
    """Digest of the mutation's identity — what an idempotency key is a name for.

    Deliberately excludes `outputs` and timestamps: a retry describes the same
    action, and a differing result is not what makes a key a lie about its scope.
    """
    return canonical_hash(
        {
            "plan_id": plan_id,
            "plan_hash": plan_hash,
            "agent_identity": agent_identity,
            "channel": channel,
            "step_id": action.step_id,
            "action": action.action,
            "target": action.target,
            "parameters": action.parameters,
        }
    )


def tenant_for(api_key: Optional[str]):
    """Resolve the tenant a guarded row will be bound to, or refuse the request.

    Entitlement is checked first so a suspended or over-quota account is denied
    with the billing vocabulary; identity is required after that, because there
    is no anonymous tenant a mutation row could belong to.
    """
    authorization = billing.authorize_request(api_key, service.VERIFIED_EXECUTION_SKU)
    account = authorization.account if authorization is not None else None
    if account is None:
        raise ApiError(
            401,
            UNKNOWN_KEY,
            "guarded mutations are recorded against a tenant, so a valid X-DSG-API-Key is required",
        )
    return account


def _require_durable_storage(store: Any) -> None:
    """Refuse memory-backed guarded mutations wherever billing is enforced."""
    if store.durable:
        return
    engine = billing.get_engine()
    if not getattr(engine, "enforcement_requested", False):
        return
    raise ApiError(
        503,
        GUARDED_STORAGE_NOT_READY,
        "paid enforcement is requested but guarded mutation evidence has no durable store",
        storage=store.summary(),
    )


def _observed(
    store: Any,
    record: dict[str, Any],
    *,
    created: Optional[bool] = None,
) -> dict[str, Any]:
    """The read-back plus a digest recomputed from it, never from the request."""
    recomputed = guarded_store.evidence_hash(record)
    body: dict[str, Any] = {
        "observed_evidence": record,
        "storage": store.summary(),
        "integrity": {
            "source": "read-back-from-store",
            "evidence_hash_recomputed": recomputed,
            "matches_stored": recomputed == record["evidence_hash"],
            "computed_by": "dsg-guarded-mutation",
        },
    }
    if created is not None:
        body["created"] = created
        body["replayed"] = not created
    return body


def execute_guarded_mutation(
    request: GuardedMutationRequest,
    *,
    api_key: Optional[str] = None,
) -> tuple[int, dict[str, Any]]:
    """Run the guarded mutation and return `(http_status, body)`."""
    account = tenant_for(api_key)
    store = guarded_store.get_guarded_store()
    _require_durable_storage(store)

    control = evaluate_unified_preflight(
        UnifiedPreflightRequest(
            plan_id=request.plan_id,
            agent_identity=request.agent_identity,
            action=request.action,
            required_capabilities=request.required_capabilities,
            channel=request.channel,
            trace_id=request.trace_id,
        )
    )

    envelope: dict[str, Any] = {
        "tenant_id": account.account_id,
        "idempotency_key": request.idempotency_key,
        "control": control,
        "computed_by": "dsg-guarded-mutation",
        "evaluated_at": utc_now(),
    }

    if control["decision"] != "ALLOW":
        envelope.update(
            executed=False,
            created=False,
            replayed=False,
            observed_evidence=None,
            storage=store.summary(),
            next_step=control["next_step"],
        )
        return 200, envelope

    digest = action_hash(
        plan_id=control["plan_id"],
        plan_hash=control["plan_hash"],
        agent_identity=request.agent_identity,
        channel=request.channel,
        action=request.action,
    )
    candidate = guarded_store.build_record(
        tenant_id=account.account_id,
        idempotency_key=request.idempotency_key,
        action_hash=digest,
        plan_id=control["plan_id"],
        plan_hash=control["plan_hash"],
        agent_identity=request.agent_identity,
        channel=request.channel,
        step_id=request.action.step_id,
        action=request.action.action,
        target=request.action.target,
        parameters=request.action.parameters,
        decision=control["decision"],
        control_hash=control["control_hash"],
        mutation_status=request.action.status,
        outputs=request.outputs,
    )

    try:
        record, created = store.record(candidate)
    except guarded_store.IdempotencyConflict as conflict:
        raise ApiError(
            409,
            IDEMPOTENCY_KEY_CONFLICT,
            str(conflict),
            tenant_id=conflict.tenant_id,
            idempotency_key=conflict.idempotency_key,
            stored_action_hash=conflict.stored_action_hash,
            submitted_action_hash=conflict.submitted_action_hash,
            stored_evidence_id=conflict.stored_evidence_id,
        ) from conflict

    envelope.update(
        executed=True,
        evidence_id=record["evidence_id"],
        action_hash=digest,
        next_step=(
            "Record the execution trace and submit evidence to obtain a proof receipt."
        ),
        **_observed(store, record, created=created),
    )
    return (201 if created else 200), envelope


def read_guarded_mutation(evidence_id: str, *, api_key: Optional[str] = None) -> dict[str, Any]:
    account = tenant_for(api_key)
    store = guarded_store.get_guarded_store()
    record = store.get(account.account_id, evidence_id)
    if record is None:
        # A row belonging to another tenant is indistinguishable from no row.
        raise ApiError(404, MUTATION_NOT_FOUND, f"no guarded mutation '{evidence_id}' for this tenant")
    body = {
        "tenant_id": account.account_id,
        "evidence_id": record["evidence_id"],
        "idempotency_key": record["idempotency_key"],
        "action_hash": record["action_hash"],
        "computed_by": "dsg-guarded-mutation",
        "read_at": utc_now(),
    }
    body.update(_observed(store, record))
    return body


@router.post("/mutations")
async def execute_mutation(
    request: GuardedMutationRequest,
    response: Response,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    status_code, body = execute_guarded_mutation(request, api_key=(x_dsg_api_key or "").strip() or None)
    response.status_code = status_code
    return body


@router.get("/mutations/{evidence_id}")
async def read_mutation(
    evidence_id: str,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    return read_guarded_mutation(evidence_id, api_key=(x_dsg_api_key or "").strip() or None)


def install(app) -> None:
    app.include_router(router)


__all__ = [
    "GuardedMutationRequest",
    "action_hash",
    "execute_guarded_mutation",
    "install",
    "read_guarded_mutation",
    "router",
]
