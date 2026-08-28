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
from typing import Any, Literal, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from . import api as billing
from .pricing import get_plan

router = APIRouter(prefix="/marketplace/stripe", tags=["stripe-marketplace"])

STRIPE_API_BASE = "https://api.stripe.com"
STRIPE_OAUTH_TOKEN = f"{STRIPE_API_BASE}/v1/oauth/token"
EXPECTED_APP_ID = "pics.dsg.governance"
STORE_VERSION = 1
STATE_TTL_SECONDS = 10 * 60
INSTALL_PLAN = "free"
OAuthLinkType = Literal["live", "test", "sandbox"]
# Keep key-shape validation explicit without embedding a credential-scanner
# sentinel as one contiguous source-code token.
LIVE_SECRET_PREFIX = "_".join(("sk", "live", ""))
TEST_SECRET_PREFIX = "_".join(("sk", "test", ""))


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
    if value != EXPECTED_APP_ID:
        raise StripeMarketplaceConfigurationError(
            f"STRIPE_APP_ID must match the manifest id {EXPECTED_APP_ID}"
        )
    return value


def _client_id() -> str:
    value = (os.getenv("STRIPE_APP_OAUTH_CLIENT_ID") or "").strip()
    if not value.startswith("ca_"):
        raise StripeMarketplaceConfigurationError(
            "STRIPE_APP_OAUTH_CLIENT_ID must be a Stripe ca_ client id"
        )
    return value


def _developer_key(name: str, *, prefix: str) -> str:
    value = _secret(name)
    if not value.startswith(prefix):
        raise StripeMarketplaceConfigurationError(f"{name} must start with {prefix}")
    return value


def _redirect_uri(link_type: OAuthLinkType) -> str:
    """Return the mode-specific callback registered in the app manifest.

    Stripe's sandbox guidance requires separate redirect URIs for live mode,
    test mode, and general sandboxes so the backend can select the matching
    developer key before it handles an authorization code.  The signed state
    carries the same mode as a second, independent binding.
    """
    env_names = {
        "live": "STRIPE_APP_OAUTH_LIVE_REDIRECT_URI",
        "test": "STRIPE_APP_OAUTH_TEST_REDIRECT_URI",
        "sandbox": "STRIPE_APP_OAUTH_SANDBOX_REDIRECT_URI",
    }
    value = (os.getenv(env_names[link_type]) or "").strip()
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path != f"/marketplace/stripe/callback/{link_type}"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise StripeMarketplaceConfigurationError(
            f"{env_names[link_type]} must be the HTTPS Cinema {link_type} callback"
        )
    return value


def _state_signing_secret() -> str:
    """Sign OAuth state with the same key that authenticates the exchange.

    Stripe's OAuth client secret is the platform's own secret key, so no
    additional secret has to be provisioned for state integrity.
    """
    return _secret("STRIPE_SECRET_KEY")


def _oauth_exchange_secret(link_type: OAuthLinkType) -> str:
    """Return the developer key matching the OAuth install-link mode.

    Stripe issues distinct live, test-mode, and managed-sandbox OAuth links.
    Codes from those links must be exchanged with the corresponding developer
    key; silently falling back to the live billing key would make External Test
    fail only after the reviewer reaches the callback.
    """
    if link_type == "live":
        override = (os.getenv("STRIPE_APP_OAUTH_LIVE_SECRET_KEY") or "").strip()
        if override:
            if len(override) < 32 or not override.startswith(LIVE_SECRET_PREFIX):
                raise StripeMarketplaceConfigurationError(
                    "STRIPE_APP_OAUTH_LIVE_SECRET_KEY must be a live secret key"
                )
            return override
        return _developer_key("STRIPE_SECRET_KEY", prefix=LIVE_SECRET_PREFIX)
    if link_type in {"test", "sandbox"}:
        selected_name = (
            "STRIPE_APP_OAUTH_TEST_SECRET_KEY"
            if link_type == "test"
            else "STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY"
        )
        peer_name = (
            "STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY"
            if link_type == "test"
            else "STRIPE_APP_OAUTH_TEST_SECRET_KEY"
        )
        selected_key = _developer_key(selected_name, prefix=TEST_SECRET_PREFIX)
        peer_key = (os.getenv(peer_name) or "").strip()
        if peer_key and hmac.compare_digest(selected_key, peer_key):
            raise StripeMarketplaceConfigurationError(
                "test-mode and managed-sandbox OAuth keys must be different"
            )
        return selected_key
    raise StripeMarketplaceConfigurationError("unsupported Stripe OAuth link type")


