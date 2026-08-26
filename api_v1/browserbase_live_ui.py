"""Authenticated UI bridge for Browserbase Live View.

The customer dashboard has a strict same-origin CSP. This module serves the
small Live View client script from an exact route and issues short-lived,
account-authenticated viewer capabilities for a same-origin iframe wrapper.
The Browserbase debugger URL is never persisted in remote-action evidence.
"""

from __future__ import annotations

import hashlib
import html
import json
import secrets
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from . import browserbase_executor
from .canonical import utc_now

router = APIRouter(tags=["remote-browser"])
VIEW_TTL_SECONDS = 90


def _viewer_root() -> Path:
    root = browserbase_executor._root() / "viewers"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _viewer_path(token: str) -> Path:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return _viewer_root() / f"{digest}.json"


def _issue_viewer(*, cinema_session_id: str, live_view_url: str) -> str:
    token = secrets.token_urlsafe(32)
    path = _viewer_path(token)
    payload = {
        "cinema_session_id": cinema_session_id,
        "live_view_url": live_view_url,
        "created_at": utc_now(),
        "exp": int(time.time()) + VIEW_TTL_SECONDS,
    }
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    temp.replace(path)
    return token


def _load_viewer(token: str) -> dict[str, Any]:
    path = _viewer_path(token)
    if not path.exists():
        raise HTTPException(status_code=404, detail="shared browser viewer is unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="shared browser viewer is unavailable") from exc
    if int(payload.get("exp", 0)) <= int(time.time()):
        try:
            path.unlink()
        except OSError:
            pass
        raise HTTPException(status_code=410, detail="shared browser viewer expired")
    return payload


@router.get("/dashboard-assets/browserbase-live.js", include_in_schema=False)
async def browserbase_live_script() -> FileResponse:
    path = Path(__file__).resolve().parent.parent / "web" / "customer-dashboard" / "browserbase-live.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="shared browser client is not present")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/remote-browser/browserbase/live-frame")
async def live_frame(
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    live = await browserbase_executor.live_view(x_dsg_api_key=x_dsg_api_key)
    live_url = live.get("live_view_url")
    cinema_session_id = live.get("cinema_session_id")
    if not live.get("connected") or not isinstance(live_url, str) or not live_url.startswith("https://"):
        return {
            "ok": True,
            "provider": "browserbase",
            "connected": False,
            "embed_url": None,
        }
    if not isinstance(cinema_session_id, str) or not cinema_session_id:
        raise HTTPException(status_code=502, detail="shared browser session binding is incomplete")

    viewer = _issue_viewer(cinema_session_id=cinema_session_id, live_view_url=live_url)
    return {
        "ok": True,
        "provider": "browserbase",
        "connected": True,
        "browserbase_session_id": live.get("browserbase_session_id"),
        "cinema_session_id": cinema_session_id,
        "embed_url": f"/remote-browser/browserbase/embed/{viewer}",
    }


@router.get("/remote-browser/browserbase/embed/{viewer_token}", include_in_schema=False)
async def embed_live_view(viewer_token: str) -> HTMLResponse:
    viewer = _load_viewer(viewer_token)
    live_url = str(viewer.get("live_view_url") or "")
    try:
        parsed = urlsplit(live_url)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Browserbase Live View URL is invalid") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise HTTPException(status_code=502, detail="Browserbase Live View URL must use HTTPS")
    host = parsed.hostname.rstrip(".").lower()
    port = parsed.port
    origin = f"https://{host}" if port in {None, 443} else f"https://{host}:{port}"

    safe_url = html.escape(live_url, quote=True)
    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DSG Shared Browser</title>
<style>html,body,iframe{{margin:0;width:100%;height:100%;border:0;background:#fff}}html,body{{overflow:hidden}}</style>
</head><body><iframe src="{safe_url}" allow="clipboard-read; clipboard-write" title="Browserbase Live View"></iframe></body></html>"""
    return HTMLResponse(
        page,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                f"default-src 'none'; style-src 'unsafe-inline'; frame-src {origin}; "
                "frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
            ),
        },
    )


def install(app) -> None:
    app.include_router(router)


__all__ = ["install", "router"]
