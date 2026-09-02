const $ = id => document.getElementById(id);
const KEY_SLOT = "dsg-one-key-session";
let key = "";
let busy = false;
let generation = 0;
let controller = new AbortController();
let remoteBusy = false;

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
  $("remoteAgentState").textContent = connection === "connected" ? "Connected" : connection === "waiting" ? "Waiting for agent" : "Off";
  $("remoteSession").textContent = enabled
    ? (connection === "connected" ? "Agent is connected to the approved execution. You can keep using the browser at the same time." : "Remote is ready. Continue in the agent chat; Cinema is waiting for the agent to connect.")
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
  renderRemoteStatus({ remote_enabled: false, agent_connection: "off" });
  remoteMessage("");
}

function clearCredentials({ forgetSession = true } = {}) {
  generation += 1;
  controller.abort();
  controller = new AbortController();
  key = "";
  busy = false;
  if (forgetSession) forgetSessionKey();
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
      } catch (marketingError) {
        // Marketing is downstream of activation and must never invalidate a real API key.
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
    try {
      await api("/billing/marketing/event", { method: "POST", body: JSON.stringify({ event: "checkout_started" }) });
    } catch (_) {
      // Checkout truth is independent of downstream marketing availability.
    }
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
    remoteMessage("Remote ON. Continue in your agent chat; you do not need to enter plan IDs, step IDs, agent names or endpoints here.");
  } catch (error) {
    remoteMessage(error.message, true);
  } finally {
    remoteBusy = false;
    await refreshRemoteStatus();
  }
};

$("remoteOff").onclick = async () => {
  if (remoteBusy || !key) return;
  remoteBusy = true;
  remoteMessage("Revoking agent remote authority…");
  try {
    const body = await api("/remote-browser/disable", { method: "POST" });
    renderRemoteStatus(body);
    remoteMessage("Remote OFF. Agent remote authority was revoked; your browser session stays live.");
  } catch (error) {
    remoteMessage(error.message, true);
  } finally {
    remoteBusy = false;
    await refreshRemoteStatus();
  }
};

setInterval(() => {
  if (key && !document.hidden) refreshRemoteStatus();
}, 4000);

resumeSession();