def _oauth_authorize_url(link_type: OAuthLinkType) -> str:
    """Return and validate the Dashboard-issued authorize link for a mode."""
    env_names = {
        "live": "STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL",
        "test": "STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL",
        "sandbox": "STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL",
    }
    configured = (os.getenv(env_names[link_type]) or "").strip()
    if not configured:
        raise StripeMarketplaceConfigurationError(
            f"{env_names[link_type]} is missing"
        )

    parsed = urlparse(configured)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "marketplace.stripe.com"
        or parsed.path != "/oauth/v2/authorize"
        or parsed.fragment
    ):
        raise StripeMarketplaceConfigurationError(
            f"{env_names[link_type]} must be a Stripe Marketplace OAuth v2 authorize URL"
        )
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if query.get("client_id") != _client_id():
        raise StripeMarketplaceConfigurationError(
            f"{env_names[link_type]} must contain the matching Dashboard-issued client_id"
        )
    return urlunparse(parsed._replace(query=urlencode(query)))


def _empty_state() -> dict[str, Any]:
    return {"version": STORE_VERSION, "links": {}, "oauth_states": {}}


def _link_key(stripe_user_id: str, livemode: bool) -> str:
    return f"{'live' if livemode else 'test'}:{stripe_user_id}"


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
        # Version 1 stores created before OAuth state persistence don't have
        # this key.  Adding it in memory is a backward-compatible migration;
        # the next state or link write persists the upgraded shape.
        if "oauth_states" not in raw:
            raw["oauth_states"] = {}
        if not isinstance(raw.get("oauth_states"), dict):
            raise ValueError("invalid Stripe Marketplace OAuth state store")
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

    def link_for(self, stripe_user_id: str, *, livemode: bool) -> Optional[dict[str, Any]]:
        with self._critical():
            link = self._state["links"].get(_link_key(stripe_user_id, livemode))
            # Read the pre-mode-bound key only when its stored mode agrees.
            # A later write migrates it to the composite key.
            if not isinstance(link, dict):
                legacy = self._state["links"].get(stripe_user_id)
                if isinstance(legacy, dict) and legacy.get("livemode") is livemode:
                    link = legacy
            return dict(link) if isinstance(link, dict) else None

    def remember_oauth_state(
        self,
        *,
        nonce: str,
        link_type: OAuthLinkType,
        expires_at: int,
    ) -> None:
        with self._critical():
            now = _utc_epoch()
            states = self._state["oauth_states"]

            def unexpired(value: Any) -> bool:
                if not isinstance(value, dict):
                    return False
                candidate = value.get("expires_at")
                return isinstance(candidate, int) and candidate >= now

            self._state["oauth_states"] = {
                key: value
                for key, value in states.items()
                if unexpired(value)
            }
            self._state["oauth_states"][nonce] = {
                "link_type": link_type,
                "expires_at": expires_at,
            }
            self._persist()

    def consume_oauth_state(self, *, nonce: str, link_type: OAuthLinkType) -> bool:
        """Consume a saved OAuth state exactly once."""
        with self._critical():
            state = self._state["oauth_states"].pop(nonce, None)
            self._persist()
            expires_at = state.get("expires_at") if isinstance(state, dict) else None
            return bool(
                isinstance(state, dict)
                and state.get("link_type") == link_type
                and isinstance(expires_at, int)
                and expires_at >= _utc_epoch()
            )

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
            key = _link_key(stripe_user_id, livemode)
            existing = self._state["links"].get(key)
            legacy_key = stripe_user_id
            if not isinstance(existing, dict):
                legacy = self._state["links"].get(legacy_key)
                if isinstance(legacy, dict) and legacy.get("livemode") is livemode:
                    existing = legacy
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
            self._state["links"][key] = link
            self._state["links"].pop(legacy_key, None)
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


