"""Authenticated same-origin UI bridge for Cinema shared browsers.

Browserbase keeps its provider Live View iframe. The Azure-native provider uses
a same-origin screenshot/input bridge backed by the exact Playwright page shared
with the agent. Viewer capabilities are short-lived and contain no DSG API key.
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
from fastapi.responses import FileResponse, HTMLResponse, Response

from . import (
    azure_local_browser,
    browserbase_executor,
    remote_pairing,
    shared_browser,
)
from .canonical import utc_now

router = APIRouter(tags=["remote-browser"])
VIEW_TTL_SECONDS = 90
AZURE_VIEW_TTL_SECONDS = 3600


def _viewer_root() -> Path:
    root = browserbase_executor._root() / "viewers"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _viewer_path(token: str) -> Path:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return _viewer_root() / f"{digest}.json"


def _issue_viewer(
    *,
    provider: str,
    cinema_session_id: Optional[str] = None,
    live_view_url: Optional[str] = None,
    account_hash: Optional[str] = None,
    ttl_seconds: int = VIEW_TTL_SECONDS,
) -> str:
    token = secrets.token_urlsafe(32)
    path = _viewer_path(token)
    payload = {
        "provider": provider,
        "cinema_session_id": cinema_session_id,
        "live_view_url": live_view_url,
        "account_hash": account_hash,
        "created_at": utc_now(),
        "exp": int(time.time()) + ttl_seconds,
    }
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    try:
        temp.chmod(0o600)
    except OSError:
        pass
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
    # Historical route retained so deployed dashboards do not need a coordinated
    # asset migration when the managed provider changes.
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
    key = remote_pairing._api_key(x_dsg_api_key)
    account_id = remote_pairing._account_id(key)
    state = remote_pairing._read_state(account_id)
    live = await shared_browser.current_shared_browser(
        account_id,
        create=bool(state.get("enabled")) and shared_browser.configured(),
    )
    provider = str(live.get("provider") or shared_browser.provider())

    if provider == azure_local_browser.PROVIDER:
        if not live.get("connected"):
            return {
                "ok": True,
                "provider": provider,
                "connected": False,
                "embed_url": None,
                "shared_profile": True,
                "context_persistent": bool(live.get("context_persistent")),
                "prerequisite": live.get("prerequisite"),
                "continuity": live.get("continuity"),
            }
        viewer = _issue_viewer(
            provider=provider,
            account_hash=azure_local_browser.account_digest(account_id),
            ttl_seconds=AZURE_VIEW_TTL_SECONDS,
        )
        return {
            "ok": True,
            "provider": provider,
            "connected": True,
            "browser_session_id": live.get("browser_session_id"),
            "browserbase_session_id": live.get("browserbase_session_id"),
            "embed_url": f"/remote-browser/browserbase/embed/{viewer}",
            "shared_profile": True,
            "context_persistent": True,
            "continuity": live.get("continuity"),
        }

    live_url = live.get("live_view_url")
    browserbase_session_id = live.get("browserbase_session_id")
    if not live.get("connected") or not isinstance(live_url, str) or not live_url.startswith("https://"):
        return {
            "ok": True,
            "provider": "browserbase",
            "connected": False,
            "embed_url": None,
            "shared_profile": True,
            "context_persistent": bool(live.get("context_persistent")),
            "prerequisite": live.get("prerequisite"),
            "continuity": live.get("continuity"),
        }
    if not isinstance(browserbase_session_id, str) or not browserbase_session_id:
        raise HTTPException(status_code=502, detail="shared browser session binding is incomplete")

    viewer = _issue_viewer(
        provider="browserbase",
        cinema_session_id=browserbase_session_id,
        live_view_url=live_url,
    )
    return {
        "ok": True,
        "provider": "browserbase",
        "connected": True,
        "browserbase_session_id": browserbase_session_id,
        "embed_url": f"/remote-browser/browserbase/embed/{viewer}",
        "shared_profile": True,
        "context_persistent": bool(live.get("context_persistent")),
        "continuity": live.get("continuity"),
    }


def _azure_view_page(viewer_token: str) -> HTMLResponse:
    token = html.escape(viewer_token, quote=True)
    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DSG Shared Browser</title>
<style>
html,body{{margin:0;width:100%;height:100%;background:#111;color:#eee;font-family:system-ui,sans-serif;overflow:hidden}}
#bar{{height:44px;display:flex;gap:6px;align-items:center;padding:0 8px;background:#1d1d1d;box-sizing:border-box}}
button{{height:30px;min-width:34px}}#url{{height:30px;flex:1;box-sizing:border-box}}
#viewport{{height:calc(100% - 44px);display:flex;align-items:flex-start;justify-content:center;background:#222;overflow:hidden}}
#screen{{display:block;max-width:100%;max-height:100%;outline:none;cursor:default;user-select:none}}
</style></head><body>
<div id="bar"><button data-a="back">←</button><button data-a="forward">→</button><button data-a="reload">↻</button><input id="url" autocomplete="off" spellcheck="false" placeholder="https://"><button id="go">Go</button></div>
<div id="viewport"><img id="screen" tabindex="0" alt="DSG shared browser"></div>
<script>
const token={json.dumps(viewer_token)};
const screen=document.getElementById('screen');
const url=document.getElementById('url');
let busy=false;
async function act(kind,parameters={{}}){{
  const r=await fetch(`/remote-browser/azure/view/${{token}}/action`,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{kind,parameters}}),cache:'no-store'}});
  if(!r.ok) throw new Error(await r.text());
  const v=await r.json(); if(v.url) url.value=v.url; return v;
}}
function refresh(){{screen.src=`/remote-browser/azure/view/${{token}}/snapshot?t=${{Date.now()}}`;}}
screen.onload=()=>setTimeout(refresh,450); screen.onerror=()=>setTimeout(refresh,1200); refresh();
screen.addEventListener('click',async e=>{{const r=screen.getBoundingClientRect(); if(!r.width||!r.height)return; const x=(e.clientX-r.left)*1280/r.width; const y=(e.clientY-r.top)*800/r.height; screen.focus(); try{{await act('click',{{x,y}});}}catch(_){{}}}});
screen.addEventListener('wheel',async e=>{{e.preventDefault(); try{{await act('scroll',{{delta_x:e.deltaX,delta_y:e.deltaY}});}}catch(_){{}}}},{{passive:false}});
screen.addEventListener('keydown',async e=>{{if(e.ctrlKey||e.metaKey||e.altKey)return; const specials=new Set(['Enter','Tab','Backspace','Delete','Escape','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Home','End','PageUp','PageDown']); try{{if(specials.has(e.key)){{e.preventDefault();await act('press',{{key:e.key}});}}else if(e.key.length===1){{e.preventDefault();await act('type',{{text:e.key}});}}}}catch(_){{}}}});
document.querySelectorAll('button[data-a]').forEach(b=>b.onclick=()=>act(b.dataset.a).catch(()=>{{}}));
document.getElementById('go').onclick=()=>act('navigate',{{url:url.value}}).catch(()=>{{}});
url.addEventListener('keydown',e=>{{if(e.key==='Enter'){{e.preventDefault();act('navigate',{{url:url.value}}).catch(()=>{{}});}}}});
</script></body></html>"""
    return HTMLResponse(
        page,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "img-src 'self'; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
            ),
        },
    )


