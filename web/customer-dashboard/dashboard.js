const $ = id => document.getElementById(id);
let key = "";
let busy = false;
let generation = 0;
let controller = new AbortController();
let remoteToken = "";
let remoteSessionId = "";
let remoteBusy = false;

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}), "X-DSG-API-Key": key };
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers, signal: controller.signal });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail?.message || body.detail?.error || body.detail || `HTTP ${response.status}`);
  return body;
}

function renderHistory(items) {
  const host = $("history");
  host.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "status";
    empty.textContent = "No verified proof usage yet.";
    host.appendChild(empty);
    return;
  }
  items.forEach(item => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "history-row";
    row.onclick = () => loadProofDetail(item.sequence);
    const when = document.createElement("span");
    when.textContent = new Date(item.recorded_at).toLocaleDateString();
    const hash = document.createElement("span");
    hash.className = "hash";
    hash.textContent = item.proof_hash;
    hash.title = item.proof_hash;
    const amount = document.createElement("span");
    amount.textContent = `$${(item.amount_micros / 1_000_000).toFixed(2)}`;
    row.append(when, hash, amount);
    host.appendChild(row);
  });
}

async function loadProofDetail(sequence) {
  if (!key || busy) return;
  busy = true;
  try {
    const detail = await api(`/billing/usage/history/${sequence}`);
    $("detailProofHash").textContent = detail.proof_hash;
    $("detailContextHash").textContent = detail.context_hash;
    $("detailEntryHash").textContent = detail.entry_hash;
    $("detailAmount").textContent = `$${(detail.amount_micros / 1_000_000).toFixed(2)}`;
    $("proofDetail").hidden = false;
  } catch (error) {
    $("message").textContent = error.message;
    $("message").className = "status error";
  } finally {
    busy = false;
  }
}

$("closeProofDetail").onclick = () => {
  $("proofDetail").hidden = true;
  for (const id of ["detailProofHash", "detailContextHash", "detailEntryHash", "detailAmount"]) $(id).textContent = "";
};

function renderRemoteOff(reason = "No remote session.") {
  remoteToken = "";
  remoteSessionId = "";
  $("remoteState").textContent = "REMOTE OFF";
  $("remoteState").className = "remote-state";
  $("remoteOn").disabled = false;
  $("remoteOff").disabled = true;
  $("remoteSend").disabled = true;
  $("remoteSession").textContent = reason;
}

function renderRemoteOn(body) {
  remoteToken = body.session_token;
  remoteSessionId = body.session_id;
  $("remoteState").textContent = "REMOTE ON";
  $("remoteState").className = "remote-state on";
  $("remoteOn").disabled = true;
  $("remoteOff").disabled = false;
  $("remoteSend").disabled = false;
  $("remoteSession").textContent = `Session ${body.session_id} · plan ${body.plan_id} · step ${body.step_id} · endpoint hidden`;
}

function remoteMessage(text, isError = false) {
  $("remoteMessage").textContent = text || "";
  $("remoteMessage").className = isError ? "status error" : "status";
}

function requiredRemote(id, label) {
  const value = $(id).value.trim();
  if (!value) throw new Error(`${label} required`);
  return value;
}

function reset() {
  $("apiKey").value = "";
  $("issuedKey").textContent = "";
  $("newKey").hidden = true;
  $("disconnect").disabled = true;
  $("connection").textContent = "NOT CONNECTED";
  $("connection").style.color = "";
  $("plan").textContent = $("usage").textContent = $("remaining").textContent = "—";
  $("progressBar").style.width = "0";
  $("progressText").textContent = "Connect to load progress";
  $("steps").replaceChildren();
  $("billingChannel").textContent = "○ channel";
  $("paymentState").textContent = "○ payment";
  $("subscriptionState").textContent = "○ subscription";
  for (const id of ["billingChannel", "paymentState", "subscriptionState"]) $(id).className = "step";
  renderHistory([]);
  $("proofDetail").hidden = true;
  for (const id of ["detailProofHash", "detailContextHash", "detailEntryHash", "detailAmount"]) $(id).textContent = "";
  $("next").textContent = "Connect your account to continue.";
  $("message").textContent = "";
  $("message").className = "status";
  $("connect").disabled = false;
  $("activate").disabled = false;
  $("upgrade").disabled = $("portal").disabled = $("firstProof").disabled = true;
  renderRemoteOff("Dashboard disconnected; no agent remote authority is available from this page.");
  $("remoteEvidence").textContent = "No action evidence yet.";
  remoteMessage("");
}

function clearCredentials() {
  generation += 1;
  controller.abort();
  controller = new AbortController();
  key = "";
  busy = false;
  reset();
}

function showError(error) {
  clearCredentials();
  $("message").textContent = error.message;
  $("message").className = "status error";
}