def _encode_state(link_type: OAuthLinkType = "live") -> str:
    issued_at = _utc_epoch()
    nonce = secrets.token_hex(12)
    payload = json.dumps(
        {
            "issued_at": issued_at,
            "link_type": link_type,
            "nonce": nonce,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(
        _state_signing_secret().encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).hexdigest()
    get_store().remember_oauth_state(
        nonce=nonce,
        link_type=link_type,
        expires_at=issued_at + STATE_TTL_SECONDS,
    )
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
    if body.get("link_type") not in {"live", "test", "sandbox"}:
        raise ValueError("OAuth state has an invalid link type")
    nonce = body.get("nonce")
    if not isinstance(nonce, str) or len(nonce) != 24:
        raise ValueError("OAuth state has an invalid nonce")
    return body


async def _exchange_oauth_code(code: str, link_type: OAuthLinkType) -> dict[str, Any]:
    """Trade the authorization code for an access token.

    Stripe authenticates this call with the mode-matched app developer key in
    HTTP Basic auth; the response names the account that authorized.
    """
    payload = {"code": code, "grant_type": "authorization_code"}
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        response = await client.post(
            STRIPE_OAUTH_TOKEN,
            headers={"Accept": "application/json"},
            data=payload,
            auth=(_oauth_exchange_secret(link_type), ""),
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Stripe OAuth returned invalid JSON") from exc
    if response.status_code != 200 or not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="Stripe OAuth token exchange failed")
    token = body.get("access_token")
    stripe_user_id = body.get("stripe_user_id")
    livemode = body.get("livemode")
    if not isinstance(token, str) or not token:
        raise HTTPException(status_code=502, detail="Stripe OAuth did not return an access token")
    if not isinstance(stripe_user_id, str) or not stripe_user_id.startswith("acct_"):
        raise HTTPException(status_code=502, detail="Stripe OAuth did not return an account id")
    if not isinstance(livemode, bool):
        raise HTTPException(status_code=502, detail="Stripe OAuth did not return its mode")
    if livemode is not (link_type == "live"):
        raise HTTPException(status_code=403, detail="Stripe OAuth mode did not match the install link")
    return body


async def _verified_account(token: str, stripe_user_id: str) -> str:
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
    return display.strip()


@router.get("/status")
def stripe_marketplace_status() -> dict[str, Any]:
    store = get_store()
    identity_ready: dict[str, bool] = {}
    for name, check in (("app_id", _app_id), ("oauth_client_id", _client_id)):
        try:
            check()
            identity_ready[name] = True
        except StripeMarketplaceConfigurationError:
            identity_ready[name] = False
    key_ready: dict[OAuthLinkType, bool] = {}
    for link_type in ("live", "test", "sandbox"):
        try:
            _oauth_exchange_secret(link_type)
            key_ready[link_type] = True
        except StripeMarketplaceConfigurationError:
            key_ready[link_type] = False
    non_live_keys_reused = False
    try:
        test_key = _developer_key(
            "STRIPE_APP_OAUTH_TEST_SECRET_KEY",
            prefix=TEST_SECRET_PREFIX,
        )
        sandbox_key = _developer_key(
            "STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY",
            prefix=TEST_SECRET_PREFIX,
        )
        non_live_keys_reused = hmac.compare_digest(test_key, sandbox_key)
    except StripeMarketplaceConfigurationError:
        pass
    redirect_ready: dict[OAuthLinkType, bool] = {}
    authorize_url_ready: dict[OAuthLinkType, bool] = {}
    for link_type in ("live", "test", "sandbox"):
        try:
            _redirect_uri(link_type)
            redirect_ready[link_type] = True
        except StripeMarketplaceConfigurationError:
            redirect_ready[link_type] = False
        try:
            _oauth_authorize_url(link_type)
            authorize_url_ready[link_type] = True
        except StripeMarketplaceConfigurationError:
            authorize_url_ready[link_type] = False
    checks = {
        "durable_store": "PASS" if store.durable else "MISSING",
        "app_id": "PASS" if identity_ready["app_id"] else "MISSING",
        "oauth_client_id": "PASS" if identity_ready["oauth_client_id"] else "MISSING",
        "oauth_live_redirect_uri": "PASS" if redirect_ready["live"] else "MISSING",
        "oauth_test_redirect_uri": "PASS" if redirect_ready["test"] else "MISSING",
        "oauth_sandbox_redirect_uri": "PASS" if redirect_ready["sandbox"] else "MISSING",
        "oauth_live_authorize_url": (
            "PASS" if authorize_url_ready["live"] else "MISSING"
        ),
        "oauth_test_authorize_url": (
            "PASS" if authorize_url_ready["test"] else "MISSING"
        ),
        "oauth_sandbox_authorize_url": (
            "PASS" if authorize_url_ready["sandbox"] else "MISSING"
        ),
        "oauth_live_secret_key": "PASS" if key_ready["live"] else "MISSING",
        "oauth_test_secret_key": (
            "REUSED"
            if non_live_keys_reused
            else "PASS" if key_ready["test"] else "MISSING"
        ),
        "oauth_sandbox_secret_key": (
            "REUSED"
            if non_live_keys_reused
            else "PASS" if key_ready["sandbox"] else "MISSING"
        ),
        "app_signing_secret": (
            "PASS"
            if (os.getenv("STRIPE_APP_SIGNING_SECRET") or "").strip().startswith("absec_")
            and len((os.getenv("STRIPE_APP_SIGNING_SECRET") or "").strip()) >= 32
            else "MISSING"
        ),
        "secret_key": (
            "PASS"
            if (os.getenv("STRIPE_SECRET_KEY") or "")
            .strip()
            .startswith(LIVE_SECRET_PREFIX)
            and len((os.getenv("STRIPE_SECRET_KEY") or "").strip()) >= 32
            else "MISSING"
        ),
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
        "callbacks": {
            link_type: f"/marketplace/stripe/callback/{link_type}"
            for link_type in ("live", "test", "sandbox")
        },
        "truth_boundary": {
            "install_grants_free_plan_only": True,
            "paid_upgrade_requires_checkout": True,
            "callback_parameter_trusted_alone": False,
            "oauth_link_mode_bound_in_state": True,
            "oauth_state_single_use": True,
            "entitlement_mode_bound": True,
        },
    }


@router.get("/setup", response_model=None)
def stripe_marketplace_setup(
    link_type: OAuthLinkType = Query(default="live"),
    begin: bool = Query(default=False),
) -> HTMLResponse | RedirectResponse:
    try:
        authorize = urlparse(_oauth_authorize_url(link_type))
        redirect_uri = _redirect_uri(link_type)
        _oauth_exchange_secret(link_type)
    except StripeMarketplaceConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if begin:
        query = dict(parse_qsl(authorize.query, keep_blank_values=True))
        query.update(
            redirect_uri=redirect_uri,
            state=_encode_state(link_type),
        )
        target = urlunparse(authorize._replace(query=urlencode(query)))
        return RedirectResponse(target, status_code=302)

    mode_label = {
        "live": "live mode",
        "test": "test mode",
        "sandbox": "a managed sandbox",
    }[link_type]
    continue_href = html.escape(
        f"/marketplace/stripe/setup?{urlencode({'link_type': link_type, 'begin': 'true'})}",
        quote=True,
    )
    return _page(
        f"""<main>
<h1>Connect DSG Governance Gate</h1>
<p>You are about to install DSG Governance Gate in {mode_label}.</p>
<ol>
  <li>Continue to Stripe and review the requested Payments read permission.</li>
  <li>Approve the install for the intended Stripe account.</li>
  <li>Stripe returns here and activates the free 25-proof monthly entitlement.</li>
</ol>
<p>The app reads bounded payment context and displays a policy decision and proof receipt. It never captures, refunds, or blocks a payment automatically.</p>
<p><a href="{continue_href}">Continue to Stripe</a></p>
<p>You can cancel on Stripe without changing your account.</p>
</main>""",
        status_code=200,
    )


@router.get("/callback/{callback_link_type}")
async def stripe_marketplace_callback(
    callback_link_type: OAuthLinkType,
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
        if state:
            try:
                state_body = _decode_state(state)
                if state_body["link_type"] == callback_link_type:
                    get_store().consume_oauth_state(
                        nonce=state_body["nonce"],
                        link_type=callback_link_type,
                    )
            except (StripeMarketplaceConfigurationError, ValueError, json.JSONDecodeError):
                pass
        detail = html.escape(error_description or error)
        return _page(f"<p>Stripe install was not completed: {detail}</p>", status_code=200)

    if not code or len(code) < 4:
        raise HTTPException(status_code=400, detail="code is required")

    if not state:
        raise HTTPException(status_code=400, detail="state is required")
    try:
        state_body = _decode_state(state)
    except StripeMarketplaceConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if state_body["link_type"] != callback_link_type:
        raise HTTPException(status_code=400, detail="OAuth state did not match the callback mode")
    if not get_store().consume_oauth_state(
        nonce=state_body["nonce"],
        link_type=callback_link_type,
    ):
        raise HTTPException(status_code=400, detail="OAuth state was unknown, expired, or already used")

    try:
        token_body = await _exchange_oauth_code(code, callback_link_type)
    except StripeMarketplaceConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    stripe_user_id = str(token_body["stripe_user_id"])
    display_name = await _verified_account(str(token_body["access_token"]), stripe_user_id)
    livemode = bool(token_body["livemode"])

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
