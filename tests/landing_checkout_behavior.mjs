import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const landingPath = process.argv[2];
if (!landingPath) throw new Error("landing path is required");

const html = fs.readFileSync(landingPath, "utf8");
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)].map(
  (match) => match[1],
);
const commerceScript = scripts.find((script) =>
  script.includes("SUBSCRIPTION_POLL_ATTEMPTS"),
);
assert.ok(commerceScript, "checkout commerce script was not found");

const SESSION_KEY_STORE = "dsg.api.session-key";
const CHECKOUT_ID_STORE = "dsg.checkout.id";
const API_KEY = `dsg_live_${"a".repeat(16)}_${"b".repeat(48)}`;

class MemoryStorage {
  constructor(initial = {}) {
    this.values = new Map(Object.entries(initial));
  }

  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null;
  }

  setItem(key, value) {
    this.values.set(key, String(value));
  }

  removeItem(key) {
    this.values.delete(key);
  }
}

class MockNode {
  constructor(id) {
    this.id = id;
    this.disabled = id === "checkoutButton" || id === "clearKeyButton";
    this.style = {};
    this.className = id.startsWith("badge") ? "badge warn" : "";
    this.listeners = new Map();
    this.history = [];
    this.value = "";
    this.scrolled = false;
    this._textContent = "";
    this.classList = {
      contains: (name) => this.className.split(/\s+/).includes(name),
    };
  }

  get textContent() {
    return this._textContent;
  }

  set textContent(value) {
    this._textContent = String(value);
    this.history.push(this._textContent);
  }

  addEventListener(name, handler) {
    const handlers = this.listeners.get(name) || [];
    handlers.push(handler);
    this.listeners.set(name, handlers);
  }

  async click() {
    for (const handler of this.listeners.get("click") || []) {
      await handler({ currentTarget: this });
    }
  }

  scrollIntoView() {
    this.scrolled = true;
  }
}

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    async json() {
      return body;
    },
  };
}

async function waitFor(predicate, message) {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setImmediate(resolve));
  }
  throw new Error(message);
}

function boot({ key = "", search = "", checkoutId = "", fetchImpl }) {
  const nodeIds = [
    "checkoutButton",
    "checkoutNotice",
    "clearKeyButton",
    "apiKeyField",
    "checkoutState",
    "badgeMetered",
    "badgeTeam",
    "activationState",
    "marketplaceState",
    "badgeMarketplace",
    "marketplaceNotice",
    "verify",
  ];
  const nodes = Object.fromEntries(nodeIds.map((id) => [id, new MockNode(id)]));
  const sessionStorage = new MemoryStorage({
    ...(key ? { [SESSION_KEY_STORE]: key } : {}),
    ...(checkoutId ? { [CHECKOUT_ID_STORE]: checkoutId } : {}),
  });
  const localStorage = new MemoryStorage();
  const calls = [];
  const windowListeners = new Map();
  const location = {
    hostname: "dsgoneverifiedweb.z1.web.core.windows.net",
    search,
    assigned: null,
    assign(url) {
      this.assigned = url;
    },
  };
  const window = {
    addEventListener(name, handler) {
      const handlers = windowListeners.get(name) || [];
      handlers.push(handler);
      windowListeners.set(name, handlers);
    },
    dispatch(name) {
      for (const handler of windowListeners.get(name) || []) handler({ type: name });
    },
  };
  const context = {
    URL,
    URLSearchParams,
    Promise,
    console,
    crypto: { randomUUID: () => "00000000-0000-4000-8000-000000000000" },
    document: {
      getElementById(id) {
        if (!nodes[id]) nodes[id] = new MockNode(id);
        return nodes[id];
      },
    },
    fetch: async (url, options = {}) => {
      calls.push({ url, options });
      return fetchImpl(url, options, calls);
    },
    localStorage,
    location,
    sessionStorage,
    setTimeout: (handler) => {
      Promise.resolve().then(handler);
      return 1;
    },
    clearTimeout: () => {},
    window,
  };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(commerceScript, context, { filename: landingPath });
  return { calls, localStorage, location, nodes, sessionStorage, window };
}

const linkedStatus = {
  checkout_status: "LINKED",
  metering_enabled: true,
  stripe: { charges_enabled: true },
};

function baseFetch(url) {
  if (url.endsWith("/billing/status")) return jsonResponse(linkedStatus);
  if (url.endsWith("/marketplace/github/status")) {
    return jsonResponse({ status: "READY" });
  }
  throw new Error(`unexpected request: ${url}`);
}

async function testKeyGateAndForget() {
  const env = boot({ fetchImpl: baseFetch });
  await waitFor(
    () => env.nodes.checkoutState.textContent === "READY",
    "billing status did not render",
  );
  assert.equal(env.nodes.checkoutButton.disabled, true);
  assert.equal(env.nodes.checkoutButton.textContent, "Activate free key first");

  env.sessionStorage.setItem(SESSION_KEY_STORE, API_KEY);
  env.nodes.apiKeyField.value = API_KEY;
  env.window.dispatch("dsg-key-updated");
  assert.equal(env.nodes.checkoutButton.disabled, false);
  assert.equal(env.nodes.checkoutButton.textContent, "Upgrade with Stripe");
  assert.equal(env.nodes.clearKeyButton.disabled, false);

  await env.nodes.clearKeyButton.click();
  assert.equal(env.sessionStorage.getItem(SESSION_KEY_STORE), null);
  assert.equal(env.nodes.apiKeyField.value, "");
  assert.equal(env.nodes.checkoutButton.disabled, true);
  assert.match(env.nodes.checkoutNotice.textContent, /does not revoke/i);
}

