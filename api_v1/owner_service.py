"""Brokered OWNER service credential for trusted external agents.

The plaintext OWNER key is never stored in source or durable account storage.
Only a normal DSG account key id plus SHA-256(secret) are bootstrapped from a
non-secret config file. The account itself uses the existing durable revenue
account store, so all ordinary API-key, MCP, pairing, audit and plan gates stay
on the same authentication path.

For legacy revenue-admin endpoints that still require DSG_REVENUE_ADMIN_SECRET,
an authenticated OWNER request is translated server-side to that bearer secret.
The external agent never receives the admin master secret. This bridge is scoped
to the exact admin endpoints below and does not rewrite Authorization globally.

GitHub/Azure scopes are broker request authority, not a claim that the provider
credentials are configured. Provider capability readiness and existing approval
gates remain authoritative.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException

from revenue import api as billing
from revenue.accounts import Account, KEY_PATTERN, STATUS_ACTIVE

OWNER_CHANNEL = "owner_service"
OWNER_PLAN = "enterprise"
DEFAULT_SCOPES = ("dsg:*", "broker:github:*", "broker:azure:*")
_CONFIG_ENV = "DSG_OWNER_SERVICE_CONFIG"
_DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "owner-service-accounts.json"
_HEX_16 = re.compile(r"^[0-9a-f]{16}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_lock = threading.RLock()

# Keep OWNER observability outside /api/v1 so the independent verification
# OpenAPI remains exact. Authentication still applies to the existing /api/v1/mcp.
router = APIRouter(prefix="/owner-service", tags=["owner-service"])

# These are the current HTTP surfaces protected by DSG_REVENUE_ADMIN_SECRET.
# OWNER does not bypass their semantics; it only keeps the master bearer secret
# inside Cinema instead of putting it into an external agent connection.
_ADMIN_EXACT_PATHS = frozenset(
    {
        "/billing/report",
        "/billing/ledger/verify",
        "/billing/marketing/reconcile",
        "/marketplace/github/replay-pending",
    }
)


def _config_path() -> Path:
    configured = (os.getenv(_CONFIG_ENV) or "").strip()
    return Path(configured) if configured else _DEFAULT_CONFIG


def _load_records() -> list[dict[str, Any]]:
    path = _config_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise RuntimeError("OWNER service config is unreadable") from exc
    if not isinstance(payload, list):
        raise RuntimeError("OWNER service config must be a JSON array")

    records: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise RuntimeError("OWNER service account record must be an object")
        if any(name in raw for name in ("api_key", "secret", "plaintext_key")):
            raise RuntimeError("OWNER service config must never contain plaintext credentials")
        key_id = str(raw.get("key_id") or "").lower()
        secret_hash = str(raw.get("secret_hash") or "").lower()
        if not _HEX_16.fullmatch(key_id) or not _HEX_64.fullmatch(secret_hash):
            raise RuntimeError("OWNER service key id/hash is invalid")
        if str(raw.get("channel") or "") != OWNER_CHANNEL:
            raise RuntimeError("OWNER service account channel must be owner_service")
        if str(raw.get("plan") or "") != OWNER_PLAN:
            raise RuntimeError("OWNER service account plan must be enterprise")
        if str(raw.get("mode") or "") != "live":
            raise RuntimeError("OWNER service account mode must be live")
        if raw.get("unit_price_micros") != 0 or raw.get("hard_cap_units") is not None:
            raise RuntimeError("OWNER service account must be uncapped and zero-priced")
        scopes = raw.get("scopes", list(DEFAULT_SCOPES))
        if not isinstance(scopes, list) or not scopes or not all(isinstance(item, str) and item for item in scopes):
            raise RuntimeError("OWNER service scopes must be a non-empty string list")
        records.append({**raw, "key_id": key_id, "secret_hash": secret_hash, "scopes": scopes})
    return records


def _record_for_key(api_key: str) -> Optional[dict[str, Any]]:
    match = KEY_PATTERN.match((api_key or "").strip())
    if not match:
        return None
    mode, key_id, secret = match.groups()
    if mode != "live":
        return None
    for record in _load_records():
        if record["key_id"] != key_id:
            continue
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        if hmac.compare_digest(record["secret_hash"], digest):
            return record
    return None


def _account_payload(record: dict[str, Any]) -> dict[str, Any]:
    allowed = set(Account.__dataclass_fields__)
    return {name: value for name, value in record.items() if name in allowed}


def _ensure_account(record: dict[str, Any]) -> Account:
    """Import an immutable OWNER identity once without reactivating a revoked row."""
    engine = billing.get_engine()
    account_id = str(record.get("account_id") or "")
    if not account_id:
        raise RuntimeError("OWNER service account_id is required")

    with _lock:
        existing = engine.accounts.get(account_id)
        if existing is None:
            account = Account(**_account_payload(record))
            engine.accounts.import_account(account)
            existing = engine.accounts.get(account_id) or account
        immutable = {
            "account_id": account_id,
            "channel": OWNER_CHANNEL,
            "plan": OWNER_PLAN,
            "mode": "live",
            "key_id": record["key_id"],
            "secret_hash": record["secret_hash"],
            "unit_price_micros": 0,
            "hard_cap_units": None,
        }
        for name, expected in immutable.items():
            if getattr(existing, name) != expected:
                raise RuntimeError("OWNER service account identity drift detected")
        return existing


def authenticate_owner_key(api_key: Optional[str]) -> tuple[Account, dict[str, Any]] | None:
    key = (api_key or "").strip()
    record = _record_for_key(key)
    if record is None:
        return None
    account = _ensure_account(record)
    if account.status != STATUS_ACTIVE:
        return None
    return account, record


def _bearer_value(authorization: Optional[str]) -> Optional[str]:
    raw = (authorization or "").strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip() or None
    return None


def _request_owner_key(headers: list[tuple[bytes, bytes]]) -> Optional[str]:
    direct = ""
    bearer = ""
    for name, value in headers:
        lowered = name.lower()
        if lowered == b"x-dsg-api-key":
            direct = value.decode("latin1").strip()
        elif lowered == b"authorization":
            bearer = _bearer_value(value.decode("latin1")) or ""
    return direct or bearer or None


def _is_admin_path(path: str) -> bool:
    if path in _ADMIN_EXACT_PATHS:
        return True
    return path == "/billing/accounts" or path.startswith("/billing/accounts/")


def _set_header(headers: list[tuple[bytes, bytes]], name: bytes, value: str) -> list[tuple[bytes, bytes]]:
    lowered = name.lower()
    updated = [(key, current) for key, current in headers if key.lower() != lowered]
    updated.append((name, value.encode("latin1")))
    return updated


class OwnerServiceMiddleware:
    """Promote a verified OWNER key into existing account/admin auth paths."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = list(scope.get("headers") or [])
        candidate = _request_owner_key(headers)
        authenticated = authenticate_owner_key(candidate)
        if authenticated is None:
            await self.app(scope, receive, send)
            return

        owner_key = str(candidate)
        headers = _set_header(headers, b"x-dsg-api-key", owner_key)
        path = str(scope.get("path") or "")
        if _is_admin_path(path):
            admin_secret = (os.getenv("DSG_REVENUE_ADMIN_SECRET") or "").strip()
            if len(admin_secret) >= 32:
                headers = _set_header(headers, b"authorization", f"Bearer {admin_secret}")
        scope["headers"] = headers
        scope.setdefault("state", {})["dsg_owner_service"] = True
        await self.app(scope, receive, send)


