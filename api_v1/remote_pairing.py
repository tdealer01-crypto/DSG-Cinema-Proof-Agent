"""Chat-driven Remote Browser pairing for Cinema.

The customer dashboard arms/disarms agent remote authority. The user's managed
shared browser is account-scoped and persists independently from that authority,
so Remote ON can hand an approved plan to the agent without forcing the user
into a fresh browser/login flow.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException

from revenue import api as billing

from . import remote_browser, service, shared_browser
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


def _managed_cinema_endpoint(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme.lower() != "https":
        return False
    return parsed.path.startswith("/remote-browser/browserbase/action/") or parsed.path.startswith(
        "/remote-browser/azure/action/"
    )


async def _shared_browser(account_id: str, *, create: bool) -> dict[str, Any]:
    return await shared_browser.current_shared_browser(account_id, create=create)


@router.post("/enable")
async def enable_remote(
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    key = _api_key(x_dsg_api_key)
    account_id = _account_id(key)

    # Provision/resume the user's browser before granting agent remote authority.
    # If no managed provider is configured we retain the custom-executor path.
    shared = await _shared_browser(account_id, create=shared_browser.configured())

    state = _read_state(account_id)
    state["enabled"] = True
    state["session_ids"] = _active_sessions(state)
    _write_state(account_id, state)
    return {
        "remote_enabled": True,
        "agent_connection": "waiting" if not state["session_ids"] else "connected",
        "shared_browser": shared,
        "message": (
            "Remote is ON. Your shared browser stays yours; continue in the agent chat and "
            "the agent can join this same browser only through an approved plan."
        ),
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
        "shared_browser": await _shared_browser(account_id, create=False),
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
    session_id = str(created["session_id"])

    # Managed Cinema sessions join the account browser that the user already has
    # open. The browser is account-owned; only agent authority is plan-owned.
    if shared_browser.configured() and _managed_cinema_endpoint(request.remote_endpoint):
        created["shared_browser"] = await shared_browser.bind_cinema_session(
            account_id,
            session_id,
            plan_hash=str(created["plan_hash"]),
        )
        created["browser_continuity"] = "ACCOUNT_SCOPED_PERSISTENT_CONTEXT"

    sessions = _active_sessions(state)
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
        "shared_browser": await _shared_browser(account_id, create=False),
        "message": "Agent control is OFF. Your shared browser/login context remains available to you.",
    }


def install(app) -> None:
    app.include_router(router)


__all__ = ["install", "router"]
