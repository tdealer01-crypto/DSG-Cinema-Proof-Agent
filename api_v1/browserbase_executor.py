"""Managed Browserbase executor for Cinema shared Remote Browser sessions.

Cinema remains the policy authority. This module only turns already-authorized
``dsg.remote-action.v1`` envelopes into interactions on one Browserbase session
that is simultaneously visible and interactive to the user through Browserbase
Live View.

The public action route is protected by an ephemeral capability allocated by the
MCP connect flow. The capability is stored only as a SHA-256 digest, is bound to
the Cinema remote session/plan/step/agent, and expires with that authority.
Browserbase API keys stay server-side.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Header, HTTPException

from .canonical import utc_now

router = APIRouter(prefix="/remote-browser/browserbase", tags=["remote-browser"])

BROWSERBASE_API_ROOT = "https://api.browserbase.com/v1"
CAPABILITY_TTL_SECONDS = 3600
MAX_BROWSERBASE_RESPONSE_BYTES = 1024 * 1024

_CONNECTIONS: dict[str, Any] = {}
_MUTATION_LOCKS: dict[str, asyncio.Lock] = {}
_PLAYWRIGHT = None

_READ_ONLY_ACTIONS = {"browser.extract", "browser.screenshot"}
_UNSUPPORTED_ACTIONS = {"browser.workflow", "browser.download"}


def _root() -> Path:
    from . import remote_browser

    root = remote_browser._ensure_store() / "browserbase"
    (root / "capabilities").mkdir(parents=True, exist_ok=True)
    (root / "sessions").mkdir(parents=True, exist_ok=True)
    (root / "evidence").mkdir(parents=True, exist_ok=True)
    return root


def _capability_path(token: str) -> Path:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return _root() / "capabilities" / f"{digest}.json"


def _session_path(cinema_session_id: str) -> Path:
    digest = hashlib.sha256(cinema_session_id.encode("utf-8")).hexdigest()
    return _root() / "sessions" / f"{digest}.json"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    temp.replace(path)


def allocate_capability(*, plan_id: str, step_id: str, agent_identity: str, ttl_seconds: int) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    _atomic_json(
        _capability_path(token),
        {
            "state": "ALLOCATED",
            "plan_id": plan_id,
            "step_id": step_id,
            "agent_identity": agent_identity,
            "session_id": None,
            "plan_hash": None,
            "browser_policy": None,
            "created_at": utc_now(),
            "exp": now + min(max(int(ttl_seconds), 60), CAPABILITY_TTL_SECONDS),
        },
    )
    return token


def finalize_capability(token: str, *, session_id: str, plan_hash: str, browser_policy: dict[str, Any]) -> None:
    path = _capability_path(token)
    if not path.exists():
        raise HTTPException(status_code=503, detail="managed browser capability is unavailable")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="managed browser capability is unreadable") from exc
    if int(value.get("exp", 0)) <= int(time.time()):
        raise HTTPException(status_code=410, detail="managed browser capability expired")
    value.update(
        {
            "state": "BOUND",
            "session_id": session_id,
            "plan_hash": plan_hash,
            "browser_policy": browser_policy,
            "bound_at": utc_now(),
        }
    )
    _atomic_json(path, value)


def revoke_capability(token: str) -> None:
    path = _capability_path(token)
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        value.update({"state": "REVOKED", "revoked_at": utc_now()})
        _atomic_json(path, value)


def _load_capability(token: str) -> dict[str, Any]:
    path = _capability_path(token)
    if not path.exists():
        raise HTTPException(status_code=401, detail="invalid managed browser capability")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="managed browser capability is unreadable") from exc
    if value.get("state") != "BOUND":
        raise HTTPException(status_code=401, detail="managed browser capability is not active")
    if int(value.get("exp", 0)) <= int(time.time()):
        raise HTTPException(status_code=410, detail="managed browser capability expired")
    return value


def _browserbase_key() -> str:
    value = (os.getenv("BROWSERBASE_API_KEY") or "").strip()
    if not value:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "BROWSERBASE_NOT_CONFIGURED",
                "message": "BROWSERBASE_API_KEY is not bound to the Cinema runtime.",
            },
        )
    return value


def _api_headers() -> dict[str, str]:
    return {
        "X-BB-API-Key": _browserbase_key(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _allowed_domains(browser_policy: dict[str, Any]) -> list[str]:
    domains: list[str] = []
    for raw in browser_policy.get("allowed_origins") or []:
        try:
            parsed = urlsplit(str(raw))
        except ValueError:
            continue
        if parsed.scheme.lower() == "https" and parsed.hostname:
            host = parsed.hostname.rstrip(".").lower()
            if host not in domains:
                domains.append(host)
    return domains


async def _bb_request(method: str, path: str, *, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.request(
                method,
                f"{BROWSERBASE_API_ROOT}{path}",
                headers=_api_headers(),
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Browserbase API request failed") from exc
    if len(response.content) > MAX_BROWSERBASE_RESPONSE_BYTES:
        raise HTTPException(status_code=502, detail="Browserbase API response exceeded 1 MiB")
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Browserbase API returned non-JSON") from exc
    if response.status_code < 200 or response.status_code >= 300:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "BROWSERBASE_API_REJECTED",
                "status_code": response.status_code,
                "message": body.get("message") if isinstance(body, dict) else "Browserbase rejected request",
            },
        )
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="Browserbase API returned invalid JSON")
    return body


def _read_binding(cinema_session_id: str) -> Optional[dict[str, Any]]:
    path = _session_path(cinema_session_id)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


async def _debug_metadata(browserbase_session_id: str) -> dict[str, Any]:
    debug = await _bb_request("GET", f"/sessions/{browserbase_session_id}/debug")
    return {
        "provider": "browserbase",
        "browserbase_session_id": browserbase_session_id,
        "live_view_url": debug.get("debuggerFullscreenUrl") or debug.get("debuggerUrl"),
        "pages": debug.get("pages") or [],
        "connected": True,
    }


async def ensure_browser_session(cinema_session_id: str, *, plan_hash: str, browser_policy: dict[str, Any]) -> dict[str, Any]:
    binding = _read_binding(cinema_session_id)
    if binding and binding.get("browserbase_session_id"):
        try:
            return await _debug_metadata(str(binding["browserbase_session_id"]))
        except HTTPException:
            pass

    settings: dict[str, Any] = {
        "recordSession": True,
        "logSession": True,
        "viewport": {"width": 1280, "height": 800},
    }
    domains = _allowed_domains(browser_policy)
    if domains:
        settings["allowedDomains"] = domains

    context_id = (os.getenv("BROWSERBASE_CONTEXT_ID") or "").strip()
    if context_id:
        settings["context"] = {"id": context_id, "persist": True}

    payload: dict[str, Any] = {
        "browserSettings": settings,
        "timeout": 3600,
        "userMetadata": {"cinema_session_id": cinema_session_id, "plan_hash": plan_hash},
    }
    project_id = (os.getenv("BROWSERBASE_PROJECT_ID") or "").strip()
    if project_id:
        payload["projectId"] = project_id

    created = await _bb_request("POST", "/sessions", payload=payload)
    browserbase_session_id = str(created.get("id") or "").strip()
    if not browserbase_session_id:
        raise HTTPException(status_code=502, detail="Browserbase did not return a session id")

    _atomic_json(
        _session_path(cinema_session_id),
        {
            "cinema_session_id": cinema_session_id,
            "browserbase_session_id": browserbase_session_id,
            "plan_hash": plan_hash,
            "created_at": utc_now(),
        },
    )
    return await _debug_metadata(browserbase_session_id)


async def _connect_browser(cinema_session_id: str):
    binding = _read_binding(cinema_session_id)
    if not binding or not binding.get("browserbase_session_id"):
        raise HTTPException(status_code=409, detail="Browserbase session has not been provisioned")
    session_id = str(binding["browserbase_session_id"])

    existing = _CONNECTIONS.get(cinema_session_id)
    if existing is not None:
        try:
            if existing.is_connected():
                return existing
        except Exception:
            _CONNECTIONS.pop(cinema_session_id, None)

    session = await _bb_request("GET", f"/sessions/{session_id}")
    connect_url = str(session.get("connectUrl") or "").strip()
    if not connect_url:
        raise HTTPException(status_code=502, detail="Browserbase did not return a CDP connect URL")

    global _PLAYWRIGHT
    if _PLAYWRIGHT is None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="Playwright is not installed in the Cinema runtime") from exc
        _PLAYWRIGHT = await async_playwright().start()

    try:
        browser = await _PLAYWRIGHT.chromium.connect_over_cdp(connect_url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Could not connect to Browserbase over CDP") from exc
    _CONNECTIONS[cinema_session_id] = browser
    return browser


async def _page(cinema_session_id: str):
    browser = await _connect_browser(cinema_session_id)
    contexts = browser.contexts
    if not contexts:
        raise HTTPException(status_code=502, detail="Browserbase session has no browser context")
    context = contexts[0]
    pages = context.pages
    if pages:
        return pages[-1]
    return await context.new_page()


def _origin(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="current browser URL is invalid") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    port = parsed.port
    default = (parsed.scheme.lower() == "https" and port in {None, 443}) or (
        parsed.scheme.lower() == "http" and port in {None, 80}
    )
    host = parsed.hostname.rstrip(".").lower()
    netloc = host if default else f"{host}:{port}"
    return f"{parsed.scheme.lower()}://{netloc}"


def _assert_current_origin(page_url: str, context: dict[str, Any], *, mutation: bool) -> None:
    if not mutation:
        return
    policy = context.get("browser_policy") or {}
    if not policy.get("enforce_current_origin"):
        return
    allowed = set(policy.get("allowed_origins") or [])
    current = _origin(page_url)
    if current and current not in allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "BROWSER_ORIGIN_BLOCKED",
                "message": "The current browser origin is outside the approved plan.",
                "current_origin": current,
                "allowed_origins": sorted(allowed),
            },
        )


async def _resolve_locator(page, params: dict[str, Any]):
    selector = params.get("selector") or params.get("target")
    if isinstance(selector, str) and selector.strip():
        return page.locator(selector.strip()).first

    field = params.get("field")
    if isinstance(field, str) and field.strip():
        name = field.strip()
        for locator in (
            page.locator(f'[name="{name}"]'),
            page.locator(f'#{name}'),
            page.get_by_label(name, exact=False),
            page.get_by_placeholder(name, exact=False),
        ):
            try:
                if await locator.count():
                    return locator.first
            except Exception:
                continue

    text = params.get("text")
    if isinstance(text, str) and text.strip():
        return page.get_by_text(text.strip(), exact=False).first

    raise HTTPException(
        status_code=400,
        detail={
            "error": "BROWSER_TARGET_REQUIRED",
            "message": "The action requires selector, target, field, or text.",
        },
    )


async def _sensitive_control(locator) -> bool:
    try:
        attrs = await locator.evaluate(
            """el => ({
              type: (el.getAttribute('type') || '').toLowerCase(),
              autocomplete: (el.getAttribute('autocomplete') || '').toLowerCase(),
              name: (el.getAttribute('name') || '').toLowerCase(),
              aria: (el.getAttribute('aria-label') || '').toLowerCase()
            })"""
        )
    except Exception:
        return False
    material = " ".join(str(attrs.get(key) or "") for key in ("type", "autocomplete", "name", "aria"))
    return (
        attrs.get("type") == "password"
        or "one-time-code" in material
        or "otp" in material
        or "passcode" in material
        or "password" in material
    )


async def _extract(page) -> dict[str, Any]:
    controls = await page.locator(
        "input,textarea,select,button,a,[role=button],[role=checkbox],[role=radio]"
    ).evaluate_all(
        """els => els.slice(0, 400).map((el, i) => {
          const tag = el.tagName.toLowerCase();
          const type = (el.getAttribute('type') || '').toLowerCase();
          const id = el.id || '';
          const name = el.getAttribute('name') || '';
          const aria = el.getAttribute('aria-label') || '';
          const placeholder = el.getAttribute('placeholder') || '';
          const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 300);
          const label = id ? (document.querySelector(`label[for="${CSS.escape(id)}"]`)?.innerText || '') : '';
          const sensitive = type === 'password' ||
            (el.getAttribute('autocomplete') || '').toLowerCase() === 'one-time-code' ||
            /password|otp|passcode/i.test(`${name} ${aria} ${label}`);
          let selector = '';
          if (id) selector = `#${CSS.escape(id)}`;
          else if (name) selector = `${tag}[name="${CSS.escape(name)}"]`;
          else if (aria) selector = `${tag}[aria-label="${CSS.escape(aria)}"]`;
          return {
            index: i, tag, type, id, name, aria_label: aria, placeholder,
            label: String(label).trim().replace(/\\s+/g, ' ').slice(0, 300),
            text, selector,
            required: !!el.required || el.getAttribute('aria-required') === 'true',
            disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
            checked: 'checked' in el ? !!el.checked : null,
            sensitive
          };
        })"""
    )
    return {"url": page.url, "title": await page.title(), "controls": controls}


async def _perform_action(cinema_session_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    action = payload.get("action") or {}
    context = payload.get("context") or {}
    kind = str(action.get("kind") or "")
    params = action.get("parameters") or {}
    page = await _page(cinema_session_id)

    mutation = kind not in _READ_ONLY_ACTIONS
    if kind != "browser.navigate":
        _assert_current_origin(page.url, context, mutation=mutation)

    if kind in _UNSUPPORTED_ACTIONS:
        raise HTTPException(
            status_code=501,
            detail={
                "error": "BROWSER_ACTION_NOT_IMPLEMENTED",
                "message": f"{kind} is not implemented by the Browserbase executor.",
            },
        )

    if kind == "browser.navigate":
        url = params.get("url")
        if not isinstance(url, str) or not url:
            raise HTTPException(status_code=400, detail="browser.navigate requires parameters.url")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return 200, {"ok": True, "url": page.url, "title": await page.title()}

    if kind == "browser.extract":
        return 200, {"ok": True, **(await _extract(page))}

    if kind == "browser.screenshot":
        raw = await page.screenshot(full_page=bool(params.get("full_page") is True))
        digest = hashlib.sha256(raw).hexdigest()
        evidence_dir = _root() / "evidence" / hashlib.sha256(cinema_session_id.encode()).hexdigest()
        evidence_dir.mkdir(parents=True, exist_ok=True)
        path = evidence_dir / f"{int(time.time() * 1000)}-{digest[:16]}.png"
        path.write_bytes(raw)
        return 200, {
            "ok": True,
            "url": page.url,
            "screenshot_sha256": digest,
            "evidence_ref": f"browserbase://evidence/{digest}",
        }

    if kind == "browser.click":
        locator = await _resolve_locator(page, params)
        await locator.click(timeout=15000)
        return 200, {"ok": True, "url": page.url}

    if kind == "browser.type":
        locator = await _resolve_locator(page, params)
        if await _sensitive_control(locator):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "DELEGATED_IDENTITY_INPUT_REQUIRED",
                    "message": "Sensitive controls must use the approved delegated user controller.",
                },
            )
        value = params.get("value")
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail="browser.type requires parameters.value")
        await locator.fill(value, timeout=15000)
        return 200, {"ok": True, "url": page.url}

    if kind == "browser.select":
        locator = await _resolve_locator(page, params)
        value = params.get("value")
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail="browser.select requires parameters.value")
        await locator.select_option(label=value, timeout=15000)
        return 200, {"ok": True, "url": page.url}

    if kind == "browser.scroll":
        await page.mouse.wheel(float(params.get("delta_x", 0)), float(params.get("delta_y", params.get("amount", 600))))
        return 200, {"ok": True, "url": page.url}

    if kind == "browser.upload":
        locator = await _resolve_locator(page, params)
        ref = params.get("file_ref")
        if not isinstance(ref, str) or not ref.startswith("artifact://"):
            raise HTTPException(status_code=400, detail="browser.upload requires an artifact:// file_ref")
        relative = ref[len("artifact://") :].lstrip("/")
        candidate = (Path("/app") / relative).resolve()
        root = Path("/app").resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise HTTPException(status_code=404, detail="approved upload artifact was not found")
        await locator.set_input_files(str(candidate))
        return 200, {
            "ok": True,
            "url": page.url,
            "artifact_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        }

    if kind == "pointer.move":
        await page.mouse.move(float(params.get("x", 0)), float(params.get("y", 0)))
        return 200, {"ok": True, "url": page.url}

    if kind == "pointer.click":
        await page.mouse.click(float(params.get("x", 0)), float(params.get("y", 0)))
        return 200, {"ok": True, "url": page.url}

    if kind == "pointer.drag":
        sx, sy = float(params.get("start_x", 0)), float(params.get("start_y", 0))
        ex, ey = float(params.get("end_x", 0)), float(params.get("end_y", 0))
        await page.mouse.move(sx, sy)
        await page.mouse.down()
        await page.mouse.move(ex, ey, steps=10)
        await page.mouse.up()
        return 200, {"ok": True, "url": page.url}

    if kind == "keyboard.type":
        text = params.get("text")
        if not isinstance(text, str):
            raise HTTPException(status_code=400, detail="keyboard.type requires parameters.text")
        await page.keyboard.type(text)
        return 200, {"ok": True, "url": page.url}

    if kind == "keyboard.press":
        key = params.get("key")
        if not isinstance(key, str) or not key:
            raise HTTPException(status_code=400, detail="keyboard.press requires parameters.key")
        await page.keyboard.press(key)
        return 200, {"ok": True, "url": page.url}

    if kind == "identity.confirmation.click":
        locator = await _resolve_locator(page, params)
        await locator.click(timeout=15000)
        return 200, {"ok": True, "url": page.url, "confirmed": True}

    if kind in {"identity.secret.inject", "identity.otp.submit"}:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "TRUSTED_SECRET_RESOLVER_UNAVAILABLE",
                "message": (
                    "The plan delegated this identity action, but no trusted secret/OTP resolver "
                    "is bound to the Browserbase executor. Plaintext fallback is forbidden."
                ),
            },
        )

    raise HTTPException(
        status_code=400,
        detail={"error": "UNKNOWN_BROWSER_ACTION", "message": f"Unsupported action {kind}"},
    )


def _validate_envelope(capability: dict[str, Any], payload: dict[str, Any]) -> str:
    if payload.get("version") != "dsg.remote-action.v1":
        raise HTTPException(status_code=400, detail="unsupported remote action protocol")
    session_id = str(payload.get("session_id") or "")
    context = payload.get("context") or {}
    expected = {
        "session_id": capability.get("session_id"),
        "plan_id": capability.get("plan_id"),
        "plan_hash": capability.get("plan_hash"),
        "step_id": capability.get("step_id"),
        "agent_identity": capability.get("agent_identity"),
    }
    actual = {
        "session_id": session_id,
        "plan_id": context.get("plan_id"),
        "plan_hash": context.get("plan_hash"),
        "step_id": context.get("step_id"),
        "agent_identity": context.get("agent_identity"),
    }
    if actual != expected:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "MANAGED_BROWSER_BINDING_MISMATCH",
                "message": "The relay envelope does not match the bound Cinema session.",
            },
        )
    return session_id


@router.post("/action/{capability_token}")
async def browserbase_action(capability_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    capability = _load_capability(capability_token)
    cinema_session_id = _validate_envelope(capability, payload)
    await ensure_browser_session(
        cinema_session_id,
        plan_hash=str(capability["plan_hash"]),
        browser_policy=dict(capability.get("browser_policy") or {}),
    )

    kind = str((payload.get("action") or {}).get("kind") or "")
    if kind in _READ_ONLY_ACTIONS:
        status, body = await _perform_action(cinema_session_id, payload)
    else:
        lock = _MUTATION_LOCKS.setdefault(cinema_session_id, asyncio.Lock())
        async with lock:
            status, body = await _perform_action(cinema_session_id, payload)
    body["remote_status"] = status
    return body


@router.get("/live-view")
async def live_view(x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key")) -> dict[str, Any]:
    from . import remote_pairing

    key = remote_pairing._api_key(x_dsg_api_key)
    account_id = remote_pairing._account_id(key)
    state = remote_pairing._read_state(account_id)
    active = remote_pairing._active_sessions(state)
    for cinema_session_id in reversed(active):
        binding = _read_binding(cinema_session_id)
        if not binding or not binding.get("browserbase_session_id"):
            continue
        try:
            metadata = await _debug_metadata(str(binding["browserbase_session_id"]))
        except HTTPException:
            continue
        return {"ok": True, "cinema_session_id": cinema_session_id, **metadata}
    return {"ok": True, "connected": False, "provider": "browserbase", "live_view_url": None}


def install(app) -> None:
    app.include_router(router)


__all__ = [
    "allocate_capability",
    "browserbase_action",
    "ensure_browser_session",
    "finalize_capability",
    "install",
    "live_view",
    "revoke_capability",
    "router",
]