@router.get("/remote-browser/browserbase/embed/{viewer_token}", include_in_schema=False)
async def embed_live_view(viewer_token: str) -> HTMLResponse:
    viewer = _load_viewer(viewer_token)
    if viewer.get("provider") == azure_local_browser.PROVIDER:
        return _azure_view_page(viewer_token)

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


@router.get("/remote-browser/azure/view/{viewer_token}/snapshot", include_in_schema=False)
async def azure_snapshot(viewer_token: str) -> Response:
    viewer = _load_viewer(viewer_token)
    if viewer.get("provider") != azure_local_browser.PROVIDER or not viewer.get("account_hash"):
        raise HTTPException(status_code=404, detail="Azure shared browser viewer is unavailable")
    raw = await azure_local_browser.snapshot(str(viewer["account_hash"]))
    return Response(
        content=raw,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/remote-browser/azure/view/{viewer_token}/action", include_in_schema=False)
async def azure_user_action(viewer_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    viewer = _load_viewer(viewer_token)
    if viewer.get("provider") != azure_local_browser.PROVIDER or not viewer.get("account_hash"):
        raise HTTPException(status_code=404, detail="Azure shared browser viewer is unavailable")
    # This route represents direct user input, not delegated agent authority. It
    # deliberately never writes the input payload to evidence or continuity.
    return await azure_local_browser.user_action(str(viewer["account_hash"]), payload)


def install(app) -> None:
    app.include_router(router)


__all__ = ["install", "router"]
