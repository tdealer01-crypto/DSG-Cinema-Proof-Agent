"""Chat-driven Remote Browser pairing for Cinema.

The customer dashboard only arms/disarms remote authority. The agent that the
user is already talking to supplies the approved plan binding and the live
remote endpoint through the agent-facing connect route. This keeps technical
plan/step/endpoint fields out of the user UI without weakening plan-bound
execution.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException

from revenue import api as billing

from . import remote_browser, service
from .canonical import utc_now

router = APIRouter(prefix="/remote-browser", tags=["remote-browser"])


def _api_key(value: Optional[str]) -> str:
    key = (value or "").strip()
    if not key:
        raise HTTPException(status_code=401, detail="a valid X-DSG-API-Key header is required")
    return key


def _account_id(api_key: str) -> str:
    authorization = billing.authorize_request(api_key, service.VERIFIED_EXECUTION_SKU)
    if authorization is None or authorization.account is None:
        raise HTTPException(status_code=401, detail="an authenticated DSG account is required")
    return authorization.account.account_id


def _pairing_dir() -> Path:
    root = remote_browser._ensure_store() / "pairing"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "REMOTE_PAIRING_STORAGE_UNAVAILABLE",
                "message": "Cinema cannot durably store remote pairing state",
            },
        ) from exc
    return root


def _state_path(account_id: str) -> Path:
    digest = hashlib.sha256(account_id.encode("utf-8")).hexdigest()
    return _pairing_dir() / f"{digest}.json"


def _read_state(account_id: str) -> dict[str, Any]:
    path = _state_path(account_id)
    if not path.exists():
        return {
            "account_id": account_id,
            "enabled": False,
            "session_ids": [],
            "updated_at": None,
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="remote pairing state is unreadable") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=503, detail="remote pairing state is invalid")
    value.setdefault("account_id", account_id)
    value.setdefault("enabled", False)
    value.setdefault("session_ids", [])
    return value


def _write_state(account_id: str, state: dict[str, Any]) -> None:
    path = _state_path(account_id)
    temp = path.with_suffix(".tmp")
    payload = {**state, "account_id": account_id, "updated_at": utc_now()}
    try:
        temp.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        temp.replace(path)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="remote pairing state could not be persisted") from exc


def _active_sessions(state: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for raw in state.get("session_ids", []):
        session_id = str(raw)
        if session_id and not remote_browser._is_revoked(session_id):
            result.append(session_id)
    return result


def _latest_evidence(session_ids: list[str]) -> dict[str, Any] | None:
    latest_path: Path | None = None
    latest_mtime = -1.0
    root = remote_browser._ensure_store() / "events"
    for session_id in session_ids:
        session_dir = root / session_id
        if not session_dir.exists():
            continue
        for path in session_dir.glob("*.json"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > latest_mtime:
                latest_path = path
                latest_mtime = mtime
    if latest_path is None:
        return None
    try:
        value = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    return {
        "event_id": value.get("event_id"),
        "action_kind": value.get("action", {}).get("kind") if isinstance(value.get("action"), dict) else None,
        "evidence_hash": value.get("evidence_hash"),
        "recorded_at": value.get("recorded_at"),
    }


@router.post("/enable")
async def enable_remote(
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    key = _api_key(x_dsg_api_key)
    account_id = _account_id(key)
    state = _read_state(account_id)
    state["enabled"] = True
    state["session_ids"] = _active_sessions(state)
    _write_state(account_id, state)
    return {
        "remote_enabled": True,
        "agent_connection": "waiting" if not state["session_ids"] else "connected",
        "message": "Remote is ready. Continue in your agent chat; no plan IDs or endpoint fields are required here.",
    }


@router.get("/status")
async def remote_status(
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    key = _api_key(x_dsg_api_key)
    account_id = _account_id(key)
    state = _read_state(account_id)
    active = _active_sessions(state)
    if active != state.get("session_ids", []):
        state["session_ids"] = active
        _write_state(account_id, state)
    enabled = bool(state.get("enabled"))
    return {
        "remote_enabled": enabled,
        "agent_connection": "connected" if enabled and active else ("waiting" if enabled else "off"),
        "active_sessions": len(active),
        "latest_evidence": _latest_evidence(active),
        "updated_at": state.get("updated_at"),
    }


@router.post("/agent-connect", status_code=201)
async def agent_connect(
    request: remote_browser.RemoteSessionCreate,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    key = _api_key(x_dsg_api_key)
    account_id = _account_id(key)
    state = _read_state(account_id)
    if not bool(state.get("enabled")):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "REMOTE_NOT_ENABLED_BY_USER",
                "message": "The user has not enabled Remote for this account.",
            },
        )

    created = await remote_browser.create_session(request, key)
    sessions = _active_sessions(state)
    session_id = str(created["session_id"])
    if session_id not in sessions:
        sessions.append(session_id)
    state["session_ids"] = sessions
    state["last_agent_identity"] = request.agent_identity
    state["last_plan_id"] = request.plan_id
    state["last_step_id"] = request.step_id
    _write_state(account_id, state)
    return created


@router.post("/disable")
async def disable_remote(
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    key = _api_key(x_dsg_api_key)
    account_id = _account_id(key)
    state = _read_state(account_id)
    revoked = 0
    for session_id in _active_sessions(state):
        remote_browser._revoke(session_id)
        revoked += 1
    state["enabled"] = False
    state["session_ids"] = []
    _write_state(account_id, state)
    return {
        "remote_enabled": False,
        "agent_connection": "off",
        "revoked_sessions": revoked,
        "user_browser_session": "unchanged",
    }


def install(app) -> None:
    app.include_router(router)


__all__ = ["install", "router"]
