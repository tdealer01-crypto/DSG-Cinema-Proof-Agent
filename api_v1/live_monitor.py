"""DSG Live: session-scoped observe/enforce decisions with customer-readable evidence.

This module does not create a second policy engine. Every action is classified by
`evaluate_unified_preflight`, the same decision core used by REST/MCP control.
Live mode changes only the *effect* around that decision:

- OBSERVE: classify and record; DSG does not stop the customer runtime.
- ENFORCE: ALLOW executes, WAITING_PERMISSION waits, BLOCK stops.

Replay is verification-only. This module never re-executes an action.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import Field

from revenue import api as billing

from . import service
from .canonical import canonical_hash, new_id, utc_now
from .control import UnifiedPreflightRequest, evaluate_unified_preflight
from .evidence import assess_evidence, assess_replay
from .models import ObservedAction, Strict
from .store import get_store

router = APIRouter(prefix="/api/v1/live", tags=["dsg-live"])

LIVE_TOKEN_HEADER = "X-DSG-Live-Token"
DEFAULT_TTL_SECONDS = 8 * 60 * 60
MAX_TTL_SECONDS = 24 * 60 * 60
DEFAULT_MONITOR_ORIGIN = "https://dsgoneverifiedweb.z1.web.core.windows.net"


class LiveStartRequest(Strict):
    display_name: str = Field(default="DSG Live", min_length=1, max_length=255)
    ttl_seconds: int = Field(default=DEFAULT_TTL_SECONDS, ge=300, le=MAX_TTL_SECONDS)


class LiveModeRequest(Strict):
    mode: Literal["observe", "enforce"]


class LiveCheckToolArgs(UnifiedPreflightRequest):
    live_session_token: str = Field(min_length=32, max_length=256)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _monitor_origin() -> str:
    return (os.getenv("DSG_LIVE_MONITOR_ORIGIN") or DEFAULT_MONITOR_ORIGIN).strip().rstrip("/")


def _iso_from_epoch(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _public_session(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": record["session_id"],
        "display_name": record["display_name"],
        "mode": record["mode"].upper(),
        "created_at": record["created_at"],
        "expires_at": _iso_from_epoch(int(record["expires_at_epoch"])),
        "events": int(record.get("events", 0)),
    }


def create_live_session(request: LiveStartRequest, *, account_id: str | None = None) -> dict[str, Any]:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    session_id = new_id("live")
    record = {
        "session_id": session_id,
        "display_name": request.display_name,
        "mode": "observe",
        "token_hash": _token_hash(token),
        "account_id": account_id,
        "created_at": utc_now(),
        "expires_at_epoch": now + request.ttl_seconds,
        "events": 0,
        "last_event_at": None,
    }
    get_store().put("live_sessions", session_id, record)
    return {
        "ok": True,
        "live_session_token": token,
        "monitor_url": f"{_monitor_origin()}/live.html#{token}",
        "session": _public_session(record),
        "next_step": (
            "Use dsg_live_check_action before each action. The session starts in OBSERVE mode, "
            "so DSG classifies and records without stopping the customer runtime."
        ),
        "truth_boundary": (
            "The token is a temporary session capability. Keep it secret. DSG stores only its SHA-256 hash."
        ),
    }


def _session_for_token(token: str) -> dict[str, Any]:
    supplied_hash = _token_hash(token)
    now = int(time.time())
    for session in get_store().list_records("live_sessions"):
        stored_hash = str(session.get("token_hash") or "")
        if stored_hash and hmac.compare_digest(stored_hash, supplied_hash):
            if int(session.get("expires_at_epoch") or 0) <= now:
                raise HTTPException(status_code=401, detail="DSG Live session expired")
            return session
    raise HTTPException(status_code=401, detail="invalid DSG Live session token")


def _governance_status(result: dict[str, Any]) -> str:
    decision = str(result.get("decision") or "")
    if decision == "ALLOW":
        return "PASS"
    if decision == "WAITING_PERMISSION":
        return "MISSING_PERMISSION"
    code = str(result.get("code") or "")
    if code in {"OUT_OF_PLAN_ACTION", "PARAMETER_MISMATCH", "UNKNOWN_STEP_ID", "STEP_REPEATED", "UNDECLARED_PARAMETER"}:
        return "OUTSIDE_PLAN"
    return "BLOCKED"


def _reason(result: dict[str, Any]) -> str:
    explicit = result.get("reason")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    decision = result.get("decision")
    if decision == "ALLOW":
        return "The action matches the approved plan and required capabilities are available."
    if decision == "WAITING_PERMISSION":
        pending = result.get("pending_capabilities") or []
        names = [str(item.get("capability")) for item in pending if isinstance(item, dict) and item.get("capability")]
        suffix = f": {', '.join(names)}" if names else ""
        return f"The action is plan-authorized but required capability is not available{suffix}."
    return str(result.get("next_step") or "DSG did not authorize this action.")


def _effect(mode: str, result: dict[str, Any]) -> dict[str, Any]:
    decision = str(result.get("decision") or "BLOCK")
    if mode == "observe":
        return {
            "execution_instruction": "CONTINUE",
            "effect": "NOT_STOPPED_OBSERVE",
            "enforcement_applied": False,
            "message": "DSG recorded the governance result but did not stop this action.",
        }
    if decision == "ALLOW":
        return {
            "execution_instruction": "EXECUTE",
            "effect": "ALLOWED_BY_DSG",
            "enforcement_applied": True,
            "message": "DSG authorized this exact approved action.",
        }
    if decision == "WAITING_PERMISSION":
        return {
            "execution_instruction": "WAIT",
            "effect": "WAITING_PERMISSION",
            "enforcement_applied": True,
            "message": "Keep the approved action pending until the required capability is available.",
        }
    return {
        "execution_instruction": "STOP",
        "effect": "BLOCKED_BY_DSG",
        "enforcement_applied": True,
        "message": "DSG stopped this action because it is not authorized by the current governance state.",
    }


def _action_trace_hash(result: dict[str, Any]) -> str | None:
    direct = result.get("action_trace_hash")
    if isinstance(direct, str):
        return direct
    grant = result.get("capability_grant")
    if isinstance(grant, dict):
        scope = grant.get("scope")
        if isinstance(scope, dict) and isinstance(scope.get("action_trace_hash"), str):
            return str(scope["action_trace_hash"])
    return None


def _record_event(
    session: dict[str, Any],
    request: UnifiedPreflightRequest,
    result: dict[str, Any],
) -> dict[str, Any]:
    effect = _effect(str(session["mode"]), result)
    event_id = new_id("liveevt")
    action = request.action
    record = {
        "event_id": event_id,
        "session_id": session["session_id"],
        "plan_id": request.plan_id,
        "agent_identity": request.agent_identity,
        "step_id": action.step_id,
        "action": action.action,
        "target": action.target,
        "parameters_hash": canonical_hash(action.parameters),
        "action_trace_hash": _action_trace_hash(result),
        "channel": request.channel,
        "trace_id": request.trace_id,
        "mode": session["mode"],
        "decision": result.get("decision"),
        "governance_status": _governance_status(result),
        "decision_code": result.get("code"),
        "reason": _reason(result),
        "effect": effect["effect"],
        "execution_instruction": effect["execution_instruction"],
        "enforcement_applied": effect["enforcement_applied"],
        "control_hash": result.get("control_hash"),
        "created_at": utc_now(),
    }
    store = get_store()
    store.put("live_events", event_id, record)

    def _increment(current: dict[str, Any]) -> dict[str, Any]:
        current["events"] = int(current.get("events", 0)) + 1
        current["last_event_at"] = record["created_at"]
        return current

    store.mutate("live_sessions", session["session_id"], _increment)
    return record


def check_live_action(token: str, request: UnifiedPreflightRequest) -> dict[str, Any]:
    session = _session_for_token(token)
    result = evaluate_unified_preflight(request)
    event = _record_event(session, request, result)
    effect = _effect(str(session["mode"]), result)
    return {
        **result,
        "live": {
            "session_id": session["session_id"],
            "event_id": event["event_id"],
            "mode": str(session["mode"]).upper(),
            "governance_status": event["governance_status"],
            **effect,
        },
    }


def set_live_mode(token: str, mode: Literal["observe", "enforce"]) -> dict[str, Any]:
    session = _session_for_token(token)

    def _set(current: dict[str, Any]) -> dict[str, Any]:
        current["mode"] = mode
        current["mode_changed_at"] = utc_now()
        return current

    updated = get_store().mutate("live_sessions", session["session_id"], _set)
    assert updated is not None
    return {
        "ok": True,
        "session": _public_session(updated),
        "effect": (
            "DSG will classify and record without stopping customer execution."
            if mode == "observe"
            else "Future dsg_live_check_action calls will return EXECUTE, WAIT, or STOP instructions from the DSG decision core."
        ),
    }


def _matching_execution(event: dict[str, Any]) -> dict[str, Any] | None:
    executions = get_store().list_records("executions")
    trace_id = event.get("trace_id")
    action_trace_hash = event.get("action_trace_hash")
    candidates: list[dict[str, Any]] = []
    for execution in executions:
        if execution.get("plan_id") != event.get("plan_id"):
            continue
        if execution.get("agent_identity") != event.get("agent_identity"):
            continue
        if trace_id:
            if execution.get("trace_id") == trace_id:
                candidates.append(execution)
        elif action_trace_hash and execution.get("action_trace_hash") == action_trace_hash:
            candidates.append(execution)
    if not candidates:
        return None
    candidates.sort(key=lambda item: str(item.get("recorded_at") or ""), reverse=True)
    return candidates[0]


def _evidence_view(event: dict[str, Any]) -> dict[str, Any]:
    execution = _matching_execution(event)
    if execution is None:
        return {
            "status": "UNVERIFIED",
            "execution_id": None,
            "evidence": "PENDING",
            "replay": "NOT_VERIFIED",
            "proof": "PENDING",
            "detail": "No recorded execution is linked to this live action yet.",
        }

    try:
        plan_record = service.get_plan_record(str(execution["plan_id"]))
        document = service.plan_document(plan_record)
        actions = [ObservedAction.model_validate(item) for item in execution.get("actions", [])]
        artifacts = execution.get("evidence", [])
        evidence = assess_evidence(document, actions, artifacts)
        replay = assess_replay(document, actions, artifacts)
    except Exception:
        return {
            "status": "UNVERIFIED",
            "execution_id": execution.get("execution_id"),
            "evidence": "UNVERIFIED",
            "replay": "NOT_VERIFIED",
            "proof": "PENDING",
            "detail": "Stored execution exists but its evidence view could not be recomputed.",
        }

    execution_status = str(execution.get("status") or "")
    if execution_status in {service.STATUS_EVIDENCE_SUBMITTED, service.STATUS_VERIFIED}:
        replay_status = "REPLAY_VERIFIED" if replay["replay_match"] else "REPLAY_FAILED"
    else:
        replay_status = "NOT_VERIFIED"

    proof_status = "PENDING"
    proof_id = execution.get("proof_id")
    proof_hash = None
    receipt_hash_verified = None
    if proof_id:
        try:
            proof = service.read_proof(str(proof_id))
            proof_hash = proof.get("proof_hash")
            receipt_hash_verified = proof.get("receipt_hash_verified")
            if (
                proof.get("verified") is True
                and proof.get("verification") == "VERIFIED_GLOBAL_OPTIMUM"
                and receipt_hash_verified is True
            ):
                proof_status = "VERIFIED"
            else:
                proof_status = "FAILED"
        except Exception:
            proof_status = "FAILED"

    evidence_status = "VERIFIED" if evidence["evidence_complete"] else "UNVERIFIED"
    overall = "VERIFIED" if proof_status == "VERIFIED" else "UNVERIFIED"
    return {
        "status": overall,
        "execution_id": execution.get("execution_id"),
        "execution_status": execution_status,
        "evidence": evidence_status,
        "evidence_completeness": evidence["evidence_completeness"],
        "evidence_hash": evidence["evidence_hash"],
        "artifacts_total": evidence["artifacts_total"],
        "artifacts_content_verified": evidence["artifacts_content_verified"],
        "replay": replay_status,
        "replay_hash": replay["replay_hash"],
        "actions_checked": replay["actions_checked"],
        "actions_matched": replay["actions_matched"],
        "proof": proof_status,
        "proof_id": proof_id,
        "proof_hash": proof_hash,
        "receipt_hash_verified": receipt_hash_verified,
    }


def _public_event(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "plan_id": record["plan_id"],
        "agent_identity": record["agent_identity"],
        "step_id": record.get("step_id"),
        "action": record["action"],
        "target": record["target"],
        "parameters_hash": record["parameters_hash"],
        "channel": record["channel"],
        "trace_id": record.get("trace_id"),
        "mode": str(record["mode"]).upper(),
        "decision": record["decision"],
        "governance_status": record["governance_status"],
        "decision_code": record.get("decision_code"),
        "reason": record["reason"],
        "effect": record["effect"],
        "execution_instruction": record["execution_instruction"],
        "enforcement_applied": record["enforcement_applied"],
        "control_hash": record.get("control_hash"),
        "created_at": record["created_at"],
        "evidence": _evidence_view(record),
    }


def live_snapshot(token: str, limit: int = 50) -> dict[str, Any]:
    session = _session_for_token(token)
    events = [
        event
        for event in get_store().list_records("live_events")
        if event.get("session_id") == session["session_id"]
    ]
    events.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    selected = [_public_event(event) for event in events[: max(1, min(limit, 100))]]
    return {
        "ok": True,
        "session": _public_session(session),
        "latest": selected[0] if selected else None,
        "events": selected,
        "replay_semantics": "verification_only_no_execution",
    }


@router.get("/contract")
async def live_contract() -> dict[str, Any]:
    return {
        "product": "DSG Live",
        "flow": ["install", "start_live", "observe", "evidence", "choose_enforcement"],
        "default_mode": "OBSERVE",
        "panels": ["LIVE ACTION", "PLAN CHECK", "DSG EFFECT", "WHY", "EVIDENCE"],
        "decisions": ["PASS", "OUTSIDE_PLAN", "MISSING_PERMISSION", "BLOCKED"],
        "replay": "verification only; DSG Live never re-executes customer actions",
        "token_storage": "server stores SHA-256 only; monitor passes the token in X-DSG-Live-Token",
    }


@router.post("/sessions")
async def start_live_session(
    request: LiveStartRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    authorization = billing.authorize_request((x_dsg_api_key or "").strip() or None, service.VERIFIED_EXECUTION_SKU)
    account_id = None
    if authorization is not None and authorization.account is not None:
        account_id = authorization.account.account_id
    return create_live_session(request, account_id=account_id)


@router.post("/check")
async def live_check(
    request: UnifiedPreflightRequest,
    x_dsg_live_token: str = Header(alias=LIVE_TOKEN_HEADER),
) -> dict[str, Any]:
    return check_live_action(x_dsg_live_token, request)


@router.get("/events")
async def live_events(
    x_dsg_live_token: str = Header(alias=LIVE_TOKEN_HEADER),
    limit: int = 50,
) -> dict[str, Any]:
    return live_snapshot(x_dsg_live_token, limit=limit)


@router.post("/mode")
async def live_mode(
    request: LiveModeRequest,
    x_dsg_live_token: str = Header(alias=LIVE_TOKEN_HEADER),
) -> dict[str, Any]:
    return set_live_mode(x_dsg_live_token, request.mode)


async def _mcp_live_start(args: LiveStartRequest) -> dict[str, Any]:
    from . import mcp

    authorization = billing.authorize_request(mcp._current_api_key(), service.VERIFIED_EXECUTION_SKU)
    account_id = None
    if authorization is not None and authorization.account is not None:
        account_id = authorization.account.account_id
    return create_live_session(args, account_id=account_id)


async def _mcp_live_check(args: LiveCheckToolArgs) -> dict[str, Any]:
    payload = args.model_dump(mode="json")
    token = str(payload.pop("live_session_token"))
    request = UnifiedPreflightRequest.model_validate(payload)
    return check_live_action(token, request)


class LiveStatusArgs(Strict):
    live_session_token: str = Field(min_length=32, max_length=256)
    limit: int = Field(default=20, ge=1, le=100)


async def _mcp_live_status(args: LiveStatusArgs) -> dict[str, Any]:
    return live_snapshot(args.live_session_token, limit=args.limit)


def install_mcp_tools() -> None:
    from . import mcp

    if "dsg_live_start" in mcp._BY_NAME:
        return
    tools = (
        mcp._Tool(
            "dsg_live_start",
            "Start a temporary DSG Live session. It defaults to OBSERVE and returns a customer monitor URL plus a short-lived session token. Keep the token secret.",
            LiveStartRequest,
            _mcp_live_start,
        ),
        mcp._Tool(
            "dsg_live_check_action",
            "Classify one exact proposed action through the same DSG decision core and record it to the Live monitor. OBSERVE returns CONTINUE without suppressing BLOCK/MISSING_PERMISSION classification; ENFORCE returns EXECUTE, WAIT, or STOP.",
            LiveCheckToolArgs,
            _mcp_live_check,
        ),
        mcp._Tool(
            "dsg_live_status",
            "Read the current DSG Live session and customer-readable events, evidence state, and verification-only replay state for the supplied temporary session token.",
            LiveStatusArgs,
            _mcp_live_status,
        ),
    )
    for tool in tools:
        mcp.TOOLS = (*mcp.TOOLS, tool)
        mcp._BY_NAME[tool.name] = tool


def install(app) -> None:
    app.include_router(router)
    install_mcp_tools()


__all__ = [
    "LiveCheckToolArgs",
    "LiveModeRequest",
    "LiveStartRequest",
    "check_live_action",
    "create_live_session",
    "install",
    "live_snapshot",
    "router",
    "set_live_mode",
]
