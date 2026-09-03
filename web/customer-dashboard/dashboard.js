const $ = id => document.getElementById(id);
const KEY_SLOT = "dsg-one-key-session";
const PAIR_SLOT = "dsg-one-agent-pairing-token";
const PAIR_EXPIRY_SLOT = "dsg-one-agent-pairing-expiry";

function endpointUrl() { return location.origin + "/mcp"; }

function selectCopyInput(input) {
  if (!input) return;
  input.focus();
  input.select();
  try { input.setSelectionRange(0, input.value.length); } catch (_) {}
}

async function copyDashboardValue(input, value, successMessage) {
  if (!input) return;
  input.value = value;
  let copied = false;
  if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    try { await navigator.clipboard.writeText(value); copied = true; } catch (_) {}
  }
  if (!copied) {
    selectCopyInput(input);
    try { copied = document.execCommand("copy"); } catch (_) { copied = false; }
  }
  remoteMessage(
    copied ? successMessage : "Copy was blocked. The value is selected — long-press it and tap Copy.",
    !copied
  );
}

function wireAdvancedConnectionCopy() {
  const endpoint = $("mcpEndpoint");
  if (endpoint) {
    endpoint.value = endpointUrl();
    endpoint.addEventListener("click", () => selectCopyInput(endpoint));
  }
  const copyEndpoint = $("copyMcpEndpoint");
  if (copyEndpoint) {
    copyEndpoint.addEventListener("click", () => copyDashboardValue(endpoint, endpointUrl(), "MCP endpoint copied."));
  }
  const copyPair = $("copyPairingToken");
  if (copyPair) {
    copyPair.addEventListener("click", () => {
      const input = $("pairingToken");
      if (input && input.value) copyDashboardValue(input, input.value, "Short-lived pairing token copied.");
    });
  }
}
let key = "";
let busy = false;
let generation = 0;
let controller = new AbortController();
let remoteBusy = false;
let chatBusy = false;
let agentConnectBusy = false;

function readSessionKey() {
  try { return sessionStorage.getItem(KEY_SLOT) || ""; }
  catch (_) { return ""; }
}

function rememberSessionKey(value) {
  if (!value) return;
  try { sessionStorage.setItem(KEY_SLOT, value); }
  catch (_) {}
}

function forgetSessionKey() {
  try { sessionStorage.removeItem(KEY_SLOT); }
  catch (_) {}
}

function rememberPairing(token, expiresAt) {
  try {
    sessionStorage.setItem(PAIR_SLOT, token || "");
    sessionStorage.setItem(PAIR_EXPIRY_SLOT, String(expiresAt || 0));
  } catch (_) {}
  const input = $("pairingToken");
  const advanced = $("pairingAdvanced");
  if (input) input.value = token || "";
  if (advanced) advanced.hidden = !token;
}

function clearPairing() {
  try { sessionStorage.removeItem(PAIR_SLOT); sessionStorage.removeItem(PAIR_EXPIRY_SLOT); } catch (_) {}
  rememberPairing("", 0);
}

function usablePairing() {
  try {
    const token = sessionStorage.getItem(PAIR_SLOT) || "";
    const expiry = Number(sessionStorage.getItem(PAIR_EXPIRY_SLOT) || 0);
    if (token && expiry > Date.now() / 1000 + 30) return { token, expiry };
  } catch (_) {}
  clearPairing();
  return null;
}

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

function remoteMessage(text, isError = false) {
  $("remoteMessage").textContent = text || "";
  $("remoteMessage").className = isError ? "status error" : "status";
}

function renderRemoteStatus(body = {}) {
  const enabled = body.remote_enabled === true;
  const connection = body.agent_connection || (enabled ? "waiting" : "off");
  $("remoteState").textContent = enabled ? "REMOTE ON" : "REMOTE OFF";
  $("remoteState").className = enabled ? "remote-state on" : "remote-state";
  $("remoteOn").disabled = !key || enabled || remoteBusy;
  $("remoteOff").disabled = !key || !enabled || remoteBusy;
  $("connectAgent").disabled = !key || agentConnectBusy;
  $("remoteAgentState").textContent = connection === "connected" ? "Connected" : connection === "waiting" ? "Waiting for agent" : "Off";
  $("chatAgentState").textContent = connection === "connected" ? "AGENT CONNECTED" : connection === "waiting" ? "WAITING FOR AGENT" : "AGENT OFFLINE";
  $("chatAgentState").className = connection === "connected" ? "remote-state on" : "remote-state";
  $("remoteSession").textContent = enabled
    ? (connection === "connected" ? "Agent is connected to the approved execution. You can use this same browser at the same time." : "Remote is ready. Cinema is waiting for a real paired agent client to contact /mcp.")
    : "Remote is off. The user's browser remains under user control.";
  const evidence = body.latest_evidence;
  $("remoteEvidence").textContent = evidence ? JSON.stringify(evidence, null, 2) : "No remote action evidence yet.";
}

