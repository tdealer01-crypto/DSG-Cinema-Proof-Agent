"""Short-lived agent pairing credentials for Cinema MCP.

The browser keeps the customer's DSG API key. Agents receive a short-lived
pairing token instead. An ASGI middleware resolves a valid pairing token to the
master key only inside the server before the existing /mcp route runs, so the
model/tool payload never needs the master credential.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from revenue import api as billing
from . import service

router = APIRouter(prefix="/remote-browser", tags=["agent-pairing"])
_TOKEN_PREFIX = "dsg_pair_"
_lock = threading.RLock()


@dataclass(frozen=True)
class _Pairing:
    api_key: str
    account_id: str
    agent_name: str
    expires_at: float


_pairings: dict[str, _Pairing] = {}


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _cleanup(now: Optional[float] = None) -> None:
    current = time.time() if now is None else now
    with _lock:
        expired = [key for key, value in _pairings.items() if value.expires_at <= current]
        for key in expired:
            _pairings.pop(key, None)


def _authenticated_account(api_key: Optional[str]):
    key = (api_key or "").strip()
    if not key:
        raise HTTPException(status_code=401, detail="a valid X-DSG-API-Key header is required")
    authorization = billing.authorize_request(key, service.VERIFIED_EXECUTION_SKU)
    if authorization is None or authorization.account is None:
        raise HTTPException(status_code=401, detail="an authenticated DSG account is required")
    return key, authorization.account


class PairAgentRequest(BaseModel):
    agent_name: str = Field(default="chat-agent", min_length=1, max_length=80)
    ttl_seconds: int = Field(default=600, ge=60, le=900)


class RevokePairingRequest(BaseModel):
    pairing_token: str = Field(min_length=20, max_length=256)


@router.post("/agent-pair", status_code=201)
def pair_agent(
    body: PairAgentRequest,
    request: Request,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict:
    api_key, account = _authenticated_account(x_dsg_api_key)
    _cleanup()
    token = _TOKEN_PREFIX + secrets.token_urlsafe(32)
    expires_at = time.time() + body.ttl_seconds
    with _lock:
        _pairings[_digest(token)] = _Pairing(
            api_key=api_key,
            account_id=account.account_id,
            agent_name=body.agent_name,
            expires_at=expires_at,
        )
    origin = str(request.base_url).rstrip("/")
    return {
        "paired": True,
        "agent_name": body.agent_name,
        "pairing_token": token,
        "token_type": "Bearer",
        "expires_in": body.ttl_seconds,
        "expires_at_unix": int(expires_at),
        "mcp_endpoint": f"{origin}/mcp",
        "master_key_exposed_to_agent": False,
        "message": "Give the pairing token to the MCP client as a Bearer token. The master DSG API key remains in Cinema.",
    }


@router.post("/agent-pair/revoke")
def revoke_pairing(
    body: RevokePairingRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict:
    _, account = _authenticated_account(x_dsg_api_key)
    digest = _digest(body.pairing_token)
    with _lock:
        pairing = _pairings.get(digest)
        if pairing is not None and pairing.account_id != account.account_id:
            raise HTTPException(status_code=403, detail="pairing token belongs to another account")
        removed = _pairings.pop(digest, None) is not None
    return {"revoked": removed}


def resolve_pairing_token(token: str) -> Optional[str]:
    if not token.startswith(_TOKEN_PREFIX):
        return None
    _cleanup()
    with _lock:
        pairing = _pairings.get(_digest(token))
    if pairing is None or pairing.expires_at <= time.time():
        return None
    return pairing.api_key


class AgentPairingMiddleware:
    """Translate a short-lived Bearer pairing token to the existing MCP key header."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") != "/mcp":
            await self.app(scope, receive, send)
            return

        headers = list(scope.get("headers") or [])
        authorization = next((value for key, value in headers if key.lower() == b"authorization"), b"")
        raw = authorization.decode("latin1").strip()
        if raw.lower().startswith("bearer "):
            token = raw[7:].strip()
            api_key = resolve_pairing_token(token)
            if api_key:
                filtered = [(key, value) for key, value in headers if key.lower() not in {b"authorization", b"x-dsg-api-key"}]
                filtered.append((b"x-dsg-api-key", api_key.encode("latin1")))
                scope = {**scope, "headers": filtered}
        await self.app(scope, receive, send)


