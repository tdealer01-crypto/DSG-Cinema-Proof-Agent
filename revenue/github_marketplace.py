"""GitHub Marketplace billing and onboarding bridge for DSG Verified Execution.

GitHub remains the merchant of record. Cinema consumes verified
``marketplace_purchase`` webhooks only to grant/revoke proof entitlement; it
never mirrors a GitHub subscription into Stripe.

The onboarding callback exchanges the GitHub OAuth code and then reads the
installation through the authenticated user API before linking it. The
``installation_id`` query parameter is never trusted on its own.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import html
import json
import os
import secrets
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import api as billing
from .pricing import get_plan

router = APIRouter(prefix="/marketplace/github", tags=["github-marketplace"])

GITHUB_API = "https://api.github.com"
GITHUB_OAUTH_AUTHORIZE = "https://github.com/login/oauth/authorize"
GITHUB_OAUTH_TOKEN = "https://github.com/login/oauth/access_token"
STORE_VERSION = 1
MAX_DELIVERIES = 4096
STATE_TTL_SECONDS = 10 * 60


class MarketplaceConfigurationError(RuntimeError):
    pass


class MarketplaceSignatureError(ValueError):
    pass


def _utc_epoch() -> int:
    return int(time.time())


def _store_path_from_env() -> Optional[str]:
    explicit = (os.getenv("DSG_GITHUB_MARKETPLACE_STORE") or "").strip()
    if explicit:
        return explicit
    account_store = (os.getenv("DSG_REVENUE_ACCOUNT_STORE") or "").strip()
    if account_store:
        return str(Path(account_store).with_name("github-marketplace.json"))
    return None


def _secret(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if len(value) < 32:
        raise MarketplaceConfigurationError(f"{name} is missing or too short")
    return value


def _client_id() -> str:
    value = (os.getenv("GITHUB_MARKETPLACE_OAUTH_CLIENT_ID") or "").strip()
    if not value:
        raise MarketplaceConfigurationError("GITHUB_MARKETPLACE_OAUTH_CLIENT_ID is missing")
    return value


def verify_github_signature(payload: bytes, signature_header: Optional[str], secret: str) -> None:
    if not signature_header or not signature_header.startswith("sha256="):
        raise MarketplaceSignatureError("X-Hub-Signature-256 is required")
    supplied = signature_header.removeprefix("sha256=").strip()
    if len(supplied) != 64:
        raise MarketplaceSignatureError("GitHub webhook signature has invalid length")
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise MarketplaceSignatureError("GitHub webhook signature did not match")


def map_github_plan(plan_name: Any) -> str:
    """Map Marketplace listing names to bounded Cinema entitlements.

    Unknown names deliberately fall to the free tier. Aliases cover the older
    DSG listing vocabulary without ever granting more access on ambiguity.
    """
    name = str(plan_name or "").strip().lower()
    if "enterprise" in name:
        return "github_enterprise"
    if any(token in name for token in ("production", "business", "agency")):
        return "github_business"
    if any(token in name for token in ("team", "pro", "solo")):
        return "github_pro"
    return "github_free"


def _empty_state() -> dict[str, Any]:
    return {"version": STORE_VERSION, "links": {}, "deliveries": []}


class GithubMarketplaceStore:
    """Small lock-guarded mapping from a GitHub buyer to a Cinema account."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = Path(path) if path else None
        self._thread_lock = threading.Lock()
        self._state = _empty_state()
        self._loaded_signature: Optional[tuple[int, int]] = None
        if self.path and self.path.exists():
            self._load()

    @property
    def durable(self) -> bool:
        return self.path is not None

    def _signature(self) -> Optional[tuple[int, int]]:
        if self.path is None:
            return None
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _load(self) -> None:
        assert self.path is not None
        raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        if not isinstance(raw, dict) or raw.get("version") != STORE_VERSION:
            raise ValueError("unsupported GitHub Marketplace store")
        if not isinstance(raw.get("links"), dict) or not isinstance(raw.get("deliveries"), list):
            raise ValueError("invalid GitHub Marketplace store")
        self._state = raw
        self._loaded_signature = self._signature()

    def _reload_if_changed(self) -> None:
        if self.path is None:
            return
        current = self._signature()
        if current is not None and current != self._loaded_signature:
            self._load()

    @contextmanager
    def _file_lock(self):
        if self.path is None:
            yield
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with open(lock_path, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _critical(self):
        with self._thread_lock:
            with self._file_lock():
                self._reload_if_changed()
                yield

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self._state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)
        self._loaded_signature = self._signature()

    def snapshot(self) -> dict[str, Any]:
        with self._critical():
            return json.loads(json.dumps(self._state))

    def link_for(self, github_account_id: int) -> Optional[dict[str, Any]]:
        with self._critical():
            link = self._state["links"].get(str(github_account_id))
            return dict(link) if isinstance(link, dict) else None

    def _mark_delivery(self, delivery_id: str) -> None:
        deliveries = self._state["deliveries"]
        deliveries.append(delivery_id)
        if len(deliveries) > MAX_DELIVERIES:
            del deliveries[: len(deliveries) - MAX_DELIVERIES]

    def apply_purchase(
        self,
        *,
        delivery_id: str,
        action: str,
        github_account_id: int,
        github_login: str,
        plan_name: str,
        billing_cycle: str,
        effective_date: Optional[str],
    ) -> dict[str, Any]:
        """Apply one signature-verified Marketplace delivery idempotently."""
        engine = billing.get_engine()
        with self._critical():
            if delivery_id in self._state["deliveries"]:
                link = self._state["links"].get(str(github_account_id)) or {}
                return {"applied": False, "duplicate": True, "link": dict(link)}

            key = str(github_account_id)
            existing = self._state["links"].get(key)
            existing = dict(existing) if isinstance(existing, dict) else {}
            current_account_id = existing.get("account_id")
            current_account = engine.accounts.get(current_account_id) if current_account_id else None

            if action in {"pending_change", "pending_change_cancelled"}:
                existing.update(
                    {
                        "github_account_id": github_account_id,
                        "github_login": github_login,
                        "pending_plan_name": plan_name if action == "pending_change" else None,
                        "pending_effective_date": effective_date if action == "pending_change" else None,
                        "updated_at": _utc_epoch(),
                    }
                )
                self._state["links"][key] = existing
                self._mark_delivery(delivery_id)
                self._persist()
                return {"applied": False, "pending": action == "pending_change", "link": dict(existing)}

            if action not in {"purchased", "changed", "cancelled"}:
                self._mark_delivery(delivery_id)
                self._persist()
                return {"applied": False, "ignored": True, "reason": f"unsupported action: {action}"}

            plan_key = "github_free" if action == "cancelled" else map_github_plan(plan_name)
            plan = get_plan(plan_key)
            display_name = f"GitHub Marketplace — {github_login or github_account_id}"

            if current_account is None:
                account, _discarded_key = engine.accounts.issue(
                    display_name=display_name,
                    plan=plan_key,
                    channel="github_marketplace",
                    mode="live",
                    unit_price_micros=0,
                    hard_cap_units=plan.hard_cap_units,
                )
            else:
                account = engine.accounts.update(
                    current_account.account_id,
                    display_name=display_name,
                    plan=plan_key,
                    status="active",
                    unit_price_micros=0,
                    hard_cap_units=plan.hard_cap_units,
                    payment_linked=False,
                )

            link = {
                **existing,
                "github_account_id": github_account_id,
                "github_login": github_login,
                "account_id": account.account_id,
                "plan_name": plan_name,
                "plan_key": plan_key,
                "billing_cycle": billing_cycle,
                "effective_date": effective_date,
                "pending_plan_name": None,
                "pending_effective_date": None,
                "updated_at": _utc_epoch(),
            }
            self._state["links"][key] = link
            self._mark_delivery(delivery_id)
            self._persist()
            return {"applied": True, "duplicate": False, "link": dict(link)}

    def issue_browser_key(
        self,
        *,
        github_account_id: int,
        github_login: str,
        installation_id: int,
    ) -> tuple[dict[str, Any], str]:
        """Rotate to a fresh one-time API key after OAuth installation proof."""
        engine = billing.get_engine()
        with self._critical():
            key = str(github_account_id)
            existing = self._state["links"].get(key)
            existing = dict(existing) if isinstance(existing, dict) else {}
            plan_key = existing.get("plan_key") or "github_free"
            try:
                plan = get_plan(plan_key)
            except ValueError:
                plan_key = "github_free"
                plan = get_plan(plan_key)

            display_name = f"GitHub Marketplace — {github_login or github_account_id}"
            new_account, api_key = engine.accounts.issue(
                display_name=display_name,
                plan=plan_key,
                channel="github_marketplace",
                mode="live",
                unit_price_micros=0,
                hard_cap_units=plan.hard_cap_units,
            )

            old_account_id = existing.get("account_id")
            if old_account_id and old_account_id != new_account.account_id:
                old = engine.accounts.get(old_account_id)
                if old is not None:
                    engine.accounts.update(old_account_id, status="suspended")

            link = {
                **existing,
                "github_account_id": github_account_id,
                "github_login": github_login,
                "installation_id": installation_id,
                "account_id": new_account.account_id,
                "plan_key": plan_key,
                "updated_at": _utc_epoch(),
            }
            self._state["links"][key] = link
            self._persist()
            return dict(link), api_key