async function refreshRemoteStatus() {
  if (!key || remoteBusy) return;
  try {
    const body = await api("/remote-browser/status");
    renderRemoteStatus(body);
  } catch (error) {
    remoteMessage(`Remote status: ${error.message}`, true);
  }
}

function setUnifiedEnabled(enabled) {
  $("connectAgent").disabled = !enabled || agentConnectBusy;
  $("chatInput").disabled = !enabled;
  $("chatSend").disabled = !enabled || chatBusy;
}

function resetMonitor() {
  $("monitorConnection").textContent = "WAITING";
  $("monitorActionState").textContent = "WAITING";
  $("monitorActionDetail").textContent = "No browser action yet.";
  $("monitorPlanState").textContent = "PENDING";
  $("monitorPlanDetail").textContent = "No approved plan is bound yet.";
  $("monitorPermissionState").textContent = "REMOTE_OFF";
  $("monitorPermissionDetail").textContent = "Remote authority is off.";
  $("monitorEvidenceState").textContent = "PENDING";
  $("monitorEvidenceDetail").textContent = "No completed action evidence yet.";
  $("monitorExecutionState").textContent = "WAITING";
  $("monitorExecutionDetail").textContent = "No agent execution has been recorded yet.";
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
  $("chatMessages").innerHTML = '<div class="chat-empty">Connect your account, then connect an agent. Your conversation stays on this page.</div>';
  $("chatStatus").textContent = "";
  renderRemoteStatus({ remote_enabled: false, agent_connection: "off" });
  setUnifiedEnabled(false);
  resetMonitor();
  remoteMessage("");
}

function clearCredentials({ forgetSession = true } = {}) {
  generation += 1;
  controller.abort();
  controller = new AbortController();
  key = "";
  busy = false;
  if (forgetSession) forgetSessionKey();
  clearPairing();
  reset();
}

function showError(error) {
  clearCredentials({ forgetSession: true });
  $("message").textContent = error.message;
  $("message").className = "status error";
}

