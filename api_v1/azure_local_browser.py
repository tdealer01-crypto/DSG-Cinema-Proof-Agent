"""Azure-native shared browser for Cinema.

This backend runs Chromium inside the Cinema Azure Container App with Playwright.
The authenticated DSG account owns one logical browser context. The user and an
approved agent operate the same Playwright page while the process is alive.
Cookies and local storage are checkpointed to the durable remote-action Azure
Files mount so a new Container Apps revision can restore the login context.

The browser backend never records form values, keystrokes, passwords or OTPs in
continuity history. User keyboard input is sent only to the live Playwright page;
agent input remains governed by the existing Remote Browser plan/policy layer.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException

from .canonical import utc_now

PROVIDER = "azure_container_apps"
BACKEND_VALUE = "azure_local"
MAX_HISTORY = 50
VIEWPORT = {"width": 1280, "height": 800}

_PLAYWRIGHT = None
_BROWSER = None
_CONTEXTS: dict[str, Any] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def configured() -> bool:
    return (os.getenv("DSG_BROWSER_PROVIDER") or "").strip().lower() in {
        BACKEND_VALUE,
        "azure",
        "self_hosted",
    }


def account_digest(account_id: str) -> str:
    return hashlib.sha256(account_id.encode("utf-8")).hexdigest()


def _root() -> Path:
    from . import remote_browser

    root = remote_browser._ensure_store() / "azure-browser"
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    return root


def _profile_dir(account_hash: str) -> Path:
    path = _root() / "profiles" / account_hash
    path.mkdir(parents=True, exist_ok=True)
    return path


def _metadata_path(account_hash: str) -> Path:
    return _profile_dir(account_hash) / "metadata.json"


def _storage_state_path(account_hash: str) -> Path:
    return _profile_dir(account_hash) / "storage-state.json"


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(path)


def _read_metadata(account_hash: str) -> dict[str, Any]:
    path = _metadata_path(account_hash)
    if not path.exists():
        return {
            "browser_session_id": f"azure-{account_hash[:24]}",
            "created_at": utc_now(),
            "last_observed_at": None,
            "last_pages": [],
            "history": [],
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Azure shared browser metadata is unreadable") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=503, detail="Azure shared browser metadata is invalid")
    value.setdefault("browser_session_id", f"azure-{account_hash[:24]}")
    value.setdefault("history", [])
    value.setdefault("last_pages", [])
    return value


def _safe_url(raw: str) -> Optional[str]:
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    port = parsed.port
    default = (parsed.scheme.lower() == "https" and port in {None, 443}) or (
        parsed.scheme.lower() == "http" and port in {None, 80}
    )
    host = parsed.hostname.rstrip(".").lower()
    netloc = host if default else f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path, "", ""))


async def _ensure_engine():
    global _PLAYWRIGHT, _BROWSER
    if _BROWSER is not None:
        try:
            if _BROWSER.is_connected():
                return _BROWSER
        except Exception:
            _BROWSER = None
    if _PLAYWRIGHT is None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="Playwright is not installed in Cinema") from exc
        _PLAYWRIGHT = await async_playwright().start()
    try:
        _BROWSER = await _PLAYWRIGHT.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "AZURE_CHROMIUM_UNAVAILABLE",
                "message": "Cinema could not launch its bundled Chromium runtime.",
            },
        ) from exc
    return _BROWSER


async def _context(account_hash: str, *, create: bool = True):
    existing = _CONTEXTS.get(account_hash)
    if existing is not None:
        return existing
    if not create:
        return None
    lock = _LOCKS.setdefault(account_hash, asyncio.Lock())
    async with lock:
        existing = _CONTEXTS.get(account_hash)
        if existing is not None:
            return existing
        browser = await _ensure_engine()
        state_path = _storage_state_path(account_hash)
        kwargs: dict[str, Any] = {"viewport": VIEWPORT}
        if state_path.is_file():
            kwargs["storage_state"] = str(state_path)
        try:
            context = await browser.new_context(**kwargs)
            if not context.pages:
                await context.new_page()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Azure Playwright context could not be created") from exc
        _CONTEXTS[account_hash] = context
        return context


async def _page_for_hash(account_hash: str):
    context = await _context(account_hash)
    pages = context.pages
    return pages[-1] if pages else await context.new_page()


async def _checkpoint(account_hash: str) -> None:
    context = _CONTEXTS.get(account_hash)
    if context is None:
        return
    try:
        state = await context.storage_state()
        _atomic_json(_storage_state_path(account_hash), state)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Azure shared browser state could not be checkpointed") from exc


async def _observe(account_hash: str) -> dict[str, Any]:
    context = await _context(account_hash)
    pages: list[dict[str, Any]] = []
    for page in context.pages[-10:]:
        safe = _safe_url(page.url)
        title = ""
        try:
            title = await page.title()
        except Exception:
            pass
        item: dict[str, Any] = {}
        if safe:
            item["url"] = safe
        if title:
            item["title"] = title[:300]
        if item:
            pages.append(item)
    metadata = _read_metadata(account_hash)
    observed_at = utc_now()
    metadata["last_observed_at"] = observed_at
    metadata["last_pages"] = pages
    history = list(metadata.get("history") or [])
    if not history or history[-1].get("pages") != pages:
        history.append({"observed_at": observed_at, "pages": pages})
    metadata["history"] = history[-MAX_HISTORY:]
    metadata["updated_at"] = observed_at
    _atomic_json(_metadata_path(account_hash), metadata)
    return metadata


def _public_metadata(account_hash: str, metadata: dict[str, Any], *, connected: bool) -> dict[str, Any]:
    return {
        "provider": PROVIDER,
        "backend": BACKEND_VALUE,
        "connected": connected,
        "shared_profile": True,
        "context_persistent": True,
        "browser_session_id": metadata.get("browser_session_id"),
        # Compatibility during the Browserbase -> Azure-native migration. New
        # clients must prefer browser_session_id and provider.
        "browserbase_session_id": metadata.get("browser_session_id"),
        "live_view_url": None,
        "live_view_mode": "cinema_same_origin",
        "pages": list(metadata.get("last_pages") or []),
        "continuity": {
            "last_observed_at": metadata.get("last_observed_at"),
            "pages": list(metadata.get("last_pages") or []),
            "recent_navigation": list(metadata.get("history") or [])[-20:],
            "privacy": "URL/title only; query, fragment, credentials and form/input values are not stored",
        },
    }


async def ensure_shared_browser(account_id: str) -> dict[str, Any]:
    if not configured():
        raise HTTPException(status_code=503, detail="Azure-native browser provider is not enabled")
    account_hash = account_digest(account_id)
    await _context(account_hash)
    metadata = await _observe(account_hash)
    return _public_metadata(account_hash, metadata, connected=True)


async def current_shared_browser(account_id: str, *, create: bool = False) -> dict[str, Any]:
    account_hash = account_digest(account_id)
    context = _CONTEXTS.get(account_hash)
    if context is None and create:
        return await ensure_shared_browser(account_id)
    metadata = _read_metadata(account_hash)
    if context is not None:
        metadata = await _observe(account_hash)
    return _public_metadata(account_hash, metadata, connected=context is not None)


async def bind_cinema_session(account_id: str, cinema_session_id: str, *, plan_hash: str) -> dict[str, Any]:
    from . import browserbase_executor

    metadata = await ensure_shared_browser(account_id)
    account_hash = account_digest(account_id)
    browserbase_executor._atomic_json(
        browserbase_executor._session_path(cinema_session_id),
        {
            "cinema_session_id": cinema_session_id,
            "provider": BACKEND_VALUE,
            "account_hash": account_hash,
            "browser_session_id": metadata.get("browser_session_id"),
            "plan_hash": plan_hash,
            "shared_profile": True,
            "created_at": utc_now(),
        },
    )
    return metadata


async def page_for_session(cinema_session_id: str):
    from . import browserbase_executor

    binding = browserbase_executor._read_binding(cinema_session_id)
    if not binding or binding.get("provider") != BACKEND_VALUE or not binding.get("account_hash"):
        raise HTTPException(status_code=409, detail="Azure shared browser session has not been bound")
    return await _page_for_hash(str(binding["account_hash"]))


async def metadata_for_session(cinema_session_id: str) -> dict[str, Any]:
    from . import browserbase_executor

    binding = browserbase_executor._read_binding(cinema_session_id)
    if not binding or binding.get("provider") != BACKEND_VALUE or not binding.get("account_hash"):
        raise HTTPException(status_code=409, detail="Azure shared browser session has not been bound")
    account_hash = str(binding["account_hash"])
    metadata = await _observe(account_hash)
    return _public_metadata(account_hash, metadata, connected=True)


async def save_session(cinema_session_id: str) -> None:
    from . import browserbase_executor

    binding = browserbase_executor._read_binding(cinema_session_id)
    if not binding or binding.get("provider") != BACKEND_VALUE or not binding.get("account_hash"):
        return
    account_hash = str(binding["account_hash"])
    await _checkpoint(account_hash)
    await _observe(account_hash)


async def snapshot(account_hash: str) -> bytes:
    page = await _page_for_hash(account_hash)
    try:
        return await page.screenshot(type="png")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Azure shared browser snapshot failed") from exc


async def user_action(account_hash: str, action: dict[str, Any]) -> dict[str, Any]:
    """Apply direct user input to the account browser. No plan authority is granted."""

    page = await _page_for_hash(account_hash)
    kind = str(action.get("kind") or "")
    params = action.get("parameters") or {}
    if kind == "navigate":
        url = params.get("url")
        if not isinstance(url, str) or _safe_url(url) is None:
            raise HTTPException(status_code=400, detail="a valid http(s) URL is required")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    elif kind == "click":
        await page.mouse.click(float(params.get("x", 0)), float(params.get("y", 0)))
    elif kind == "scroll":
        await page.mouse.wheel(float(params.get("delta_x", 0)), float(params.get("delta_y", 600)))
    elif kind == "type":
        text = params.get("text")
        if not isinstance(text, str) or len(text) > 4096:
            raise HTTPException(status_code=400, detail="invalid keyboard text")
        await page.keyboard.type(text)
    elif kind == "press":
        key = params.get("key")
        if not isinstance(key, str) or not key or len(key) > 64:
            raise HTTPException(status_code=400, detail="invalid keyboard key")
        await page.keyboard.press(key)
    elif kind == "back":
        await page.go_back(wait_until="domcontentloaded", timeout=15000)
    elif kind == "forward":
        await page.go_forward(wait_until="domcontentloaded", timeout=15000)
    elif kind == "reload":
        await page.reload(wait_until="domcontentloaded", timeout=30000)
    else:
        raise HTTPException(status_code=400, detail="unsupported user browser action")
    await page.wait_for_timeout(100)
    await _checkpoint(account_hash)
    metadata = await _observe(account_hash)
    return {
        "ok": True,
        "provider": PROVIDER,
        "url": page.url,
        "title": await page.title(),
        "browser_session_id": metadata.get("browser_session_id"),
    }


__all__ = [
    "BACKEND_VALUE",
    "PROVIDER",
    "account_digest",
    "bind_cinema_session",
    "configured",
    "current_shared_browser",
    "ensure_shared_browser",
    "metadata_for_session",
    "page_for_session",
    "save_session",
    "snapshot",
    "user_action",
]