async function loadWithCurrentKey(expectedGeneration = generation) {
  if (!key) throw new Error("API key required");
  $("message").textContent = "Loading…";
  const [onboarding, usage, history, subscription] = await Promise.all([
    api("/onboarding/status"), api("/billing/usage"), api("/billing/usage/history?limit=10"), api("/billing/subscription")
  ]);
  if (expectedGeneration !== generation || !key) return;
  $("apiKey").value = "";
  $("connection").textContent = "CONNECTED";
  $("disconnect").disabled = false;
  $("connection").style.color = "var(--green)";
  $("plan").textContent = usage.account.plan;
  $("usage").textContent = usage.units;
  $("remaining").textContent = usage.units_remaining ?? "Uncapped";
  $("progressBar").style.width = `${onboarding.progress}%`;
  $("progressText").textContent = `${onboarding.progress}% · ${onboarding.current_step}`;
  $("steps").replaceChildren();
  Object.entries(onboarding.steps).forEach(([name, done]) => {
    const node = document.createElement("div");
    node.className = `step ${done ? "done" : ""}`;
    node.textContent = `${done ? "✓" : "○"} ${name.replaceAll("_", " ")}`;
    $("steps").appendChild(node);
  });
  renderHistory(history.items);
  $("billingChannel").textContent = `✓ ${subscription.billing_channel}`;
  $("billingChannel").className = "step done";
  $("paymentState").textContent = `${subscription.payment_linked ? "✓" : "○"} payment ${subscription.payment_linked ? "linked" : "not linked"}`;
  $("paymentState").className = `step ${subscription.payment_linked ? "done" : ""}`;
  $("subscriptionState").textContent = `${subscription.subscription_active ? "✓" : "○"} subscription ${subscription.subscription_active ? "active" : "inactive"}`;
  $("subscriptionState").className = `step ${subscription.subscription_active ? "done" : ""}`;
  $("next").textContent = onboarding.next_action ? `${onboarding.next_action.method} ${onboarding.next_action.endpoint}` : "Onboarding complete";
  $("firstProof").disabled = onboarding.current_step !== "RUN_FIRST_PROOF";
  $("upgrade").disabled = subscription.billing_channel === "github_marketplace" || !usage.upgrade?.recommended;
  $("portal").disabled = !subscription.can_manage_in_portal;
  $("message").textContent = usage.upgrade?.recommended ? `Upgrade recommended: ${usage.upgrade.reason}` : "Account ready";
  $("message").className = "status";
}

async function load() {
  if (busy) return;
  const supplied = $("apiKey").value.trim();
  if (!supplied) return showError(new Error("API key required"));
  clearCredentials();
  const expectedGeneration = generation;
  key = supplied;
  busy = true;
  $("connect").disabled = true;
  try { await loadWithCurrentKey(expectedGeneration); }
  catch (error) { if (expectedGeneration === generation && error.name !== "AbortError") showError(error); }
  finally { if (expectedGeneration === generation) { busy = false; $("connect").disabled = false; } }
}

$("connect").onclick = load;
$("disconnect").onclick = () => {
  clearCredentials();
  $("message").textContent = "Disconnected. Credentials cleared from this page.";
  $("message").className = "status";
};
window.addEventListener("pagehide", clearCredentials);

$("firstProof").onclick = async () => {
  if (busy || !key) return;
  busy = true; $("firstProof").disabled = true; $("message").textContent = "Running exact Z3 proof…";
  try {
    const receipt = await api("/onboarding/first-proof", { method: "POST" });
    if (receipt.verified !== true || receipt.verification !== "VERIFIED_GLOBAL_OPTIMUM") throw new Error("First proof did not return an exact verified receipt");
    const resultMessage = `${receipt.decision} · ${receipt.verification} · ${receipt.proof_hash.slice(0, 16)}…`;
    await loadWithCurrentKey(); $("message").textContent = resultMessage; $("message").className = "status";
  } catch (error) { $("message").textContent = error.message; $("message").className = "status error"; $("firstProof").disabled = false; }
  finally { busy = false; }
};