async function testTrustedCheckoutRedirect() {
  const checkoutUrl = "https://checkout.stripe.com/c/pay/cs_live_verified";
  const env = boot({
    key: API_KEY,
    fetchImpl(url, options) {
      if (url.endsWith("/billing/checkout/session")) {
        return jsonResponse(
          {
            state: "CHECKOUT_CREATED_NOT_ENTITLED",
            entitled: false,
            checkout_url: checkoutUrl,
          },
          { status: 201 },
        );
      }
      return baseFetch(url, options);
    },
  });
  await waitFor(
    () => env.nodes.checkoutButton.disabled === false,
    "checkout button did not become ready",
  );
  await env.nodes.checkoutButton.click();

  const request = env.calls.find((call) =>
    call.url.endsWith("/billing/checkout/session"),
  );
  assert.ok(request, "checkout request was not sent");
  assert.equal(request.options.method, "POST");
  assert.equal(request.options.headers["X-DSG-API-Key"], API_KEY);
  assert.deepEqual(JSON.parse(request.options.body), {
    plan: "metered",
    checkout_id: "web-checkout-00000000-0000-4000-8000-000000000000",
  });
  assert.equal(env.location.assigned, checkoutUrl);
  assert.match(env.nodes.checkoutNotice.textContent, /wait for a signed webhook/i);
  assert.doesNotMatch(env.nodes.checkoutNotice.textContent, /plan is active/i);
}

async function testUntrustedCheckoutRedirectIsRejected() {
  const env = boot({
    key: API_KEY,
    fetchImpl(url, options) {
      if (url.endsWith("/billing/checkout/session")) {
        return jsonResponse(
          {
            state: "CHECKOUT_CREATED_NOT_ENTITLED",
            entitled: false,
            checkout_url: "https://checkout.stripe.com.evil.example/phish",
          },
          { status: 201 },
        );
      }
      return baseFetch(url, options);
    },
  });
  await waitFor(
    () => env.nodes.checkoutButton.disabled === false,
    "checkout button did not become ready",
  );
  await env.nodes.checkoutButton.click();
  assert.equal(env.location.assigned, null);
  assert.match(env.nodes.checkoutNotice.textContent, /failed the DSG trust contract/i);
}

async function testSuccessWaitsForWebhookState() {
  let subscriptionCalls = 0;
  const env = boot({
    key: API_KEY,
    search: "?checkout=success",
    checkoutId: "checkout-before-return",
    fetchImpl(url, options) {
      if (url.endsWith("/billing/subscription")) {
        subscriptionCalls += 1;
        return jsonResponse(
          subscriptionCalls === 1
            ? { subscription_active: false, payment_linked: false }
            : { subscription_active: true, payment_linked: true },
        );
      }
      return baseFetch(url, options);
    },
  });
  await waitFor(
    () => env.nodes.checkoutNotice.textContent.includes("Payment verified by signed webhook"),
    "signed-webhook subscription state was not rendered",
  );
  assert.equal(subscriptionCalls, 2);
  assert.equal(env.nodes.badgeMetered.textContent, "ACTIVE");
  assert.equal(env.nodes.checkoutButton.textContent, "Metered plan active");
  assert.equal(env.nodes.checkoutButton.disabled, true);
  assert.equal(env.sessionStorage.getItem(CHECKOUT_ID_STORE), null);

  const waitingIndex = env.nodes.checkoutNotice.history.findIndex((value) =>
    value.includes("Waiting for signed Stripe webhook confirmation"),
  );
  const activeIndex = env.nodes.checkoutNotice.history.findIndex((value) =>
    value.includes("Payment verified by signed webhook"),
  );
  assert.ok(waitingIndex >= 0 && activeIndex > waitingIndex);
}

async function testCancelledCheckoutClearsRetryIdWithoutClaimingPayment() {
  let subscriptionCalls = 0;
  const env = boot({
    key: API_KEY,
    search: "?checkout=cancelled",
    checkoutId: "cancelled-checkout",
    fetchImpl(url, options) {
      if (url.endsWith("/billing/subscription")) subscriptionCalls += 1;
      return baseFetch(url, options);
    },
  });
  await waitFor(
    () => env.nodes.checkoutNotice.textContent.includes("Checkout was cancelled"),
    "cancelled state was not rendered",
  );
  assert.equal(subscriptionCalls, 0);
  assert.equal(env.sessionStorage.getItem(CHECKOUT_ID_STORE), null);
  assert.doesNotMatch(env.nodes.checkoutNotice.textContent, /paid|active/i);
}

async function testStatusFailureDisablesCheckout() {
  const env = boot({
    key: API_KEY,
    fetchImpl(url) {
      if (url.endsWith("/billing/status")) throw new Error("offline");
      if (url.endsWith("/marketplace/github/status")) {
        return jsonResponse({ status: "READY" });
      }
      throw new Error(`unexpected request: ${url}`);
    },
  });
  await waitFor(
    () => env.nodes.checkoutNotice.textContent.includes("Checkout status is unavailable"),
    "fail-closed status was not rendered",
  );
  assert.equal(env.nodes.checkoutButton.disabled, true);
  assert.equal(env.location.assigned, null);
}

await testKeyGateAndForget();
await testTrustedCheckoutRedirect();
await testUntrustedCheckoutRedirectIsRejected();
await testSuccessWaitsForWebhookState();
await testCancelledCheckoutClearsRetryIdWithoutClaimingPayment();
await testStatusFailureDisablesCheckout();

console.log("landing checkout behavior: ok");