_CONNECT_HTML = """<!doctype html>
<meta name=viewport content='width=device-width,initial-scale=1'>
<title>DSG ONE — Connect Agent</title>
<style>body{font:16px system-ui;background:#07101f;color:#e9f0ff;max-width:760px;margin:auto;padding:24px}input,button{font:inherit;padding:11px;border-radius:9px;border:1px solid #345;background:#0d1a30;color:#fff}input{width:100%;box-sizing:border-box}.row{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.card{border:1px solid #234;padding:18px;border-radius:14px;background:#0a1426}.ok{color:#66e2b5}.muted{color:#91a3c0;font-size:13px}.primary{background:#f5f7ff;color:#07101f;font-weight:700;border-color:#f5f7ff}details{margin-top:18px}code{word-break:break-all}</style>
<h1>Connect Agent</h1>
<p class=muted>One click prepares Cinema for your agent. If needed, Cinema activates Free Evaluation, turns Remote ON, creates a short-lived pairing token, and verifies MCP. The master DSG key stays in this browser tab; the agent receives a short-lived pairing token only. Plan approval is never skipped.</p>
<div class=card>
<button id=pair class=primary>Connect Agent</button>
<p id=s class=muted>Ready to connect.</p>
<pre id=o></pre>
<details><summary>Advanced</summary><label>DSG API key</label><div class=row><input id=k type=password autocomplete=off><button id=activate>Activate Free Key</button><button id=show>Show</button><button id=copy>Copy</button></div><label>Agent name</label><div class=row><input id=a value='chat-agent'></div><button id=copyPair disabled>Copy pairing token</button></details>
</div>
<script>
const k=document.querySelector('#k'),s=document.querySelector('#s'),o=document.querySelector('#o'),pairButton=document.querySelector('#pair'),copyPair=document.querySelector('#copyPair');
const KEY_SLOT='dsg-one-key-session',PAIR_SLOT='dsg-one-agent-pairing-token',ACTIVATION_SLOT='dsg-one-remote-activation-id';
let running=false;
try{k.value=sessionStorage.getItem(KEY_SLOT)||''}catch(e){}
function activationId(){try{let id=sessionStorage.getItem(ACTIVATION_SLOT);if(!id){id='remote-browser-'+(crypto.randomUUID?crypto.randomUUID():String(Date.now())+'-'+Math.random().toString(36).slice(2));sessionStorage.setItem(ACTIVATION_SLOT,id)}return id}catch(e){return 'remote-browser-'+String(Date.now())+'-'+Math.random().toString(36).slice(2)}}
function rememberKey(value){k.value=value;try{sessionStorage.setItem(KEY_SLOT,value)}catch(e){}}
function rememberPair(value){try{sessionStorage.setItem(PAIR_SLOT,value)}catch(e){}copyPair.disabled=!value}
async function jsonFetch(path,options={}){const r=await fetch(path,options);let b={};try{b=await r.json()}catch(e){}if(!r.ok)throw new Error((b.detail&&JSON.stringify(b.detail))||JSON.stringify(b)||('HTTP '+r.status));return b}
async function activateKey(){s.textContent='Activating Free Evaluation…';const b=await jsonFetch('/billing/activate',{method:'POST',headers:{'Accept':'application/json','Content-Type':'application/json'},body:JSON.stringify({channel:'remote_browser',activation_id:activationId(),display_name:'Cinema Remote Browser'})});if(!b.api_key)throw new Error('Activation returned no API key');rememberKey(b.api_key);return b.api_key}
async function ensureKey(){const existing=k.value.trim();return existing||await activateKey()}
async function enableRemote(key){s.textContent='Turning Remote ON…';const b=await jsonFetch('/remote-browser/enable',{method:'POST',headers:{'Accept':'application/json','X-DSG-API-Key':key}});if(b.remote_enabled!==true)throw new Error('Cinema did not confirm Remote ON');return b}
async function pairAgent(key){s.textContent='Creating secure agent pairing…';const b=await jsonFetch('/remote-browser/agent-pair',{method:'POST',headers:{'Content-Type':'application/json','X-DSG-API-Key':key},body:JSON.stringify({agent_name:document.querySelector('#a').value||'chat-agent',ttl_seconds:600})});if(!b.pairing_token)throw new Error('Pairing returned no token');rememberPair(b.pairing_token);return b}
async function checkStatus(token){s.textContent='Verifying MCP connection…';const rpc={jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'remote_status',arguments:{}}};const b=await jsonFetch('/mcp',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify(rpc)});const result=b.result||{};if(result.isError===true)throw new Error(JSON.stringify(result.structuredContent||result.content||result));return result.structuredContent||{}}
async function connectAgent(){if(running)return;running=true;pairButton.disabled=true;o.textContent='';try{const key=await ensureKey();const remote=await enableRemote(key);const pairing=await pairAgent(key);const status=await checkStatus(pairing.pairing_token);const summary={remote_enabled:status.remote_enabled===true,agent_connection:status.agent_connection||'waiting',active_sessions:status.active_sessions||0,shared_browser_connected:!!(status.shared_browser&&status.shared_browser.connected),mcp_endpoint:pairing.mcp_endpoint,pairing_expires_in:pairing.expires_in,master_key_exposed_to_agent:false,plan_approval_required:true};o.textContent=JSON.stringify(summary,null,2);if(!summary.remote_enabled)throw new Error('Remote status did not stay enabled');s.innerHTML='<span class=ok>READY — Cinema is paired and Remote is ON.</span> Approve the plan when Cinema shows it; after APPROVED the agent binds to that exact step automatically.'}catch(e){s.textContent='CONNECT FAILED — '+e.message}finally{running=false;pairButton.disabled=false}}
document.querySelector('#activate').onclick=async()=>{try{await activateKey();s.innerHTML='<span class=ok>FREE KEY ACTIVE — kept only for this browser tab</span>'}catch(e){s.textContent='ACTIVATION FAILED — '+e.message}};
document.querySelector('#show').onclick=()=>{k.type=k.type==='password'?'text':'password';document.querySelector('#show').textContent=k.type==='password'?'Show':'Hide'};
document.querySelector('#copy').onclick=async()=>{if(!k.value.trim()){s.textContent='No API key to copy. Connect Agent first.';return}await navigator.clipboard.writeText(k.value);s.textContent='API key copied.'};
copyPair.onclick=async()=>{let token='';try{token=sessionStorage.getItem(PAIR_SLOT)||''}catch(e){}if(!token){s.textContent='No active pairing token. Connect Agent first.';return}await navigator.clipboard.writeText(token);s.textContent='Short-lived pairing token copied.'};
pairButton.onclick=connectAgent;
if(new URLSearchParams(location.search).get('auto')==='1')connectAgent();
</script>"""


@router.get("/connect-agent", response_class=HTMLResponse)
def connect_agent_page() -> HTMLResponse:
    return HTMLResponse(_CONNECT_HTML)


def install(app) -> None:
    app.add_middleware(AgentPairingMiddleware)
    app.include_router(router)


__all__ = ["AgentPairingMiddleware", "PairAgentRequest", "install", "resolve_pairing_token", "router"]