@router.get("/status")
def owner_service_status() -> dict[str, Any]:
    records = _load_records()
    scopes = sorted({scope for record in records for scope in record.get("scopes", [])})
    return {
        "configured": bool(records),
        "configured_accounts": len(records),
        "role": "owner_service",
        "scopes": scopes,
        "plaintext_secret_stored": False,
        "admin_master_exposed_to_agent": False,
        "provider_authority": "brokered_and_capability_gated",
        "approval_gates_preserved": True,
    }


@router.get("/whoami")
def owner_service_whoami(
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    key = (x_dsg_api_key or "").strip() or (_bearer_value(authorization) or "")
    authenticated = authenticate_owner_key(key)
    if authenticated is None:
        raise HTTPException(status_code=403, detail="OWNER service key required")
    account, record = authenticated
    from .capability_broker import capability_status

    return {
        "authenticated": True,
        "role": "owner_service",
        "account": account.public_view(),
        "scopes": list(record.get("scopes", DEFAULT_SCOPES)),
        "capabilities": capability_status(),
        "admin_bridge_ready": len((os.getenv("DSG_REVENUE_ADMIN_SECRET") or "").strip()) >= 32,
        "approval_gates_preserved": True,
    }


def install(app) -> None:
    app.add_middleware(OwnerServiceMiddleware)
    app.include_router(router)


__all__ = [
    "OWNER_CHANNEL",
    "OWNER_PLAN",
    "OwnerServiceMiddleware",
    "authenticate_owner_key",
    "install",
    "owner_service_status",
]
