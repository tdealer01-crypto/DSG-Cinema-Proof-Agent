"""Account-scoped persistent Browserbase profile for Cinema Remote Browser.

The shared browser belongs to the authenticated DSG account, not to an agent
plan. Users can keep using the same Browserbase Live View while agent authority
is enabled/disabled independently. Agent mutations remain plan-bound by
``remote_browser`` and the Browserbase executor's current-origin check.

A Browserbase Context persists cookies/auth/application storage across provider
sessions. The account id itself is never sent to Browserbase or stored in the
profile; only a SHA-256 account digest is used as metadata/file identity.

Continuity is deliberately privacy-minimized. Cinema stores only timestamped
page URL/title snapshots with query strings, fragments and URL credentials
removed. It never stores form values, keystrokes, passwords, OTPs or DOM input
contents as browser-memory state.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException

from . import browserbase_executor
from .canonical import utc_now

PROFILE_VERSION = 1
DEFAULT_SESSION_TIMEOUT_SECONDS = 21_600
MIN_SESSION_TIMEOUT_SECONDS = 900
MAX_SESSION_TIMEOUT_SECONDS = 21_600
MAX_CONTINUITY_EVENTS = 50


def configured() -> bool:
    return bool((os.getenv("BROWSERBASE_API_KEY") or "").strip())


def _project_id() -> str:
    value = (os.getenv("BROWSERBASE_PROJECT_ID") or "").strip()
    if not value:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "BROWSERBASE_PROJECT_NOT_CONFIGURED",
                "message": "BROWSERBASE_PROJECT_ID is not bound to the Cinema runtime.",
            },
        )
    return value


def _account_digest(account_id: str) -> str:
    return hashlib.sha256(account_id.encode("utf-8")).hexdigest()


def _profiles_root() -> Path:
    root = browserbase_executor._root() / "profiles"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _profile_path(account_id: str) -> Path:
    return _profiles_root() / f"{_account_digest(account_id)}.json"


def _read_profile(account_id: str) -> dict[str, Any]:
    path = _profile_path(account_id)
    if not path.exists():
        return {
            "version": PROFILE_VERSION,
            "account_hash": _account_digest(account_id),
            "context_id": None,
            "browserbase_session_id": None,
            "created_at": utc_now(),
            "updated_at": None,
            "last_observed_at": None,
            "last_pages": [],
            "history": [],
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="shared browser profile is unreadable") from exc
    if not isinstance(value, dict) or value.get("account_hash") != _account_digest(account_id):
        raise HTTPException(status_code=503, detail="shared browser profile is invalid")
    value.setdefault("version", PROFILE_VERSION)
    value.setdefault("context_id", None)
    value.setdefault("browserbase_session_id", None)
    value.setdefault("last_pages", [])
    value.setdefault("history", [])
    return value


def _write_profile(account_id: str, profile: dict[str, Any]) -> None:
    payload = {
        **profile,
        "version": PROFILE_VERSION,
        "account_hash": _account_digest(account_id),
        "updated_at": utc_now(),
    }
    browserbase_executor._atomic_json(_profile_path(account_id), payload)


def _session_timeout_seconds() -> int:
    raw = (os.getenv("BROWSERBASE_SHARED_SESSION_TIMEOUT_SECONDS") or "").strip()
    try:
        requested = int(raw) if raw else DEFAULT_SESSION_TIMEOUT_SECONDS
    except ValueError:
        requested = DEFAULT_SESSION_TIMEOUT_SECONDS
    return min(max(requested, MIN_SESSION_TIMEOUT_SECONDS), MAX_SESSION_TIMEOUT_SECONDS)


def _safe_page(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    raw_url = value.get("url")
    safe_url: str | None = None
    if isinstance(raw_url, str) and raw_url:
        try:
            parsed = urlsplit(raw_url)
            if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
                port = parsed.port
                default = (parsed.scheme.lower() == "https" and port in {None, 443}) or (
                    parsed.scheme.lower() == "http" and port in {None, 80}
                )
                host = parsed.hostname.rstrip(".").lower()
                netloc = host if default else f"{host}:{port}"
                safe_url = urlunsplit((parsed.scheme.lower(), netloc, parsed.path, "", ""))
        except ValueError:
            safe_url = None
    result: dict[str, Any] = {}
    if value.get("id") is not None:
        result["id"] = value.get("id")
    if safe_url:
        result["url"] = safe_url
    title = value.get("title")
    if isinstance(title, str) and title:
        result["title"] = title[:300]
    return result or None


def _safe_pages(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return [page for raw in metadata.get("pages") or [] if (page := _safe_page(raw)) is not None]


def _record_observation(profile: dict[str, Any], pages: list[dict[str, Any]]) -> None:
    observed_at = utc_now()
    profile["last_observed_at"] = observed_at
    profile["last_pages"] = pages
    history = list(profile.get("history") or [])
    if not history or history[-1].get("pages") != pages:
        history.append({"observed_at": observed_at, "pages": pages})
    profile["history"] = history[-MAX_CONTINUITY_EVENTS:]


def _continuity(profile: dict[str, Any], pages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "last_observed_at": profile.get("last_observed_at"),
        "pages": pages,
        "recent_navigation": list(profile.get("history") or [])[-20:],
        "privacy": "URL/title only; query, fragment, credentials and form/input values are not stored",
    }


def _public_metadata(metadata: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    pages = _safe_pages(metadata)
    return {
        **metadata,
        "pages": pages,
        "shared_profile": True,
        "context_persistent": bool(profile.get("context_id")),
        "continuity": _continuity(profile, pages),
    }


async def _ensure_context(account_id: str, profile: dict[str, Any]) -> str:
    existing = str(profile.get("context_id") or "").strip()
    if existing:
        return existing

    created = await browserbase_executor._bb_request(
        "POST",
        "/contexts",
        payload={"projectId": _project_id()},
    )
    context_id = str(created.get("id") or "").strip()
    if not context_id:
        raise HTTPException(status_code=502, detail="Browserbase did not return a context id")
    profile["context_id"] = context_id
    _write_profile(account_id, profile)
    return context_id


async def _existing_session(account_id: str, profile: dict[str, Any]) -> Optional[dict[str, Any]]:
    session_id = str(profile.get("browserbase_session_id") or "").strip()
    if not session_id:
        return None
    try:
        metadata = await browserbase_executor._debug_metadata(session_id)
    except HTTPException:
        profile["browserbase_session_id"] = None
        _write_profile(account_id, profile)
        return None

    pages = _safe_pages(metadata)
    _record_observation(profile, pages)
    _write_profile(account_id, profile)
    return _public_metadata(metadata, profile)


async def ensure_shared_browser(account_id: str) -> dict[str, Any]:
    """Return the account's live shared browser, creating/restoring it if needed."""

    if not configured():
        raise HTTPException(
            status_code=503,
            detail={
                "error": "BROWSERBASE_NOT_CONFIGURED",
                "message": "BROWSERBASE_API_KEY is not bound to the Cinema runtime.",
            },
        )

    profile = _read_profile(account_id)
    existing = await _existing_session(account_id, profile)
    if existing is not None:
        return existing

    project_id = _project_id()
    context_id = await _ensure_context(account_id, profile)
    settings: dict[str, Any] = {
        "recordSession": True,
        "logSession": True,
        "viewport": {"width": 1280, "height": 800},
        "context": {"id": context_id, "persist": True},
    }
    payload: dict[str, Any] = {
        "browserSettings": settings,
        "timeout": _session_timeout_seconds(),
        "keepAlive": True,
        "projectId": project_id,
        "userMetadata": {
            "dsg_account_hash": _account_digest(account_id),
            "surface": "dsg-shared-browser",
        },
    }

    created = await browserbase_executor._bb_request("POST", "/sessions", payload=payload)
    session_id = str(created.get("id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=502, detail="Browserbase did not return a session id")

    profile["browserbase_session_id"] = session_id
    _write_profile(account_id, profile)

    metadata = await browserbase_executor._debug_metadata(session_id)
    profile = _read_profile(account_id)
    _record_observation(profile, _safe_pages(metadata))
    _write_profile(account_id, profile)
    return _public_metadata(metadata, profile)


async def current_shared_browser(account_id: str, *, create: bool = False) -> dict[str, Any]:
    """Inspect the account browser without creating one unless explicitly requested."""

    if not configured():
        return {
            "provider": "browserbase",
            "connected": False,
            "shared_profile": True,
            "context_persistent": False,
            "prerequisite": "BROWSERBASE_NOT_CONFIGURED",
            "live_view_url": None,
            "pages": [],
        }
    profile = _read_profile(account_id)
    existing = await _existing_session(account_id, profile)
    if existing is not None:
        return existing
    if create:
        return await ensure_shared_browser(account_id)
    pages = list(profile.get("last_pages") or [])
    return {
        "provider": "browserbase",
        "connected": False,
        "shared_profile": True,
        "context_persistent": bool(profile.get("context_id")),
        "live_view_url": None,
        "pages": pages,
        "continuity": _continuity(profile, pages),
    }


async def bind_cinema_session(
    account_id: str,
    cinema_session_id: str,
    *,
    plan_hash: str,
) -> dict[str, Any]:
    """Bind a short-lived plan authority session to the account's long-lived browser."""

    metadata = await ensure_shared_browser(account_id)
    browserbase_session_id = str(metadata.get("browserbase_session_id") or "").strip()
    if not browserbase_session_id:
        raise HTTPException(status_code=502, detail="shared browser session binding is incomplete")
    profile = _read_profile(account_id)
    browserbase_executor._atomic_json(
        browserbase_executor._session_path(cinema_session_id),
        {
            "cinema_session_id": cinema_session_id,
            "browserbase_session_id": browserbase_session_id,
            "plan_hash": plan_hash,
            "shared_profile": True,
            "account_hash": _account_digest(account_id),
            "context_id": profile.get("context_id"),
            "created_at": utc_now(),
        },
    )
    return metadata


__all__ = [
    "bind_cinema_session",
    "configured",
    "current_shared_browser",
    "ensure_shared_browser",
]
