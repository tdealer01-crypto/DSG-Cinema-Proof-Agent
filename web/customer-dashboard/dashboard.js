const $ = id => document.getElementById(id);
let key = "";
let busy = false;

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}), "X-DSG-API-Key": key };
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail?.message || body.detail || `HTTP ${response.status}`);
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
    const row = document.createElement("div");
    row.className = "history-row";
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

function reset() {
  key = "";
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
  $("upgrade").disabled = $("portal").disabled = true;
}

function showError(error) {
  reset();
  $("message").textContent = error.message;
  $("message").className = "status error";
}

async function load() {
  const supplied = $("apiKey").value.trim();
  if (!supplied) return showError(new Error("API key required"));
  reset();
  key = supplied;
  $("message").textContent = "Loading…";
  try {
    const [onboarding, usage, history, subscription] = await Promise.all([
      api("/onboarding/status"),
      api("/billing/usage"),
      api("/billing/usage/history?limit=10"),
      api("/billing/subscription")
    ]);
    $("apiKey").value = "";
    $("connection").textContent = "CONNECTED";
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
    $("next").textContent = onboarding.next_action
      ? `${onboarding.next_action.method} ${onboarding.next_action.endpoint}`
      : "Onboarding complete";
    $("upgrade").disabled = !usage.upgrade?.recommended;
    $("portal").disabled = !subscription.can_manage_in_portal;
    $("message").textContent = usage.upgrade?.recommended
      ? `Upgrade recommended: ${usage.upgrade.reason}`
      : "Account ready";
    $("message").className = "status";
  } catch (error) {
    showError(error);
  }
}

$("connect").onclick = load;
$("upgrade").onclick = async () => {
  if (busy) return;
  busy = true;
  $("upgrade").disabled = true;
  try {
    const data = await api("/billing/checkout/session", {
      method: "POST",
      body: JSON.stringify({ plan: "metered", checkout_id: crypto.randomUUID() })
    });
    const url = new URL(data.checkout_url);
    if (url.protocol !== "https:" || url.hostname !== "checkout.stripe.com" || url.username || url.password) {
      throw new Error("Untrusted checkout URL");
    }
    location.href = url.href;
  } catch (error) {
    showError(error);
  } finally {
    busy = false;
  }
};
$("portal").onclick = async () => {
  if (busy) return;
  busy = true;
  $("portal").disabled = true;
  try {
    const data = await api("/billing/portal/session", { method: "POST" });
    const url = new URL(data.portal_url);
    if (url.protocol !== "https:" || url.hostname !== "billing.stripe.com" || url.username || url.password) {
      throw new Error("Untrusted portal URL");
    }
    location.href = url.href;
  } catch (error) {
    showError(error);
  } finally {
    busy = false;
  }
};
