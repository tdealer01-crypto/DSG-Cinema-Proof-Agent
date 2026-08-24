"""Plan-bound remote browser action surface for Cinema.

The remote browser is an execution tool, not a second policy engine. A session
is opened only against an approved Cinema plan step. Once opened, ordinary
browser/pointer/keyboard actions are relayed without per-click re-approval.

Hard boundaries remain:
- the approved plan/agent/step binding must be valid;
- the remote endpoint must be public HTTPS (no localhost/private-network SSRF);
- identity secrets are entered by the user directly in the shared browser, not
  copied through the agent payload;
- explicit attempts to bypass authorization, steal credentials, or tamper with
  audit/evidence are refused.

The user can disconnect Remote at any time. Revocation markers and action
records are stored on the durable Cinema volume so a container restart does not
silently restore agent control.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Header, HTTPException
from pydantic import Field, field_validator

from revenue import api as billing

from . import service
from .canonical import canonical_hash, utc_now
from .decision_core import CorePreflightRequest, evaluate_plan_authorization
from .models import ObservedAction, Scalar, Strict

router = APIRouter(prefix="/api/v1/remote-browser", tags=["remote-browser"])

REMOTE_PROTOCOL_VERSION = "dsg.remote-action.v1"
TOKEN_VERSION = 1
MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0

RemoteActionKind = Literal[
    "browser.navigate",
    "browser.click",
    "browser.type",
    "browser.select",
    "browser.scroll",
    "browser.extract",
    "browser.screenshot",
    "browser.upload",
    "browser.download",
    "browser.workflow",
    "pointer.move",
    "pointer.click",
    "pointer.drag",
    "keyboard.type",
    "keyboard.press",
]

_SENSITIVE_KEYS = {
    "password",
    "passcode",
    "otp",
    "captcha",
    "passkey",
    "private_key",
    "api_key",
    "secret",
    "security_key",
    "mfa_code",
    "2fa_code",
}

_HARD_INVARIANT = re.compile(
    r"(?:bypass|disable|evade|circumvent)\s+(?:security|authorization|permission|audit|governance)"
    r"|(?:steal|exfiltrate|harvest)\s+(?:password|credential|token|secret)"
    r"|(?:delete|erase|tamper|forge)\s+(?:audit|evidence|proof|log)\b"
    r"|unauthorized\s+access|credential\s+theft|phishing|malware",
    re.IGNORECASE,
)


class RemoteSessionCreate(Strict):
    plan_id: str = Field(min_length=1, max_length=64)
    agent_identity: str = Field(min_length=1, max_length=255)
    step_id: str = Field(min_length=1, max_length=64)
    remote_endpoint: str = Field(min_length=12, max_length=4096)
    ttl_seconds: int = Field(default=900, ge=60, le=3600)


class RemoteAction(Strict):
    kind: RemoteActionKind
    parameters: dict[str, Scalar] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def _bound_parameters(cls, value: dict[str, Scalar]) -> dict[str, Scalar]:
        if len(value) > 64:
            raise ValueError("a remote action carries at most 64 parameters")
        for key, item in value.items():
            if len(key) > 128:
                raise ValueError("remote action parameter names are at most 128 characters")
            if isinstance(item, str) and len(item) > 16384:
                raise ValueError("remote action string values are at most 16384 characters")
        return value


class RemoteActionRequest(Strict):
    session_token: str = Field(min_length=32, max_length=16384)
    action: RemoteAction


class RemoteDisconnectRequest(Strict):
    session_token: str = Field(min_length=32, max_length=16384)


def _api_key(value: Optional[str]) -> Optional[str]:
    return (value or "").strip() or None


def _store_root() -> Path:
    configured = (os.getenv("DSG_REMOTE_ACTION_STORE") or "").strip()
    return Path(configured or "/revenue/remote-action")


def _ensure_store() -> Path:
    root = _store_root()
    try:
        (root / "revoked").mkdir(parents=True, exist_ok=True)
        (root / "events").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "REMOTE_ACTION_STORAGE_UNAVAILABLE",
                "message": "Cinema cannot durably record remote browser authority/evidence",
            },
        ) from exc
    return root


def _token_secret() -> bytes:
    raw = (
        os.getenv("DSG_REMOTE_ACTION_KEY")
        or os.getenv("CINEMA_API_SECRET")
        or ""
    ).strip()
    if len(raw) < 32:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "REMOTE_ACTION_KEY_UNAVAILABLE",
                "message": "DSG_REMOTE_ACTION_KEY or CINEMA_API_SECRET must contain at least 32 characters",
            },
        )
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid remote session token") from exc


def _seal(payload: dict[str, Any]) -> str:
    nonce = os.urandom(12)
    plaintext = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(_token_secret()).encrypt(nonce, plaintext, REMOTE_PROTOCOL_VERSION.encode("ascii"))
    return _b64encode(nonce + ciphertext)


def _open(token: str) -> dict[str, Any]:
    raw = _b64decode(token)
    if len(raw) < 29:
        raise HTTPException(status_code=401, detail="invalid remote session token")
    nonce, ciphertext = raw[:12], raw[12:]
    try:
        plaintext = AESGCM(_token_secret()).decrypt(
            nonce,
            ciphertext,
            REMOTE_PROTOCOL_VERSION.encode("ascii"),
        )
        payload = json.loads(plaintext)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid remote session token") from exc
    if not isinstance(payload, dict) or payload.get("v") != TOKEN_VERSION:
        raise HTTPException(status_code=401, detail="unsupported remote session token")
    if int(payload.get("exp", 0)) <= int(time.time()):
        raise HTTPException(status_code=401, detail="remote session token expired")
    return payload


def _public_https_endpoint(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid remote endpoint") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise HTTPException(status_code=400, detail="remote endpoint must be public HTTPS")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="userinfo credentials are not allowed in remote endpoint URLs")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise HTTPException(status_code=400, detail="private/local remote endpoints are not allowed")

    try:
        literal = ipaddress.ip_address(host)
        addresses = [literal]
    except ValueError:
        try:
            resolved = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise HTTPException(status_code=400, detail="remote endpoint hostname did not resolve") from exc
        addresses = []
        for item in resolved:
            try:
                addresses.append(ipaddress.ip_address(item[4][0]))
            except ValueError:
                continue
        if not addresses:
            raise HTTPException(status_code=400, detail="remote endpoint hostname did not resolve to an IP address")

    for address in addresses:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise HTTPException(status_code=400, detail="remote endpoint resolves to a non-public address")

    # Fragments are client-only and must not be relayed. Query strings are kept
    # because many remote-browser providers use short-lived signed endpoint URLs.
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))


def _plan_step(plan_document: Any, step_id: str) -> Any:
    for step in plan_document.steps:
        if step.step_id == step_id:
            return step
    raise HTTPException(status_code=409, detail="step_id is not present in the approved plan")


def _authorize_session(request: RemoteSessionCreate) -> tuple[dict[str, Any], Any]:
    record = service.get_plan_record(request.plan_id)
    document = service.plan_document(record)
    step = _plan_step(document, request.step_id)
    action = ObservedAction(
        action=step.action,
        target=step.target,
        step_id=step.step_id,
        parameters=step.parameters,
        status="succeeded",
    )
    result = evaluate_plan_authorization(
        request=CorePreflightRequest(
            plan_id=record["plan_id"],
            plan_hash=record["plan_hash"],
            plan_status=record["status"],
            approved_agent_identity=document.agent_identity,
            agent_identity=request.agent_identity,
            action=action,
            capability_needs=[],
            channel="api",
            trace_id=f"remote-session:{uuid.uuid4().hex}",
            client_context={"surface": "remote_browser"},
        ),
        plan_document=document,
    )
    if not result.get("allowed"):
        raise HTTPException(status_code=409, detail=result)
    return result, step


def _revoked_path(session_id: str) -> Path:
    return _ensure_store() / "revoked" / session_id


def _is_revoked(session_id: str) -> bool:
    return _revoked_path(session_id).exists()


def _revoke(session_id: str) -> None:
    path = _revoked_path(session_id)
    path.write_text(utc_now(), encoding="utf-8")


def _direct_user_input(action: RemoteAction) -> bool:
    lowered = {key.lower() for key in action.parameters}
    if lowered.intersection(_SENSITIVE_KEYS):
        return True
    return bool(action.parameters.get("sensitive") is True)


def _hard_invariant_violation(action: RemoteAction) -> bool:
    material = [action.kind]
    for key, value in action.parameters.items():
        material.append(key)
        if isinstance(value, str):
            material.append(value)
    return bool(_HARD_INVARIANT.search(" ".join(material)))


def _validate_navigation(action: RemoteAction) -> None:
    if action.kind != "browser.navigate":
        return
    raw = action.parameters.get("url")
    if not isinstance(raw, str):
        raise HTTPException(status_code=400, detail="browser.navigate requires parameters.url")
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="browser navigation must target http(s)")


def _event_path(session_id: str, event_id: str) -> Path:
    path = _ensure_store() / "events" / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{event_id}.json"


def _write_event(path: Path, event: dict[str, Any]) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(event, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    temp.replace(path)


async def _relay(endpoint: str, payload: dict[str, Any]) -> tuple[int, str | dict[str, Any], str]:
    chunks: list[bytes] = []
    total = 0
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS, follow_redirects=False) as client:
            async with client.stream(
                "POST",
                endpoint,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                json=payload,
            ) as response:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        raise HTTPException(status_code=502, detail="remote endpoint response exceeded 1 MiB")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                response_sha256 = hashlib.sha256(raw).hexdigest()
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    try:
                        body: str | dict[str, Any] = json.loads(raw or b"{}")
                    except ValueError:
                        body = raw.decode("utf-8", errors="replace")
                else:
                    body = raw.decode("utf-8", errors="replace")
                return response.status_code, body, response_sha256
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="remote browser endpoint request failed") from exc


@router.get("/contract")
async def contract() -> dict[str, Any]:
    return {
        "protocol": REMOTE_PROTOCOL_VERSION,
        "semantics": "approved plan grants remote execution authority; no per-click approval cycle",
        "controllers": ["user", "agent"],
        "concurrency": "independent user and agent input channels may operate simultaneously",
        "remote_off": "revokes only agent remote authority; the user's browser session remains live",
        "identity_input": "password/OTP/CAPTCHA/passkey are entered directly by the user in the shared browser",
        "evidence": "each relayed action is recorded on durable Cinema storage with a canonical evidence hash",
    }


@router.post("/sessions", status_code=201)
async def create_session(
    request: RemoteSessionCreate,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    billing.authorize_request(_api_key(x_dsg_api_key), service.VERIFIED_EXECUTION_SKU)
    _ensure_store()
    endpoint = _public_https_endpoint(request.remote_endpoint)
    decision, step = _authorize_session(request)
    now = int(time.time())
    session_id = f"rbs_{uuid.uuid4().hex}"
    payload = {
        "v": TOKEN_VERSION,
        "sid": session_id,
        "plan_id": request.plan_id,
        "plan_hash": decision["plan_hash"],
        "agent_identity": request.agent_identity,
        "step_id": request.step_id,
        "step_action": step.action,
        "step_target": step.target,
        "endpoint": endpoint,
        "iat": now,
        "exp": now + request.ttl_seconds,
    }
    token = _seal(payload)
    return {
        "ok": True,
        "session_id": session_id,
        "session_token": token,
        "plan_id": request.plan_id,
        "plan_hash": decision["plan_hash"],
        "step_id": request.step_id,
        "agent_identity": request.agent_identity,
        "expires_at_unix": payload["exp"],
        "decision": "ALLOW",
        "control_hash": decision["control_hash"],
        "remote_enabled": True,
        "endpoint_exposed": False,
    }


@router.post("/actions")
async def execute_action(
    request: RemoteActionRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    billing.authorize_request(_api_key(x_dsg_api_key), service.VERIFIED_EXECUTION_SKU)
    session = _open(request.session_token)
    session_id = str(session["sid"])
    if _is_revoked(session_id):
        raise HTTPException(status_code=410, detail="remote authority was revoked by the user")
    if _direct_user_input(request.action):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "DIRECT_USER_INPUT_REQUIRED",
                "message": "Enter identity material directly in the shared browser; Remote stays connected.",
            },
        )
    if _hard_invariant_violation(request.action):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "HARD_INVARIANT_BLOCKED",
                "message": "Cinema refused an explicit authorization/security/audit integrity violation.",
            },
        )
    _validate_navigation(request.action)

    event_id = f"evt_{uuid.uuid4().hex}"
    event_path = _event_path(session_id, event_id)
    intent = {
        "event_id": event_id,
        "session_id": session_id,
        "state": "DISPATCHING",
        "plan_id": session["plan_id"],
        "plan_hash": session["plan_hash"],
        "agent_identity": session["agent_identity"],
        "step_id": session["step_id"],
        "action": request.action.model_dump(mode="json"),
        "recorded_at": utc_now(),
    }
    _write_event(event_path, intent)

    relay_payload = {
        "version": REMOTE_PROTOCOL_VERSION,
        "session_id": session_id,
        "context": {
            "plan_id": session["plan_id"],
            "plan_hash": session["plan_hash"],
            "agent_identity": session["agent_identity"],
            "step_id": session["step_id"],
        },
        "action": request.action.model_dump(mode="json"),
    }

    try:
        status_code, response_body, response_sha256 = await _relay(str(session["endpoint"]), relay_payload)
    except HTTPException as exc:
        failed = {
            **intent,
            "state": "DISPATCH_FAILED",
            "error": str(exc.detail),
            "finished_at": utc_now(),
        }
        failed["evidence_hash"] = canonical_hash(failed)
        _write_event(event_path, failed)
        raise

    completed = {
        **intent,
        "state": "COMPLETED" if 200 <= status_code < 300 else "REMOTE_REJECTED",
        "remote_status": status_code,
        "response_sha256": response_sha256,
        "finished_at": utc_now(),
    }
    completed["evidence_hash"] = canonical_hash(completed)
    _write_event(event_path, completed)

    return {
        "ok": 200 <= status_code < 300,
        "session_id": session_id,
        "event_id": event_id,
        "remote_status": status_code,
        "response": response_body,
        "response_sha256": response_sha256,
        "evidence_hash": completed["evidence_hash"],
        "plan_id": session["plan_id"],
        "plan_hash": session["plan_hash"],
        "step_id": session["step_id"],
        "remote_enabled": True,
    }


@router.post("/disconnect")
async def disconnect(
    request: RemoteDisconnectRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    billing.authorize_request(_api_key(x_dsg_api_key), service.VERIFIED_EXECUTION_SKU)
    session = _open(request.session_token)
    session_id = str(session["sid"])
    _revoke(session_id)
    return {
        "ok": True,
        "session_id": session_id,
        "remote_enabled": False,
        "browser_session_terminated": False,
        "message": "Agent remote authority revoked; the user's browser session remains live.",
    }


def install(app) -> None:
    app.include_router(router)


__all__ = [
    "REMOTE_PROTOCOL_VERSION",
    "RemoteAction",
    "RemoteActionRequest",
    "RemoteDisconnectRequest",
    "RemoteSessionCreate",
    "install",
    "router",
]