_store: Optional[GithubMarketplaceStore] = None
_store_path: Optional[str] = None


def get_store() -> GithubMarketplaceStore:
    global _store, _store_path
    path = _store_path_from_env()
    if _store is None or path != _store_path:
        _store = GithubMarketplaceStore(path)
        _store_path = path
    return _store


def reset_store(store: Optional[GithubMarketplaceStore] = None) -> GithubMarketplaceStore:
    global _store, _store_path
    _store = store if store is not None else GithubMarketplaceStore(_store_path_from_env())
    _store_path = str(_store.path) if _store.path else None
    return _store


def _state_signing_secret() -> str:
    return _secret("GITHUB_MARKETPLACE_OAUTH_CLIENT_SECRET")


def _encode_state(installation_id: int) -> str:
    payload = json.dumps(
        {"installation_id": installation_id, "issued_at": _utc_epoch(), "nonce": secrets.token_hex(12)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(_state_signing_secret().encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _decode_state(value: str) -> dict[str, Any]:
    encoded, separator, supplied = value.partition(".")
    if not separator:
        raise ValueError("OAuth state is malformed")
    expected = hmac.new(_state_signing_secret().encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise ValueError("OAuth state signature did not match")
    padding = "=" * (-len(encoded) % 4)
    body = json.loads(base64.urlsafe_b64decode(encoded + padding))
    if not isinstance(body, dict):
        raise ValueError("OAuth state is invalid")
    issued_at = body.get("issued_at")
    if not isinstance(issued_at, int) or abs(_utc_epoch() - issued_at) > STATE_TTL_SECONDS:
        raise ValueError("OAuth state expired")
    return body


async def _exchange_oauth_code(code: str) -> str:
    payload = {
        "client_id": _client_id(),
        "client_secret": _secret("GITHUB_MARKETPLACE_OAUTH_CLIENT_SECRET"),
        "code": code,
    }
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        response = await client.post(
            GITHUB_OAUTH_TOKEN,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=payload,
        )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="GitHub OAuth token exchange failed")
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="GitHub OAuth returned invalid JSON") from exc
    token = body.get("access_token") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token:
        raise HTTPException(status_code=502, detail="GitHub OAuth did not return an access token")
    return token


async def _verified_installation(token: str, installation_id: int) -> tuple[int, str]:
    """Return the installation account only after GitHub validates user access."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        response = await client.get(f"{GITHUB_API}/user/installations/{installation_id}", headers=headers)
    if response.status_code != 200:
        raise HTTPException(
            status_code=403,
            detail="GitHub did not confirm that this installation belongs to the authorized user",
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="GitHub installation lookup returned invalid JSON") from exc
    account = body.get("account") if isinstance(body, dict) else None
    account_id = account.get("id") if isinstance(account, dict) else None
    login = account.get("login") if isinstance(account, dict) else None
    if not isinstance(account_id, int) or not isinstance(login, str) or not login:
        raise HTTPException(status_code=502, detail="GitHub installation account is incomplete")
    return account_id, login


@router.get("/status")
def marketplace_status() -> dict[str, Any]:
    store = get_store()
    checks = {
        "durable_store": "PASS" if store.durable else "MISSING",
        "webhook_secret": "PASS" if len((os.getenv("GITHUB_MARKETPLACE_WEBHOOK_SECRET") or "").strip()) >= 32 else "MISSING",
        "oauth_client_id": "PASS" if (os.getenv("GITHUB_MARKETPLACE_OAUTH_CLIENT_ID") or "").strip() else "MISSING",
        "oauth_client_secret": "PASS" if len((os.getenv("GITHUB_MARKETPLACE_OAUTH_CLIENT_SECRET") or "").strip()) >= 32 else "MISSING",
    }
    ready = all(value == "PASS" for value in checks.values())
    snapshot = store.snapshot()
    return {
        "product": "DSG Verified Execution",
        "billing_channel": "github_marketplace",
        "status": "READY" if ready else "ACTION_REQUIRED",
        "checks": checks,
        "linked_accounts": len(snapshot["links"]),
        "processed_deliveries": len(snapshot["deliveries"]),
        "webhook": "/marketplace/github/webhook",
        "callback": "/marketplace/github/callback",
        "setup": "/marketplace/github/setup",
        "truth_boundary": {
            "github_collects_subscription_payment": True,
            "cinema_stripe_rebilling": False,
            "unknown_plan_falls_back_to_free": True,
        },
    }


@router.post("/webhook")
async def marketplace_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: Optional[str] = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: Optional[str] = Header(default=None, alias="X-GitHub-Delivery"),
) -> JSONResponse:
    raw = await request.body()
    try:
        secret = _secret("GITHUB_MARKETPLACE_WEBHOOK_SECRET")
        verify_github_signature(raw, x_hub_signature_256, secret)
    except MarketplaceConfigurationError as exc:
        return JSONResponse(status_code=503, content={"accepted": False, "error": str(exc)})
    except MarketplaceSignatureError as exc:
        return JSONResponse(status_code=401, content={"accepted": False, "error": str(exc)})

    if not x_github_delivery:
        return JSONResponse(status_code=400, content={"accepted": False, "error": "X-GitHub-Delivery is required"})
    if x_github_event == "ping":
        return JSONResponse(status_code=200, content={"accepted": True, "event": "ping"})
    if x_github_event != "marketplace_purchase":
        return JSONResponse(status_code=202, content={"accepted": True, "ignored": True, "event": x_github_event})

    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"accepted": False, "error": "webhook body is not valid JSON"})

    purchase = body.get("marketplace_purchase") if isinstance(body, dict) else None
    account = purchase.get("account") if isinstance(purchase, dict) else None
    plan = purchase.get("plan") if isinstance(purchase, dict) else None
    action = body.get("action") if isinstance(body, dict) else None
    account_id = account.get("id") if isinstance(account, dict) else None
    login = account.get("login") if isinstance(account, dict) else None
    plan_name = plan.get("name") if isinstance(plan, dict) else None
    billing_cycle = purchase.get("billing_cycle") if isinstance(purchase, dict) else None
    effective_date = purchase.get("effective_date") if isinstance(purchase, dict) else None

    if not isinstance(action, str) or not isinstance(account_id, int) or not isinstance(login, str):
        return JSONResponse(status_code=422, content={"accepted": False, "error": "marketplace_purchase identity is incomplete"})

    result = get_store().apply_purchase(
        delivery_id=x_github_delivery,
        action=action,
        github_account_id=account_id,
        github_login=login,
        plan_name=str(plan_name or ""),
        billing_cycle=str(billing_cycle or ""),
        effective_date=str(effective_date) if effective_date is not None else None,
    )
    public_link = result.get("link")
    if isinstance(public_link, dict):
        public_link = {
            key: value
            for key, value in public_link.items()
            if key in {"github_account_id", "github_login", "plan_name", "plan_key", "billing_cycle", "effective_date", "pending_plan_name", "pending_effective_date"}
        }
    return JSONResponse(
        status_code=200,
        content={
            "accepted": True,
            "event": "marketplace_purchase",
            "action": action,
            "applied": bool(result.get("applied")),
            "duplicate": bool(result.get("duplicate")),
            "pending": bool(result.get("pending")),
            "ignored": bool(result.get("ignored")),
            "entitlement": public_link,
        },
    )


@router.get("/setup")
def marketplace_setup(installation_id: int = Query(gt=0)) -> RedirectResponse:
    try:
        state = _encode_state(installation_id)
        client_id = _client_id()
    except MarketplaceConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    query = urlencode({"client_id": client_id, "state": state})
    return RedirectResponse(f"{GITHUB_OAUTH_AUTHORIZE}?{query}", status_code=302)


@router.get("/callback")
async def marketplace_callback(
    code: str = Query(min_length=4),
    installation_id: int = Query(gt=0),
    state: Optional[str] = Query(default=None),
) -> HTMLResponse:
    if state:
        try:
            decoded = _decode_state(state)
        except (MarketplaceConfigurationError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if decoded.get("installation_id") != installation_id:
            raise HTTPException(status_code=400, detail="OAuth state installation does not match callback")

    try:
        token = await _exchange_oauth_code(code)
        github_account_id, github_login = await _verified_installation(token, installation_id)
    except MarketplaceConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    link, api_key = get_store().issue_browser_key(
        github_account_id=github_account_id,
        github_login=github_login,
        installation_id=installation_id,
    )
    plan_key = html.escape(str(link.get("plan_key") or "github_free"))
    safe_key = json.dumps(api_key)
    document = f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>DSG Verified Execution</title></head><body>
<p>GitHub Marketplace entitlement connected: <strong>{plan_key}</strong>. Opening DSG ONE…</p>
<script>sessionStorage.setItem('dsg_api_key', {safe_key}); location.replace('/app');</script>
<noscript>JavaScript is required to hand the one-time API key to the DSG console without placing it in the URL.</noscript>
</body></html>"""
    return HTMLResponse(
        document,
        status_code=200,
        headers={
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


def install(app: Any) -> None:
    app.include_router(router)
