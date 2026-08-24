"""Stripe Apps OAuth onboarding bridge for DSG Verified Execution.

Stripe Apps redirects the installing user's browser to this service's
``redirect_uri`` after they authorize the app. This module owns that URL.

The callback exchanges the authorization code for an access token and then
reads the account back through the Stripe API using that token before linking
anything. The ``stripe_user_id`` returned alongside the token is never trusted
on its own, mirroring the GitHub Marketplace bridge.

Entitlement is deliberately bounded: installing the app grants the free
evaluation plan. Paid plans are reached through the existing Stripe checkout in
``revenue.checkout`` — installation alone never grants paid units.
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
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from . import api as billing
from .pricing import get_plan

router = APIRouter(prefix="/marketplace/stripe", tags=["stripe-marketplace"])

STRIPE_API_BASE = "https://api.stripe.com"
STRIPE_OAUTH_TOKEN = f"{STRIPE_API_BASE}/v1/oauth/token"
STRIPE_APP_AUTHORIZE = "https://marketplace.stripe.com/oauth/v2"
STORE_VERSION = 1
STATE_TTL_SECONDS = 10 * 60
INSTALL_PLAN = "free"


class StripeMarketplaceConfigurationError(RuntimeError):
    pass


def _utc_epoch() -> int:
    return int(time.time())


def _store_path_from_env() -> Optional[str]:
    explicit = (os.getenv("DSG_STRIPE_MARKETPLACE_STORE") or "").strip()
    if explicit:
        return explicit
    account_store = (os.getenv("DSG_REVENUE_ACCOUNT_STORE") or "").strip()
    if account_store:
        return str(Path(account_store).with_name("stripe-marketplace.json"))
    return None


def _secret(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if len(value) < 32:
        raise StripeMarketplaceConfigurationError(f"{name} is missing or too short")
    return value


def _app_id() -> str:
    value = (os.getenv("STRIPE_APP_ID") or "").strip()
    if not value:
        raise StripeMarketplaceConfigurationError("STRIPE_APP_ID is missing")
    return value


def _client_id() -> str:
    value = (os.getenv("STRIPE_APP_OAUTH_CLIENT_ID") or "").strip()
    if not value:
        raise StripeMarketplaceConfigurationError("STRIPE_APP_OAUTH_CLIENT_ID is missing")
    return value


def _state_signing_secret() -> str:
    """Sign OAuth state with the same key that authenticates the exchange.

    Stripe's OAuth client secret is the platform's own secret key, so no
    additional secret has to be provisioned for state integrity.
    """
    return _secret("STRIPE_SECRET_KEY")


def _empty_state() -> dict[str, Any]:
    return {"version": STORE_VERSION, "links": {}}


class StripeMarketplaceStore:
    """Lock-guarded mapping from an installing Stripe account to a Cinema account."""

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
            raise ValueError("unsupported Stripe Marketplace store")
        if not isinstance(raw.get("links"), dict):
            raise ValueError("invalid Stripe Marketplace store")
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

    def link_for(self, stripe_user_id: str) -> Optional[dict[str, Any]]:
        with self._critical():
            link = self._state["links"].get(stripe_user_id)
            return dict(link) if isinstance(link, dict) else None

    def issue_browser_key(
        self,
        *,
        stripe_user_id: str,
        display_name: str,
        livemode: bool,
    ) -> tuple[dict[str, Any], str]:
        """Rotate to a fresh one-time API key after proving the install."""
        engine = billing.get_engine()
        with self._critical():
            existing = self._state["links"].get(stripe_user_id)
            existing = dict(existing) if isinstance(existing, dict) else {}
            plan_key = existing.get("plan_key") or INSTALL_PLAN
            try:
                plan = get_plan(plan_key)
            except ValueError:
                plan_key = INSTALL_PLAN
                plan = get_plan(plan_key)

            new_account, api_key = engine.accounts.issue(
                display_name=display_name,
                plan=plan_key,
                channel="stripe_marketplace",
                mode="live" if livemode else "test",
                hard_cap_units=plan.hard_cap_units,
            )

            old_account_id = existing.get("account_id")
            if old_account_id and old_account_id != new_account.account_id:
                if engine.accounts.get(old_account_id) is not None:
                    engine.accounts.update(old_account_id, status="suspended")

            link = {
                **existing,
                "stripe_user_id": stripe_user_id,
                "display_name": display_name,
                "livemode": livemode,
                "account_id": new_account.account_id,
                "plan_key": plan_key,
                "updated_at": _utc_epoch(),
            }
            self._state["links"][stripe_user_id] = link
            self._persist()
            return dict(link), api_key


_store: Optional[StripeMarketplaceStore] = None
_store_path: Optional[str] = None


def get_store() -> StripeMarketplaceStore:
    global _store, _store_path
    path = _store_path_from_env()
    if _store is None or path != _store_path:
        _store = StripeMarketplaceStore(path)
        _store_path = path
    return _store


def reset_store(store: Optional[StripeMarketplaceStore] = None) -> StripeMarketplaceStore:
    global _store, _store_path
    _store = store if store is not None else StripeMarketplaceStore(_store_path_from_env())
    _store_path = str(_store.path) if _store.path else None
    return _store


def _encode_state() -> str:
    payload = json.dumps(
        {"issued_at": _utc_epoch(), "nonce": secrets.token_hex(12)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(
        _state_signing_secret().encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def _decode_state(value: str) -> dict[str, Any]:
    encoded, separator, supplied = value.partition(".")
    if not separator:
        raise ValueError("OAuth state is malformed")
    expected = hmac.new(
        _state_signing_secret().encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).hexdigest()
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


async def _exchange_oauth_code(code: str) -> dict[str, Any]:
    """Trade the authorization code for an access token.

    Stripe authenticates this call with the platform secret key sent as
    ``client_secret``; the response names the account that authorized.
    """
    payload = {
        "client_secret": _secret("STRIPE_SECRET_KEY"),
        "code": code,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        response = await client.post(
            STRIPE_OAUTH_TOKEN,
            headers={"Accept": "application/json"},
            data=payload,
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Stripe OAuth returned invalid JSON") from exc
    if response.status_code != 200 or not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="Stripe OAuth token exchange failed")
    token = body.get("access_token")
    stripe_user_id = body.get("stripe_user_id")
    if not isinstance(token, str) or not token:
        raise HTTPException(status_code=502, detail="Stripe OAuth did not return an access token")
    if not isinstance(stripe_user_id, str) or not stripe_user_id.startswith("acct_"):
        raise HTTPException(status_code=502, detail="Stripe OAuth did not return an account id")
    return body


async def _verified_account(token: str, stripe_user_id: str) -> tuple[str, bool]:
    """Read the account back with the issued token before linking it."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        response = await client.get(f"{STRIPE_API_BASE}/v1/account", headers=headers)
    if response.status_code != 200:
        raise HTTPException(
            status_code=403,
            detail="Stripe did not confirm that this token belongs to the authorizing account",
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Stripe account lookup returned invalid JSON") from exc
    account_id = body.get("id") if isinstance(body, dict) else None
    if not isinstance(account_id, str) or account_id != stripe_user_id:
        raise HTTPException(status_code=403, detail="Stripe account did not match the authorized install")
    settings = body.get("settings") if isinstance(body, dict) else None
    dashboard = settings.get("dashboard") if isinstance(settings, dict) else None
    display = dashboard.get("display_name") if isinstance(dashboard, dict) else None
    if not isinstance(display, str) or not display.strip():
        display = body.get("business_profile", {}).get("name") if isinstance(body, dict) else None
    if not isinstance(display, str) or not display.strip():
        display = account_id
    return display.strip(), bool(body.get("livemode"))


@router.get("/status")
def stripe_marketplace_status() -> dict[str, Any]:
    store = get_store()
    checks = {
        "durable_store": "PASS" if store.durable else "MISSING",
        "app_id": "PASS" if (os.getenv("STRIPE_APP_ID") or "").strip() else "MISSING",
        "oauth_client_id": "PASS" if (os.getenv("STRIPE_APP_OAUTH_CLIENT_ID") or "").strip() else "MISSING",
        "app_signing_secret": (
            "PASS"
            if len((os.getenv("STRIPE_APP_SIGNING_SECRET") or "").strip()) >= 32
            else "MISSING"
        ),
        "secret_key": "PASS" if len((os.getenv("STRIPE_SECRET_KEY") or "").strip()) >= 32 else "MISSING",
    }
    ready = all(value == "PASS" for value in checks.values())
    snapshot = store.snapshot()
    return {
        "product": "DSG Verified Execution",
        "billing_channel": "stripe_marketplace",
        "status": "READY" if ready else "ACTION_REQUIRED",
        "checks": checks,
        "linked_accounts": len(snapshot["links"]),
        "setup": "/marketplace/stripe/setup",
        "callback": "/marketplace/stripe/callback",
        "truth_boundary": {
            "install_grants_free_plan_only": True,
            "paid_upgrade_requires_checkout": True,
            "callback_parameter_trusted_alone": False,
        },
    }


@router.get("/setup")
def stripe_marketplace_setup() -> RedirectResponse:
    try:
        query = urlencode(
            {
                "client_id": _client_id(),
                "state": _encode_state(),
                "response_type": "code",
            }
        )
        target = f"{STRIPE_APP_AUTHORIZE}/{_app_id()}/authorize?{query}"
    except StripeMarketplaceConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RedirectResponse(target, status_code=302)


@router.get("/callback")
async def stripe_marketplace_callback(
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    error_description: Optional[str] = Query(default=None),
) -> HTMLResponse:
    """Redirect target for the Stripe App OAuth install.

    A denied install is a normal outcome, not a server fault, so it renders a
    plain page instead of raising.
    """
    if error:
        detail = html.escape(error_description or error)
        return _page(f"<p>Stripe install was not completed: {detail}</p>", status_code=200)

    if not code or len(code) < 4:
        raise HTTPException(status_code=400, detail="code is required")

    if state:
        try:
            _decode_state(state)
        except StripeMarketplaceConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        token_body = await _exchange_oauth_code(code)
    except StripeMarketplaceConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    stripe_user_id = str(token_body["stripe_user_id"])
    display_name, livemode = await _verified_account(str(token_body["access_token"]), stripe_user_id)

    link, api_key = get_store().issue_browser_key(
        stripe_user_id=stripe_user_id,
        display_name=f"Stripe App — {display_name}",
        livemode=livemode,
    )
    plan_key = html.escape(str(link.get("plan_key") or INSTALL_PLAN))
    safe_key = json.dumps(api_key)
    return _page(
        f"""<p>Stripe app connected: <strong>{plan_key}</strong>. Opening DSG ONE…</p>
<script>localStorage.setItem('dsg-one-key', {safe_key}); location.replace('/app');</script>
<noscript>JavaScript is required to hand the one-time API key to the DSG console without placing it in the URL.</noscript>""",
        status_code=200,
    )


def _page(body: str, *, status_code: int) -> HTMLResponse:
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DSG Verified Execution</title></head><body>
{body}
</body></html>"""
    return HTMLResponse(
        document,
        status_code=status_code,
        headers={
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


def install(app: Any) -> None:
    app.include_router(router)
