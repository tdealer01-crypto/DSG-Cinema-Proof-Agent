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
      updateEvaluationStatus("needs-activation", "Free evaluation not activated", "Session credential cleared. Run again to activate Free Evaluation.");
    }, true);
  }
}

function bootstrap() {
  updateSettingsCopy();
  ensureEvaluationStatus();
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
    tests. This layer changes credential UX only; it does not change authorization
    or verification semantics.
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
