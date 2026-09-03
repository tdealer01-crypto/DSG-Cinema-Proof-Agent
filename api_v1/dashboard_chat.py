"""Account-scoped chat and five-panel live monitor for the customer dashboard.

This module is a transport, not an AI model. The browser posts user messages to
an authenticated queue and an already-paired MCP agent reads/replies through
explicit tools. That keeps the user on /dashboard without pretending that a
model is connected when no agent client has contacted Cinema.

The five monitor panels render only durable Cinema state: browser activity,
approved-plan binding, Remote authority, action evidence, and execution/audit
records. Direct user browser input is recorded only as actor + action kind +
sanitized page URL; typed text, coordinates, passwords, OTPs and form values are
never written here.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import Field

from . import agent_pairing, remote_browser, remote_pairing, service
from .canonical import utc_now
from .models import ApprovePlanRequest, PlanDocument, Strict

router = APIRouter(prefix="/dashboard/api", tags=["dashboard"])
_lock = threading.RLock()
_MAX_MESSAGES = 300
_MAX_ACTIVITY = 200


class UserMessage(Strict):
    text: str = Field(min_length=1, max_length=8000)


class ApprovalDecision(Strict):
    message_id: str = Field(min_length=1, max_length=96)
    decision: Literal["approve", "reject"]


class ChatReceiveArgs(Strict):
    after_seq: int = Field(default=0, ge=0)
    limit: int = Field(default=30, ge=1, le=100)


class ChatReplyArgs(Strict):
    text: str = Field(min_length=1, max_length=12000)


class ChatApprovalArgs(Strict):
    plan_id: str = Field(min_length=1, max_length=64)
    plan_hash: str = Field(min_length=64, max_length=128)
    summary: str = Field(min_length=1, max_length=4000)


class ChatPlanArgs(Strict):
    plan: PlanDocument
    summary: str = Field(min_length=1, max_length=4000)
    fallback_targets: list[str] = Field(default_factory=list, max_length=8)


def _account(api_key: Optional[str]) -> tuple[str, str]:
    key, account = agent_pairing._authenticated_account(api_key)
    return key, str(account.account_id)


def _root() -> Path:
    path = remote_browser._ensure_store() / "dashboard"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(account_id: str) -> Path:
    digest = hashlib.sha256(account_id.encode("utf-8")).hexdigest()
    return _root() / f"{digest}.json"


def _empty(account_id: str) -> dict[str, Any]:
    return {"account_id": account_id, "seq": 0, "messages": [], "activity": [], "updated_at": None}


def _read(account_id: str) -> dict[str, Any]:
    path = _path(account_id)
    if not path.exists():
        return _empty(account_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="dashboard state is unreadable") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=503, detail="dashboard state is invalid")
    value.setdefault("account_id", account_id)
    value.setdefault("seq", 0)
    value.setdefault("messages", [])
    value.setdefault("activity", [])
    return value


def _write(account_id: str, state: dict[str, Any]) -> None:
    path = _path(account_id)
    state["account_id"] = account_id
    state["updated_at"] = utc_now()
    temp = path.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        temp.replace(path)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="dashboard state could not be persisted") from exc


def _append_message(
    account_id: str,
    *,
    role: Literal["user", "agent", "system"],
    text: str,
    agent_name: str | None = None,
    approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _lock:
        state = _read(account_id)
        seq = int(state.get("seq", 0)) + 1
        message = {
            "message_id": f"chat_{uuid.uuid4().hex}",
            "seq": seq,
            "role": role,
            "text": text,
            "agent_name": agent_name,
            "approval": approval,
            "created_at": utc_now(),
        }
        messages = list(state.get("messages") or [])
        messages.append(message)
        state["messages"] = messages[-_MAX_MESSAGES:]
        state["seq"] = seq
        _write(account_id, state)
        return message


def record_user_activity(account_id: str, kind: str, *, url: str | None = None) -> dict[str, Any]:
    """Record only safe user-input metadata for the shared-screen monitor."""
    with _lock:
        state = _read(account_id)
        event = {
            "activity_id": f"uact_{uuid.uuid4().hex}",
            "actor": "USER",
            "controller": "user",
            "action": str(kind)[:128],
            "url": str(url)[:2048] if isinstance(url, str) else None,
            "created_at": utc_now(),
        }
        items = list(state.get("activity") or [])
        items.append(event)
        state["activity"] = items[-_MAX_ACTIVITY:]
        _write(account_id, state)
        return event


def _latest_user_activity(account_id: str) -> dict[str, Any] | None:
    state = _read(account_id)
    items = list(state.get("activity") or [])
    return items[-1] if items else None


def _latest_agent_event(session_ids: list[str]) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    latest_mtime = -1.0
    root = remote_browser._ensure_store() / "events"
    for session_id in session_ids:
        folder = root / session_id
        if not folder.exists():
            continue
        for path in folder.glob("*.json"):
            try:
                mtime = path.stat().st_mtime
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(value, dict) and mtime > latest_mtime:
                latest = value
                latest_mtime = mtime
    return latest


def _iso_epoch(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        from datetime import datetime

        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _plan_panel(state: dict[str, Any], event: dict[str, Any] | None) -> dict[str, Any]:
    plan_id = str((event or {}).get("plan_id") or state.get("last_plan_id") or "").strip()
    if not plan_id:
        return {"status": "PENDING", "plan_id": None, "detail": "No approved plan is bound yet."}
    try:
        plan = service.read_plan(plan_id)
    except Exception:
        return {"status": "UNAVAILABLE", "plan_id": plan_id, "detail": "The bound plan could not be read."}
    status = str(plan.get("status") or "")
    return {
        "status": "PASS" if status == service.STATUS_APPROVED else status or "PENDING",
        "plan_id": plan_id,
        "plan_hash": plan.get("plan_hash"),
        "detail": "Exact approved plan binding is active." if status == service.STATUS_APPROVED else "Plan approval is not complete.",
    }


def monitor_snapshot(account_id: str) -> dict[str, Any]:
    state = remote_pairing._read_state(account_id)
    active = remote_pairing._active_sessions(state)
    agent_event = _latest_agent_event(active)
    user_event = _latest_user_activity(account_id)
    use_user = bool(user_event) and _iso_epoch(user_event.get("created_at")) >= _iso_epoch((agent_event or {}).get("recorded_at") or (agent_event or {}).get("finished_at"))

    if use_user:
        action = {
            "status": "OBSERVED",
            "actor": "USER",
            "controller": "user",
            "action": user_event.get("action"),
            "target": user_event.get("url"),
            "event_id": user_event.get("activity_id"),
            "created_at": user_event.get("created_at"),
        }
    elif agent_event:
        raw_action = agent_event.get("action") if isinstance(agent_event.get("action"), dict) else {}
        params = raw_action.get("parameters") if isinstance(raw_action, dict) else {}
        target = None
        if isinstance(params, dict):
            target = params.get("url") or params.get("target") or params.get("selector")
        action = {
            "status": str(agent_event.get("state") or "OBSERVED"),
            "actor": str(agent_event.get("actor") or "AGENT"),
            "controller": agent_event.get("controller"),
            "action": raw_action.get("kind") if isinstance(raw_action, dict) else None,
            "target": target,
            "event_id": agent_event.get("event_id"),
            "created_at": agent_event.get("finished_at") or agent_event.get("recorded_at"),
        }
    else:
        action = {"status": "WAITING", "actor": None, "controller": None, "action": None, "target": None, "event_id": None, "created_at": None}

    plan = _plan_panel(state, agent_event)
    enabled = bool(state.get("enabled"))
    auto_error = state.get("last_auto_connect_error") if isinstance(state.get("last_auto_connect_error"), dict) else None
    if auto_error:
        permission = {"status": "BLOCKED", "detail": str(auto_error.get("error") or "Remote binding failed"), "active_sessions": len(active)}
    elif not enabled:
        permission = {"status": "REMOTE_OFF", "detail": "User has not granted Remote authority.", "active_sessions": 0}
    elif not active:
        permission = {"status": "WAITING_AGENT", "detail": "Remote is ON; waiting for a paired agent to claim the approved step.", "active_sessions": 0}
    else:
        permission = {"status": "PASS", "detail": "Plan-bound Remote authority is active.", "active_sessions": len(active)}

    evidence_hash = (agent_event or {}).get("evidence_hash")
    evidence = {
        "status": "RECORDED" if isinstance(evidence_hash, str) and evidence_hash else "PENDING",
        "evidence_hash": evidence_hash,
        "event_id": (agent_event or {}).get("event_id"),
        "detail": "Durable remote-action evidence recorded." if evidence_hash else "No completed agent action evidence yet.",
    }
    execution_state = str((agent_event or {}).get("state") or "WAITING")
    execution = {
        "status": execution_state,
        "remote_status": (agent_event or {}).get("remote_status"),
        "response_sha256": (agent_event or {}).get("response_sha256"),
        "event_id": (agent_event or {}).get("event_id"),
        "recorded_at": (agent_event or {}).get("recorded_at"),
        "finished_at": (agent_event or {}).get("finished_at"),
        "detail": "Audit comes from the durable Remote Browser event record." if agent_event else "No agent execution has been recorded yet.",
    }
    return {
        "ok": True,
        "remote_enabled": enabled,
        "agent_connection": "connected" if enabled and active else ("waiting" if enabled else "off"),
        "panels": {
            "action": action,
            "plan_alignment": plan,
            "permission": permission,
            "evidence": evidence,
            "execution_audit": execution,
        },
    }


@router.get("/chat/messages")
async def chat_messages(
    after_seq: int = 0,
    limit: int = 100,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    _, account_id = _account(x_dsg_api_key)
    state = _read(account_id)
    items = [item for item in state.get("messages", []) if int(item.get("seq", 0)) > max(0, after_seq)]
    return {"ok": True, "messages": items[: max(1, min(limit, 100))], "last_seq": int(state.get("seq", 0))}


@router.post("/chat/messages", status_code=201)
async def post_user_message(
    body: UserMessage,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    _, account_id = _account(x_dsg_api_key)
    message = _append_message(account_id, role="user", text=body.text.strip())
    return {"ok": True, "message": message, "delivery": "queued_for_paired_agent"}


@router.post("/chat/approval")
async def decide_approval(
    body: ApprovalDecision,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    key, account_id = _account(x_dsg_api_key)
    with _lock:
        state = _read(account_id)
        messages = list(state.get("messages") or [])
        message = next((item for item in messages if item.get("message_id") == body.message_id), None)
        if not isinstance(message, dict) or not isinstance(message.get("approval"), dict):
            raise HTTPException(status_code=404, detail="approval request was not found")
        approval = dict(message["approval"])
        if approval.get("status") != "pending":
            return {"ok": True, "approval": approval, "idempotent": True}
        if body.decision == "reject":
            approval["status"] = "rejected"
            approval["decided_at"] = utc_now()
            message["approval"] = approval
            _write(account_id, state)
            _append_message(account_id, role="system", text=f"Plan {approval['plan_id']} was rejected by the user.")
            return {"ok": True, "approval": approval}

        plan_id = str(approval.get("plan_id") or "")
        plan_hash = str(approval.get("plan_hash") or "")
        record = service.get_plan_record(plan_id)
        if str(record.get("plan_hash") or "") != plan_hash:
            raise HTTPException(status_code=409, detail="approval plan hash no longer matches the stored plan")
        if str(record.get("status") or "") != service.STATUS_APPROVED:
            service.approve_plan(
                plan_id,
                ApprovePlanRequest(approver="dashboard-user", plan_hash=plan_hash, approval_note="Approved from unified /dashboard chat"),
            )
        agent_pairing._remember_approved_binding(key, plan_id)
        approval["status"] = "approved"
        approval["decided_at"] = utc_now()
        message["approval"] = approval
        _write(account_id, state)
    _append_message(account_id, role="system", text=f"Plan {plan_id} approved. The paired agent can continue on the exact approved step.")
    return {"ok": True, "approval": approval, "plan": service.read_plan(plan_id)}


@router.get("/monitor")
async def monitor(
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    _, account_id = _account(x_dsg_api_key)
    return monitor_snapshot(account_id)


def _mcp_account() -> tuple[str, str, str]:
    from . import remote_mcp

    key, account_id = _account(remote_mcp._current_api_key())
    agent_name = remote_mcp._current_agent_name() or "paired-agent"
    return key, account_id, agent_name


async def _mcp_receive(args: ChatReceiveArgs) -> dict[str, Any]:
    _, account_id, _ = _mcp_account()
    state = _read(account_id)
    items = [
        item for item in state.get("messages", [])
        if int(item.get("seq", 0)) > args.after_seq and item.get("role") in {"user", "agent", "system"}
    ]
    return {"messages": items[: args.limit], "last_seq": int(state.get("seq", 0)), "instruction": "Reply with dashboard_chat_reply. If an exact plan needs user approval, call dashboard_chat_request_approval."}


async def _mcp_reply(args: ChatReplyArgs) -> dict[str, Any]:
    _, account_id, agent_name = _mcp_account()
    return {"ok": True, "message": _append_message(account_id, role="agent", text=args.text.strip(), agent_name=agent_name)}


async def _mcp_create_plan(args: ChatPlanArgs) -> dict[str, Any]:
    """Create a draft plan and expose it as a user approval card.

    The paired agent may propose a plan, but only the dashboard user can approve
    it.  Binding is recorded by ``decide_approval`` after that approval.
    """
    key, account_id, agent_name = _mcp_account()
    # A web-search task must remain useful when the primary provider blocks,
    # rate-limits, or is unavailable.  The agent supplies lawful alternatives;
    # we materialize them as auditable steps rather than silently navigating to
    # an unapproved origin after execution has started.
    plan_document = args.plan.model_copy(deep=True)
    browser_steps = [
        step
        for step in plan_document.steps
        if step.action == "browser_workflow" or step.action.startswith("browser.")
    ]
    if browser_steps and args.fallback_targets:
        used = {step.step_id for step in plan_document.steps}
        for index, target in enumerate(args.fallback_targets, start=1):
            step_id = f"fallback-{index}"
            while step_id in used:
                index += 1
                step_id = f"fallback-{index}"
            used.add(step_id)
            source = browser_steps[min(index - 1, len(browser_steps) - 1)]
            plan_document.steps.append(
                source.model_copy(
                    update={
                        "step_id": step_id,
                        "target": target,
                        "description": f"Fallback source if the primary source is unavailable: {target}",
                    }
                )
            )
        plan_document.metadata["fallback_strategy"] = "try_in_order_and_stop_on_first_usable_source"
        plan_document.metadata["fallback_targets"] = ",".join(args.fallback_targets)
    plan = service.create_plan(plan_document)
    message = _append_message(
        account_id,
        role="agent",
        text=f"Plan proposed: {args.summary}",
        agent_name=agent_name,
        approval={
            "status": "pending",
            "plan_id": plan["plan_id"],
            "plan_hash": plan["plan_hash"],
            "summary": args.summary,
        },
    )
    return {"ok": True, "plan": plan, "message": message, "requires_user_approval": True}


async def _mcp_request_approval(args: ChatApprovalArgs) -> dict[str, Any]:
    _, account_id, agent_name = _mcp_account()
    record = service.get_plan_record(args.plan_id)
    stored_hash = str(record.get("plan_hash") or "")
    if not stored_hash or stored_hash != args.plan_hash:
        raise HTTPException(status_code=409, detail="requested approval hash does not match the stored Cinema plan")
    approval = {"status": "pending", "plan_id": args.plan_id, "plan_hash": args.plan_hash, "summary": args.summary}
    message = _append_message(
        account_id,
        role="agent",
        text=f"Approval required: {args.summary}",
        agent_name=agent_name,
        approval=approval,
    )
    return {"ok": True, "message": message, "approval_required": True}


def install_mcp_tools() -> None:
    from . import remote_mcp

    if "dashboard_chat_receive" in remote_mcp._BY_NAME:
        return
    tools = (
        remote_mcp._Tool(
            "dashboard_chat_receive",
            "Read new user/system messages from the unified /dashboard conversation for this paired account. Use after_seq to poll without duplicates.",
            ChatReceiveArgs,
            _mcp_receive,
            read_only=True,
            idempotent=True,
            open_world=False,
        ),
        remote_mcp._Tool(
            "dashboard_chat_reply",
            "Send an agent reply into the user's unified /dashboard conversation. Do not claim an action succeeded unless Cinema evidence supports it.",
            ChatReplyArgs,
            _mcp_reply,
            read_only=False,
            idempotent=False,
            open_world=False,
        ),
        remote_mcp._Tool(
            "dashboard_chat_create_plan",
            "Create a detailed universal task plan from the paired agent and show an approval card. For web search tasks, always provide lawful fallback_targets so blocked or unavailable sites are tried in order. The user must approve before remote browser execution.",
            ChatPlanArgs,
            _mcp_create_plan,
            read_only=False,
            idempotent=False,
            open_world=False,
        ),
        remote_mcp._Tool(
            "dashboard_chat_request_approval",
            "Show an inline Approve/Reject control in /dashboard for the exact stored plan_id and plan_hash. The user decision is authoritative; never self-approve.",
            ChatApprovalArgs,
            _mcp_request_approval,
            read_only=False,
            idempotent=False,
            open_world=False,
        ),
    )
    for tool in tools:
        remote_mcp.TOOLS = (*remote_mcp.TOOLS, tool)
        remote_mcp._BY_NAME[tool.name] = tool


def install(app) -> None:
    app.include_router(router)
    install_mcp_tools()


__all__ = ["install", "install_mcp_tools", "monitor_snapshot", "record_user_activity", "router"]