async function loadWithCurrentKey(expectedGeneration = generation) {
  if (!key) throw new Error("API key required");
  $("message").textContent = "Loading…";
  const [onboarding, usage, history, subscription, remote] = await Promise.all([
    api("/onboarding/status"),
    api("/billing/usage"),
    api("/billing/usage/history?limit=10"),
    api("/billing/subscription"),
    api("/remote-browser/status")
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
  renderRemoteStatus(remote);
  setUnifiedEnabled(true);
  const pairing = usablePairing();
  if (pairing) rememberPairing(pairing.token, pairing.expiry);
  await Promise.allSettled([refreshChat(), refreshMonitor()]);
}

async function load() {
  if (busy) return;
  const supplied = $("apiKey").value.trim();
  if (!supplied) return showError(new Error("API key required"));
  clearCredentials({ forgetSession: true });
  const expectedGeneration = generation;
  key = supplied;
  rememberSessionKey(supplied);
  busy = true;
  $("connect").disabled = true;
  try { await loadWithCurrentKey(expectedGeneration); }
  catch (error) { if (expectedGeneration === generation && error.name !== "AbortError") showError(error); }
  finally { if (expectedGeneration === generation) { busy = false; $("connect").disabled = false; } }
}

async function resumeSession() {
  const recovered = readSessionKey();
  if (!recovered || busy) return;
  const expectedGeneration = generation;
  key = recovered;
  busy = true;
  $("connect").disabled = true;
  $("connection").textContent = "RECONNECTING";
  try {
    await loadWithCurrentKey(expectedGeneration);
  } catch (error) {
    if (expectedGeneration === generation && error.name !== "AbortError") showError(error);
  } finally {
    if (expectedGeneration === generation) {
      busy = false;
      $("connect").disabled = false;
    }
  }
}

$("connect").onclick = load;
$("disconnect").onclick = () => {
  clearCredentials({ forgetSession: true });
  $("message").textContent = "Disconnected. Credentials cleared from this browser tab.";
  $("message").className = "status";
};
window.addEventListener("pagehide", () => {
  controller.abort();
  controller = new AbortController();
  key = "";
  busy = false;
});

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
  const contactEmail = $("contactEmail").value.trim();
  const marketingConsent = $("marketingConsent").checked;
  if (!displayName) return showError(new Error("Organization name required"));
  if (marketingConsent && !contactEmail) return showError(new Error("Email is required only when marketing opt-in is selected"));
  busy = true; $("activate").disabled = true;
  try {
    const response = await fetch("/billing/activate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ channel: "dashboard", activation_id: crypto.randomUUID(), display_name: displayName }) });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail?.message || body.remediation?.next_step || `HTTP ${response.status}`);
    if (typeof body.api_key !== "string" || !body.api_key.startsWith("dsg_live_")) throw new Error("Activation did not return a valid one-time key");

    let marketingMessage = "";
    if (contactEmail) {
      try {
        const identifyResponse = await fetch("/billing/marketing/identify", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-DSG-API-Key": body.api_key },
          body: JSON.stringify({ email: contactEmail, marketing_consent: marketingConsent, source: "dashboard" })
        });
        const identifyBody = await identifyResponse.json().catch(() => ({}));
        if (!identifyResponse.ok) throw new Error(identifyBody.detail || `HTTP ${identifyResponse.status}`);
        const state = identifyBody.marketing_sync?.sync_state;
        if (marketingConsent && state && state !== "SYNCED") marketingMessage = ` Marketing sync: ${state}.`;
      } catch (_) {
        marketingMessage = " Marketing profile is pending sync; your DSG account is still active.";
      }
    }

    $("issuedKey").textContent = body.api_key;
    $("newKey").hidden = false;
    $("displayName").value = "";
    $("contactEmail").value = "";
    $("marketingConsent").checked = false;
    key = body.api_key;
    rememberSessionKey(body.api_key);
    await loadWithCurrentKey();
    $("message").textContent = `Account activated and connected automatically. The key is shown once above for backup.${marketingMessage}`;
  } catch (error) { showError(error); }
  finally { busy = false; $("activate").disabled = false; }
};

$("useIssuedKey").onclick = () => {
  const issued = $("issuedKey").textContent;
  if (!issued) return;
  $("apiKey").value = issued;
  rememberSessionKey(issued);
  load();
};

$("upgrade").onclick = async () => {
  if (busy) return; busy = true; $("upgrade").disabled = true;
  try {
    const data = await api("/billing/checkout/session", { method: "POST", body: JSON.stringify({ plan: "metered", checkout_id: crypto.randomUUID() }) });
    try { await api("/billing/marketing/event", { method: "POST", body: JSON.stringify({ event: "checkout_started" }) }); } catch (_) {}
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

$("remoteOn").onclick = async () => {
  if (remoteBusy || !key) return;
  remoteBusy = true;
  remoteMessage("Enabling Remote…");
  try {
    const body = await api("/remote-browser/enable", { method: "POST" });
    renderRemoteStatus(body);
    remoteMessage("Remote ON. The shared browser remains yours while an approved agent can join the same session.");
  } catch (error) { remoteMessage(error.message, true); }
  finally { remoteBusy = false; await refreshRemoteStatus(); await refreshMonitor(); }
};

$("remoteOff").onclick = async () => {
  if (remoteBusy || !key) return;
  remoteBusy = true;
  remoteMessage("Revoking agent remote authority…");
  try {
    const body = await api("/remote-browser/disable", { method: "POST" });
    renderRemoteStatus(body);
    remoteMessage("Remote OFF. Agent remote authority was revoked; your browser session stays live.");
  } catch (error) { remoteMessage(error.message, true); }
  finally { remoteBusy = false; await refreshRemoteStatus(); await refreshMonitor(); }
};

$("connectAgent").onclick = async () => {
  if (!key || agentConnectBusy) return;
  agentConnectBusy = true;
  $("connectAgent").disabled = true;
  remoteMessage("Preparing secure agent pairing…");
  try {
    const enabled = await api("/remote-browser/enable", { method: "POST" });
    renderRemoteStatus(enabled);
    const pairing = await api("/remote-browser/agent-pair", {
      method: "POST",
      body: JSON.stringify({ agent_name: "chat-agent", ttl_seconds: 600 })
    });
    if (!pairing.pairing_token) throw new Error("Cinema returned no pairing token");
    rememberPairing(pairing.pairing_token, pairing.expires_at_unix);
    remoteMessage("Pairing is ready. Cinema will show Connected only after a real agent client contacts /mcp. No page change is required.");
  } catch (error) {
    remoteMessage(error.message, true);
  } finally {
    agentConnectBusy = false;
    setUnifiedEnabled(true);
    await refreshRemoteStatus();
    await refreshMonitor();
  }
};

function renderApproval(message, host) {
  const approval = message.approval;
  if (!approval) return;
  const box = document.createElement("div");
  box.className = "approval-box";
  const summary = document.createElement("div");
  summary.className = "status";
  summary.textContent = `${approval.summary || "Plan approval"} · ${approval.plan_id || ""}`;
  box.appendChild(summary);
  if (approval.status === "pending") {
    const actions = document.createElement("div");
    actions.className = "actions";
    for (const [label, decision, secondary] of [["Approve", "approve", false], ["Reject", "reject", true]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = secondary ? "btn secondary" : "btn";
      button.textContent = label;
      button.onclick = async () => {
        button.disabled = true;
        try {
          await api("/dashboard/api/chat/approval", { method: "POST", body: JSON.stringify({ message_id: message.message_id, decision }) });
          await Promise.all([refreshChat(), refreshRemoteStatus(), refreshMonitor()]);
        } catch (error) { $("chatStatus").textContent = error.message; }
      };
      actions.appendChild(button);
    }
    box.appendChild(actions);
  } else {
    const state = document.createElement("strong");
    state.textContent = approval.status.toUpperCase();
    box.appendChild(state);
  }
  host.appendChild(box);
}

function renderChat(messages) {
  const host = $("chatMessages");
  host.replaceChildren();
  if (!messages.length) {
    const empty = document.createElement("div");
    empty.className = "chat-empty";
    empty.textContent = "No messages yet. Send a message; a paired agent can read and reply through Cinema MCP.";
    host.appendChild(empty);
    return;
  }
  for (const message of messages) {
    const row = document.createElement("article");
    row.className = `chat-message ${message.role || "system"}`;
    const role = document.createElement("div");
    role.className = "chat-role";
    role.textContent = message.role === "user" ? "YOU" : message.role === "agent" ? (message.agent_name || "AGENT") : "DSG";
    const text = document.createElement("div");
    text.className = "chat-text";
    text.textContent = message.text || "";
    row.append(role, text);
    renderApproval(message, row);
    host.appendChild(row);
  }
  host.scrollTop = host.scrollHeight;
}

async function refreshChat() {
  if (!key || chatBusy || document.hidden) return;
  try {
    const body = await api("/dashboard/api/chat/messages?after_seq=0&limit=100");
    renderChat(body.messages || []);
  } catch (error) {
    $("chatStatus").textContent = `Chat: ${error.message}`;
  }
}

async function sendChat() {
  if (!key || chatBusy) return;
  const text = $("chatInput").value.trim();
  if (!text) return;
  chatBusy = true;
  $("chatSend").disabled = true;
  $("chatStatus").textContent = "Sending…";
  try {
    await api("/dashboard/api/chat/messages", { method: "POST", body: JSON.stringify({ text }) });
    $("chatInput").value = "";
    $("chatStatus").textContent = "Queued for the paired agent.";
    await refreshChat();
  } catch (error) {
    $("chatStatus").textContent = error.message;
  } finally {
    chatBusy = false;
    $("chatSend").disabled = !key;
  }
}

$("chatSend").onclick = sendChat;
$("chatInput").addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendChat(); }
});

function panelDetail(panel, kind) {
  if (!panel) return "—";
  if (kind === "action") {
    const bits = [panel.actor, panel.action, panel.target].filter(Boolean);
    return bits.length ? bits.join(" · ") : "No browser action yet.";
  }
  return panel.detail || "—";
}

async function refreshMonitor() {
  if (!key || document.hidden) return;
  try {
    const body = await api("/dashboard/api/monitor");
    const panels = body.panels || {};
    $("monitorConnection").textContent = body.agent_connection === "connected" ? "LIVE" : body.agent_connection === "waiting" ? "WAITING AGENT" : "REMOTE OFF";
    $("monitorConnection").className = body.agent_connection === "connected" ? "remote-state on" : "remote-state";
    const mappings = [
      ["action", "monitorActionState", "monitorActionDetail"],
      ["plan_alignment", "monitorPlanState", "monitorPlanDetail"],
      ["permission", "monitorPermissionState", "monitorPermissionDetail"],
      ["evidence", "monitorEvidenceState", "monitorEvidenceDetail"],
      ["execution_audit", "monitorExecutionState", "monitorExecutionDetail"]
    ];
    for (const [name, stateId, detailId] of mappings) {
      const panel = panels[name] || {};
      $(stateId).textContent = panel.status || "PENDING";
      $(detailId).textContent = panelDetail(panel, name);
    }
  } catch (error) {
    $("monitorConnection").textContent = "ERROR";
    $("monitorExecutionDetail").textContent = error.message;
  }
}

setInterval(() => {
  if (key && !document.hidden) {
    refreshRemoteStatus();
    refreshChat();
    refreshMonitor();
  }
}, 2000);

wireAdvancedConnectionCopy();
resumeSession();