from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_CONSOLE = Path(__file__).resolve().parent.parent / "web" / "dsg-one-3d" / "index.html"
_SCRIPT_PATH = "/app-free-evaluation.js"
router = APIRouter()

_SCRIPT = r'''(() => {
"use strict";

const FREE_KEY = "dsg-one-free-session-key";
const FREE_ACTIVATION = "dsg-one-free-activation-id";
const FREE_PLAN = "dsg-one-free-plan";
const APPROVED_PLAN = "dsg-one-approved-plan-session";
const nativeFetch = window.fetch.bind(window);
let activating = null;

function byId(id) { return document.getElementById(id); }
function configuredBase() {
  const raw = (byId("apiBase")?.value || "").trim().replace(/\/+$/, "");
  return raw || location.origin;
}
function freeKey() {
  try { return sessionStorage.getItem(FREE_KEY) || ""; } catch (_) { return ""; }
}
function saveFreeKey(key) {
  try { sessionStorage.setItem(FREE_KEY, key); } catch (_) {}
}
function clearFreeKey() {
  try { sessionStorage.removeItem(FREE_KEY); } catch (_) {}
}
function activationId() {
  try {
    let id = sessionStorage.getItem(FREE_ACTIVATION);
    if (!id) {
      id = `web-session-${crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`}`;
      sessionStorage.setItem(FREE_ACTIVATION, id);
    }
    return id;
  } catch (_) {
    return `web-session-${Date.now()}`;
  }
}
function manualKeyPresent() {
  return Boolean((byId("apiKey")?.value || "").trim());
}
function activeDsgKey() {
  return (byId("apiKey")?.value || "").trim() || freeKey();
}
function retryRun() {
  const run = byId("btnRun");
  if (!run) return;
  run.disabled = false;
  run.click();
}
function dsgRequest(urlLike) {
  try {
    const target = new URL(typeof urlLike === "string" ? urlLike : urlLike.url, location.href);
    const base = new URL(configuredBase(), location.href);
    if (target.origin !== base.origin) return false;
    return target.pathname.startsWith("/api/v1/") || target.pathname.startsWith("/billing/") || target.pathname === "/mcp";
  } catch (_) {
    return false;
  }
}
function jsonErrorCode(payload) {
  return payload?.error || payload?.detail?.error || null;
}
function friendlyUnknownKey(response, payload) {
  if (response.status !== 401 || jsonErrorCode(payload) !== "UNKNOWN_KEY") return response;
  const body = {
    detail: {
      error: "FREE_EVALUATION_REQUIRED",
      message: "Free Evaluation is not active for this browser session. Activate it and retry; no payment card is required.",
      remediation: {
        next_step: "Activate Free Evaluation and retry this run. Developer keys can still be entered in Settings."
      }
    }
  };
  return new Response(JSON.stringify(body), {
    status: 401,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" }
  });
}

window.fetch = async function(input, init = {}) {
  const next = { ...init };
  const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
  const key = freeKey();
  if (key && dsgRequest(input) && !headers.has("X-DSG-API-Key")) {
    headers.set("X-DSG-API-Key", key);
  }
  next.headers = headers;
  const response = await nativeFetch(input, next);

  if (dsgRequest(input) && response.status === 401) {
    try {
      const clone = response.clone();
      const payload = await clone.json();
      if (jsonErrorCode(payload) === "UNKNOWN_KEY") {
        clearFreeKey();
        updateEvaluationStatus("needs-activation", "Free evaluation needs activation", "Activate free evaluation and retry. No payment card is required.");
        return friendlyUnknownKey(response, payload);
      }
    } catch (_) {}
  }

  try {
    const target = new URL(typeof input === "string" ? input : input.url, location.href);
    if (response.ok && /\/api\/v1\/executions\/[^/]+\/verify$/.test(target.pathname)) {
      queueMicrotask(refreshUsage);
    }
  } catch (_) {}
  return response;
};

function ensureEvaluationStatus() {
  let host = byId("freeEvaluationStatus");
  if (host) return host;
  const run = byId("btnRun");
  const actions = run?.closest(".actions");
  if (!actions?.parentNode) return null;
  host = document.createElement("div");
  host.id = "freeEvaluationStatus";
  host.className = "note";
  host.style.marginTop = "12px";
  host.innerHTML = '<div><strong data-role="title">Free evaluation not activated</strong><div data-role="detail" style="margin-top:4px">Your first Run can activate a session-only free key automatically.</div><button class="btn" data-role="activate" style="margin-top:9px">Activate free evaluation</button></div>';
  actions.parentNode.insertBefore(host, actions);
  host.querySelector('[data-role="activate"]').addEventListener("click", async () => {
    try { await activateFreeEvaluation({ retryRun: false }); } catch (_) {}
  });
  return host;
}

function updateEvaluationStatus(kind, title, detail) {
  const host = ensureEvaluationStatus();
  if (!host) return;
  host.dataset.state = kind;
  const titleNode = host.querySelector('[data-role="title"]');
  const detailNode = host.querySelector('[data-role="detail"]');
  const button = host.querySelector('[data-role="activate"]');
  if (titleNode) titleNode.textContent = title;
  if (detailNode) detailNode.textContent = detail;
  if (button) button.hidden = kind === "active" || kind === "activating";
}

function updateSettingsCopy() {
  const label = document.querySelector('label[for="apiKey"]');
  if (label) label.textContent = "X-DSG-API-Key (Developer mode)";
  const input = byId("apiKey");
  if (input) input.placeholder = "Optional for developers — first Run activates Free Evaluation automatically";
  const notice = byId("activationNotice");
  if (notice && !notice.textContent.trim()) {
    notice.textContent = "Normal evaluation does not require copying an API key. Free Evaluation uses a session-only credential; paid/developer keys remain available here.";
  }
  const old = document.querySelector('label[for="apiKey"]')?.parentElement;
  if (old && !byId("developerKeyHelp")) {
    const help = document.createElement("p");
    help.id = "developerKeyHelp";
    help.className = "muted";
    help.style.margin = "7px 0 0";
    help.textContent = "Use this field only for a paid, marketplace, or developer-managed key. Free Evaluation is activated automatically and is not persisted to localStorage.";
    old.appendChild(help);
  }
}

async function refreshUsage() {
  const key = freeKey();
  if (!key) return;
  try {
    const response = await nativeFetch(`${configuredBase()}/billing/usage`, {
      headers: { Accept: "application/json", "X-DSG-API-Key": key }
    });
    if (!response.ok) return;
    const usage = await response.json();
    const remaining = usage.units_remaining;
    const text = remaining == null
      ? `${usage.units || 0} executions used · no configured hard cap`
      : `${remaining} executions remaining · No payment required`;
    updateEvaluationStatus("active", "Free evaluation ready", text);
  } catch (_) {}
}

async function activateFreeEvaluation({ retryRun: shouldRetryRun = false } = {}) {
  if (freeKey()) {
    await refreshUsage();
    if (shouldRetryRun) retryRun();
    return;
  }
  if (activating) {
    await activating;
    if (shouldRetryRun) retryRun();
    return;
  }

  activating = (async () => {
    updateEvaluationStatus("activating", "Activating Free Evaluation…", "Creating a session-only credential. No payment card is required.");
    const notice = byId("activationNotice");
    if (notice) notice.textContent = "Activating Free Evaluation for this browser session…";
    const response = await nativeFetch(`${configuredBase()}/billing/activate`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({
        channel: "api",
        activation_id: activationId(),
        display_name: "DSG ONE browser evaluation"
      })
    });
    let payload = null;
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) {
      const code = jsonErrorCode(payload) || `HTTP_${response.status}`;
      const message = payload?.message || payload?.detail?.message || "Free Evaluation activation failed.";
      throw new Error(`${code}: ${message}`);
    }
    if (!payload?.api_key || typeof payload.api_key !== "string") {
      throw new Error("ACTIVATION_KEY_UNAVAILABLE: this activation did not return a reusable browser credential. Start a new browser session or use a developer key in Settings.");
    }
    saveFreeKey(payload.api_key);
    try { sessionStorage.setItem(FREE_PLAN, JSON.stringify(payload.plan || {})); } catch (_) {}
    if (notice) notice.textContent = "Free Evaluation is active for this browser session. The key is not saved to localStorage.";
    const remaining = payload.plan?.hard_cap_units ?? payload.plan?.included_units;
    updateEvaluationStatus(
      "active",
      "Free evaluation ready",
      remaining == null ? "No payment required" : `${remaining} executions included · No payment required`
    );
    await refreshUsage();
  })();

  try {
    await activating;
    if (shouldRetryRun) retryRun();
  } catch (error) {
    updateEvaluationStatus("needs-activation", "Free Evaluation could not be activated", error.message || "Retry activation or open Developer Settings.");
    const notice = byId("activationNotice");
    if (notice) notice.textContent = error.message || "Activation failed.";
    throw error;
  } finally {
    activating = null;
  }
}

async function ensureDsgKey() {
  let key = activeDsgKey();
  if (key) return key;
  await activateFreeEvaluation({ retryRun: false });
  key = activeDsgKey();
  if (!key) throw new Error("No DSG credential is available for this browser session.");
  return key;
}

function currentPlanDefinition() {
  const raw = byId("runInput")?.value || "";
  let definition;
  try { definition = JSON.parse(raw); }
  catch (error) { throw new Error(`The run definition is not valid JSON: ${error.message}`); }
  if (!definition?.plan || !Array.isArray(definition.plan.steps)) {
    throw new Error("The run definition needs a plan with steps before it can be approved.");
  }
  return definition;
}

function readApprovedPlan() {
  try {
    const raw = sessionStorage.getItem(APPROVED_PLAN);
    return raw ? JSON.parse(raw) : null;
  } catch (_) { return null; }
}
function saveApprovedPlan(record) {
  try { sessionStorage.setItem(APPROVED_PLAN, JSON.stringify(record)); } catch (_) {}
}
function clearApprovedPlan() {
  try { sessionStorage.removeItem(APPROVED_PLAN); } catch (_) {}
}
function sameApprovedPlan(record, definition) {
  return Boolean(record && definition && record.plan_json === JSON.stringify(definition.plan));
}

function ensureGovernanceStatus() {
  let host = byId("governanceActionStatus");
  if (host) return host;
  const actions = byId("btnRun")?.closest(".actions");
  if (!actions?.parentNode) return null;
  host = document.createElement("div");
  host.id = "governanceActionStatus";
  host.className = "note";
  host.style.marginTop = "12px";
  host.innerHTML = '<div><strong data-role="title">Plan approval</strong><div data-role="detail" style="margin-top:4px">Review the run definition, then approve the exact DSG-computed plan hash.</div></div>';
  actions.parentNode.insertBefore(host, actions.nextSibling);
  return host;
}

function setGovernanceStatus(title, detail, state = "") {
  const host = ensureGovernanceStatus();
  if (!host) return;
  host.dataset.state = state;
  const titleNode = host.querySelector('[data-role="title"]');
  const detailNode = host.querySelector('[data-role="detail"]');
  if (titleNode) titleNode.textContent = title;
  if (detailNode) detailNode.textContent = detail;
}

async function keyedJson(path, { method = "GET", body } = {}, key) {
  const headers = { Accept: "application/json", "X-DSG-API-Key": key };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await nativeFetch(`${configuredBase()}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store"
  });
  let payload = null;
  try { payload = await response.json(); } catch (_) {}
  if (!response.ok) {
    const code = jsonErrorCode(payload) || `HTTP_${response.status}`;
    const message = payload?.message || payload?.detail?.message || payload?.detail || "Request failed.";
    throw new Error(`${code}: ${typeof message === "string" ? message : JSON.stringify(message)}`);
  }
  return payload;
}

async function approveCurrentPlan() {
  const button = byId("btnApprovePlan");
  if (button) button.disabled = true;
  try {
    const definition = currentPlanDefinition();
    const existing = readApprovedPlan();
    if (sameApprovedPlan(existing, definition) && existing?.approved?.status === "APPROVED") {
      setGovernanceStatus("APPROVED", `Plan ${existing.created.plan_id} is already locked to ${existing.created.plan_hash}.`, "approved");
      if (button) button.textContent = "✓ APPROVED";
      return existing;
    }

    setGovernanceStatus("Creating plan…", "DSG is computing the authoritative plan hash from the exact JSON shown above.", "busy");
    const key = await ensureDsgKey();
    const created = await keyedJson("/api/v1/plans", { method: "POST", body: definition.plan }, key);
    if (!created?.plan_id || !created?.plan_hash) throw new Error("Plan creation returned no plan_id or plan_hash.");

    setGovernanceStatus("Waiting for approval…", `Plan ${created.plan_id} · hash ${created.plan_hash}`, "busy");
    const approved = await keyedJson(`/api/v1/plans/${encodeURIComponent(created.plan_id)}/approve`, {
      method: "POST",
      body: {
        approver: (byId("approver")?.value || "").trim() || "unknown-approver",
        plan_hash: created.plan_hash
      }
    }, key);
    if (approved?.status !== "APPROVED") throw new Error("Cinema did not return status APPROVED for the exact plan hash.");

    const record = {
      plan_json: JSON.stringify(definition.plan),
      created,
      approved,
      approved_at: new Date().toISOString()
    };
    saveApprovedPlan(record);
    setGovernanceStatus("APPROVED", `Plan ${created.plan_id} locked to ${created.plan_hash}. Run full flow will reuse this real approval.`, "approved");
    if (button) button.textContent = "✓ APPROVED";
    return record;
  } catch (error) {
    setGovernanceStatus("Approval failed", error.message || "The plan could not be approved.", "error");
    if (button) button.textContent = "✓ Approve Plan";
    throw error;
  } finally {
    if (button) button.disabled = false;
  }
}

function installApprovedPlanReuse() {
  const originalApi = window.api;
  if (typeof originalApi !== "function" || originalApi.__dsgApprovedPlanReuse) return;

  const governedApi = async function(path, options = {}) {
    const record = readApprovedPlan();
    let definition = null;
    try { definition = currentPlanDefinition(); } catch (_) {}
    if (sameApprovedPlan(record, definition)) {
      const method = String(options.method || "GET").toUpperCase();
      if (path === "/api/v1/plans" && method === "POST") return record.created;
      if (path === `/api/v1/plans/${record.created.plan_id}/approve` && method === "POST") return record.approved;
    }
    return originalApi(path, options);
  };
  governedApi.__dsgApprovedPlanReuse = true;
  window.api = governedApi;
}

function ensureSharedBrowserOverlay() {
  let overlay = byId("dsgSharedBrowserOverlay");
  if (overlay) return overlay;
  overlay = document.createElement("div");
  overlay.id = "dsgSharedBrowserOverlay";
  overlay.hidden = true;
  overlay.style.cssText = "position:fixed;inset:0;z-index:9999;background:rgba(3,8,18,.94);padding:10px;display:flex;flex-direction:column;gap:8px";
  overlay.innerHTML = '<div style="display:flex;gap:8px;align-items:center"><strong>DSG Shared Browser</strong><span id="dsgSharedBrowserMeta" class="muted" style="flex:1"></span><button class="btn" id="btnCloseSharedBrowser">Close</button></div><iframe id="dsgSharedBrowserFrame" title="DSG Shared Browser" style="width:100%;height:calc(100vh - 58px);border:1px solid rgba(94,124,190,.32);border-radius:10px;background:#111"></iframe>';
  document.body.appendChild(overlay);
  byId("btnCloseSharedBrowser")?.addEventListener("click", () => {
    overlay.hidden = true;
    overlay.style.display = "none";
    const frame = byId("dsgSharedBrowserFrame");
    if (frame) frame.src = "about:blank";
  });
  return overlay;
}

async function openSharedBrowser() {
  const button = byId("btnSharedBrowser");
  if (button) button.disabled = true;
  try {
    setGovernanceStatus("Opening shared browser…", "Requesting a short-lived same-origin viewer from Cinema.", "busy");
    const key = await ensureDsgKey();
    const live = await keyedJson("/remote-browser/browserbase/live-frame", { method: "GET" }, key);
    if (live?.connected !== true || !live?.embed_url) {
      const reason = live?.prerequisite || "Remote is not connected yet. Turn Remote ON and connect the approved agent session first.";
      throw new Error(typeof reason === "string" ? reason : JSON.stringify(reason));
    }

    const overlay = ensureSharedBrowserOverlay();
    const frame = byId("dsgSharedBrowserFrame");
    const meta = byId("dsgSharedBrowserMeta");
    if (meta) meta.textContent = `${live.provider || "managed"} · ${live.browser_session_id || live.browserbase_session_id || "shared session"}`;
    if (frame) frame.src = new URL(live.embed_url, configuredBase()).toString();
    overlay.hidden = false;
    overlay.style.display = "flex";
    setGovernanceStatus("Shared browser connected", "The browser below is the same managed session shared with the agent; no DSG master key is placed in the viewer URL.", "approved");
  } catch (error) {
    setGovernanceStatus("Shared browser unavailable", error.message || "Cinema could not open the shared browser.", "error");
    throw error;
  } finally {
    if (button) button.disabled = false;
  }
}

function ensureGovernanceControls() {
  const actions = byId("btnRun")?.closest(".actions");
  if (!actions || byId("btnApprovePlan")) return;

  const approve = document.createElement("button");
  approve.className = "btn";
  approve.id = "btnApprovePlan";
  approve.type = "button";
  approve.textContent = "✓ Approve Plan";
  approve.addEventListener("click", () => approveCurrentPlan().catch(() => {}));

  const browser = document.createElement("button");
  browser.className = "btn";
  browser.id = "btnSharedBrowser";
  browser.type = "button";
  browser.textContent = "▣ Shared Browser";
  browser.addEventListener("click", () => openSharedBrowser().catch(() => {}));

  const reset = byId("btnReset");
  actions.insertBefore(approve, reset || null);
  actions.insertBefore(browser, reset || null);
  ensureGovernanceStatus();

  const definition = (() => { try { return currentPlanDefinition(); } catch (_) { return null; } })();
  const record = readApprovedPlan();
  if (sameApprovedPlan(record, definition) && record?.approved?.status === "APPROVED") {
    approve.textContent = "✓ APPROVED";
    setGovernanceStatus("APPROVED", `Plan ${record.created.plan_id} is already approved for this browser session.`, "approved");
  }

  byId("runInput")?.addEventListener("input", () => {
    const current = (() => { try { return currentPlanDefinition(); } catch (_) { return null; } })();
    const approved = readApprovedPlan();
    if (!sameApprovedPlan(approved, current)) {
      approve.textContent = "✓ Approve Plan";
      setGovernanceStatus("Plan changed — approval required", "Approve the exact current plan before relying on the approval state.", "pending");
    }
  });

  reset?.addEventListener("click", () => {
    clearApprovedPlan();
    approve.textContent = "✓ Approve Plan";
    setGovernanceStatus("Plan approval", "Sample reset. Approve the exact plan hash when ready.", "pending");
  });
}

function installCaptureHandlers() {
  const run = byId("btnRun");
  if (run) {
    run.addEventListener("click", async (event) => {
      if (manualKeyPresent() || freeKey()) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      run.disabled = true;
      try {
        await activateFreeEvaluation({ retryRun: true });
      } catch (_) {
        run.disabled = false;
      }
    }, true);
  }

  const activate = byId("btnActivateFree");
  if (activate) {
    activate.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      try { await activateFreeEvaluation({ retryRun: false }); } catch (_) {}
    }, true);
  }

  const disconnect = byId("btnDisconnect");
  if (disconnect) {
    disconnect.addEventListener("click", () => {
      clearFreeKey();
      clearApprovedPlan();
      updateEvaluationStatus("needs-activation", "Free evaluation not activated", "Session credential cleared. Run again to activate Free Evaluation.");
      setGovernanceStatus("Plan approval", "Session credential and cached approval UI state cleared.", "pending");
    }, true);
  }
}

function bootstrap() {
  updateSettingsCopy();
  ensureEvaluationStatus();
  ensureGovernanceControls();
  installApprovedPlanReuse();
  installCaptureHandlers();
  if (freeKey()) refreshUsage();
  else updateEvaluationStatus("needs-activation", "Free evaluation not activated", "Your first Run activates a session-only free key automatically.");
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
else bootstrap();
})();
'''


@router.get(_SCRIPT_PATH, include_in_schema=False)
def free_evaluation_script() -> Response:
    return Response(
        _SCRIPT,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


class OneClickEvaluationMiddleware(BaseHTTPMiddleware):
    """Inject the managed free-evaluation controller into the existing console.

    The underlying console file stays the exact verification UI used by contract
    tests. This layer changes credential and explicit approval/browser UX only;
    it does not change authorization or verification semantics.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method == "GET" and request.url.path == "/app":
            html = _CONSOLE.read_text(encoding="utf-8")
            marker = "</body>"
            injected = f'<script src="{_SCRIPT_PATH}"></script>\n{marker}'
            if marker in html:
                html = html.replace(marker, injected, 1)
            return HTMLResponse(
                html,
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )
        return await call_next(request)


def install(app: FastAPI) -> None:
    app.include_router(router)
    app.add_middleware(OneClickEvaluationMiddleware)