$("activate").onclick = async () => {
  if (busy) return;
  const displayName = $("displayName").value.trim();
  if (!displayName) return showError(new Error("Organization name required"));
  busy = true; $("activate").disabled = true;
  try {
    const response = await fetch("/billing/activate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ channel: "dashboard", activation_id: crypto.randomUUID(), display_name: displayName }) });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail?.message || body.remediation?.next_step || `HTTP ${response.status}`);
    if (typeof body.api_key !== "string" || !body.api_key.startsWith("dsg_live_")) throw new Error("Activation did not return a valid one-time key");
    $("issuedKey").textContent = body.api_key; $("newKey").hidden = false; $("displayName").value = ""; $("message").textContent = "Account activated. Copy the key before continuing.";
  } catch (error) { showError(error); }
  finally { busy = false; $("activate").disabled = false; }
};

$("useIssuedKey").onclick = () => { const issued = $("issuedKey").textContent; if (!issued) return; $("apiKey").value = issued; $("issuedKey").textContent = ""; $("newKey").hidden = true; load(); };

$("upgrade").onclick = async () => {
  if (busy) return; busy = true; $("upgrade").disabled = true;
  try {
    const data = await api("/billing/checkout/session", { method: "POST", body: JSON.stringify({ plan: "metered", checkout_id: crypto.randomUUID() }) });
    const url = new URL(data.checkout_url);
    if (url.protocol !== "https:" || url.hostname !== "checkout.stripe.com" || url.username || url.password) throw new Error("Untrusted checkout URL");
    location.href = url.href;
  } catch (error) { showError(error); }
  finally { busy = false; }
};

$("portal").onclick = async () => {
  if (busy) return; busy = true; $("portal").disabled = true;
  try {
    const data = await api("/billing/portal/session", { method: "POST" });
    const url = new URL(data.portal_url);
    if (url.protocol !== "https:" || url.hostname !== "billing.stripe.com" || url.username || url.password) throw new Error("Untrusted portal URL");
    location.href = url.href;
  } catch (error) { showError(error); }
  finally { busy = false; }
};

$("remoteContract").onclick = async () => {
  if (remoteBusy) return; remoteBusy = true; remoteMessage("Checking production remote contract…");
  try {
    const response = await fetch("/remote-browser/contract", { headers: { Accept: "application/json" } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
    $("remoteEvidence").textContent = JSON.stringify(body, null, 2);
    remoteMessage(`${body.protocol} · ${body.concurrency}`);
  } catch (error) { remoteMessage(error.message, true); }
  finally { remoteBusy = false; }
};

$("remoteOn").onclick = async () => {
  if (remoteBusy) return; remoteBusy = true; remoteMessage("Opening plan-bound remote session…");
  try {
    if (!key) throw new Error("Connect a DSG API key first");
    const payload = { plan_id: requiredRemote("remotePlanId", "Approved plan ID"), agent_identity: requiredRemote("remoteAgentId", "Agent identity"), step_id: requiredRemote("remoteStepId", "Approved step ID"), remote_endpoint: requiredRemote("remoteEndpoint", "Remote endpoint"), ttl_seconds: 900 };
    const body = await api("/remote-browser/sessions", { method: "POST", body: JSON.stringify(payload) });
    if (body.remote_enabled !== true || typeof body.session_token !== "string") throw new Error("Remote session was not enabled");
    renderRemoteOn(body);
    $("remoteEvidence").textContent = JSON.stringify({ decision: body.decision, plan_hash: body.plan_hash, session_id: body.session_id, remote_enabled: body.remote_enabled, endpoint_exposed: body.endpoint_exposed }, null, 2);
    $("remoteEndpoint").value = "";
    remoteMessage("Remote connected. User and agent input channels remain independent.");
  } catch (error) { renderRemoteOff(); remoteMessage(error.message, true); }
  finally { remoteBusy = false; }
};

$("remoteSend").onclick = async () => {
  if (remoteBusy || !remoteToken) return; remoteBusy = true; $("remoteSend").disabled = true; remoteMessage("Sending action…");
  try {
    let parameters = {}; const raw = $("remoteActionParameters").value.trim();
    if (raw) { parameters = JSON.parse(raw); if (!parameters || Array.isArray(parameters) || typeof parameters !== "object") throw new Error("Action parameters must be a JSON object"); }
    const body = await api("/remote-browser/actions", { method: "POST", body: JSON.stringify({ session_token: remoteToken, action: { kind: $("remoteActionKind").value, parameters } }) });
    $("remoteEvidence").textContent = JSON.stringify({ session_id: body.session_id, action: body.action, status: body.status, evidence_hash: body.evidence_hash, remote_response: body.remote_response }, null, 2);
    remoteMessage(`Action recorded · evidence ${String(body.evidence_hash || "").slice(0, 16)}…`);
  } catch (error) { if (/expired|revoked|410/i.test(error.message)) renderRemoteOff("Remote session is no longer active."); remoteMessage(error.message, true); }
  finally { remoteBusy = false; $("remoteSend").disabled = !remoteToken; }
};

$("remoteOff").onclick = async () => {
  if (remoteBusy || !remoteToken) return; remoteBusy = true; const token = remoteToken; const session = remoteSessionId; remoteMessage("Revoking agent remote authority…");
  try {
    const body = await api("/remote-browser/disconnect", { method: "POST", body: JSON.stringify({ session_token: token }) });
    renderRemoteOff(`Remote disabled for ${session || body.session_id || "session"}. User browser remains live.`);
    $("remoteEvidence").textContent = JSON.stringify(body, null, 2);
    remoteMessage("Remote OFF. Only agent remote authority was revoked.");
  } catch (error) { remoteMessage(error.message, true); }
  finally { remoteBusy = false; }
};
