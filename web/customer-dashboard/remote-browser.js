(() => {
  const byId = id => document.getElementById(id);
  let remoteToken = "";
  let remoteSessionId = "";
  let remoteBusy = false;

  function message(text, error = false) {
    const node = byId("remoteMessage");
    node.textContent = text || "";
    node.className = error ? "status error" : "status";
  }

  function renderOff(reason = "No remote session.") {
    remoteToken = "";
    remoteSessionId = "";
    byId("remoteState").textContent = "REMOTE OFF";
    byId("remoteState").className = "remote-state";
    byId("remoteOn").disabled = false;
    byId("remoteOff").disabled = true;
    byId("remoteSend").disabled = true;
    byId("remoteSession").textContent = reason;
  }

  function renderOn(body) {
    remoteToken = body.session_token;
    remoteSessionId = body.session_id;
    byId("remoteState").textContent = "REMOTE ON";
    byId("remoteState").className = "remote-state on";
    byId("remoteOn").disabled = true;
    byId("remoteOff").disabled = false;
    byId("remoteSend").disabled = false;
    byId("remoteSession").textContent = `Session ${body.session_id} · plan ${body.plan_id} · step ${body.step_id} · endpoint hidden`;
  }

  function required(id, label) {
    const value = byId(id).value.trim();
    if (!value) throw new Error(`${label} required`);
    return value;
  }

  async function remoteApi(path, options = {}) {
    if (typeof api !== "function") throw new Error("Dashboard API client unavailable");
    return api(path, options);
  }

  byId("remoteContract").addEventListener("click", async () => {
    if (remoteBusy) return;
    remoteBusy = true;
    message("Checking production remote contract…");
    try {
      const body = await fetch("/remote-browser/contract", { headers: { Accept: "application/json" } }).then(async response => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        return data;
      });
      byId("remoteEvidence").textContent = JSON.stringify(body, null, 2);
      message(`${body.protocol} · ${body.concurrency}`);
    } catch (error) {
      message(error.message, true);
    } finally {
      remoteBusy = false;
    }
  });

  byId("remoteOn").addEventListener("click", async () => {
    if (remoteBusy) return;
    remoteBusy = true;
    message("Opening plan-bound remote session…");
    try {
      if (!key) throw new Error("Connect a DSG API key first");
      const payload = {
        plan_id: required("remotePlanId", "Approved plan ID"),
        agent_identity: required("remoteAgentId", "Agent identity"),
        step_id: required("remoteStepId", "Approved step ID"),
        remote_endpoint: required("remoteEndpoint", "Remote endpoint"),
        ttl_seconds: 900
      };
      const body = await remoteApi("/remote-browser/sessions", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (body.remote_enabled !== true || typeof body.session_token !== "string") {
        throw new Error("Remote session was not enabled");
      }
      renderOn(body);
      byId("remoteEvidence").textContent = JSON.stringify({
        decision: body.decision,
        plan_hash: body.plan_hash,
        session_id: body.session_id,
        remote_enabled: body.remote_enabled,
        endpoint_exposed: body.endpoint_exposed
      }, null, 2);
      byId("remoteEndpoint").value = "";
      message("Remote connected. User and agent input channels remain independent.");
    } catch (error) {
      renderOff();
      message(error.message, true);
    } finally {
      remoteBusy = false;
    }
  });

  byId("remoteSend").addEventListener("click", async () => {
    if (remoteBusy || !remoteToken) return;
    remoteBusy = true;
    byId("remoteSend").disabled = true;
    message("Sending action…");
    try {
      let parameters = {};
      const raw = byId("remoteActionParameters").value.trim();
      if (raw) {
        parameters = JSON.parse(raw);
        if (!parameters || Array.isArray(parameters) || typeof parameters !== "object") throw new Error("Action parameters must be a JSON object");
      }
      const body = await remoteApi("/remote-browser/actions", {
        method: "POST",
        body: JSON.stringify({
          session_token: remoteToken,
          action: { kind: byId("remoteActionKind").value, parameters }
        })
      });
      byId("remoteEvidence").textContent = JSON.stringify({
        session_id: body.session_id,
        action: body.action,
        status: body.status,
        evidence_hash: body.evidence_hash,
        remote_response: body.remote_response
      }, null, 2);
      message(`Action recorded · evidence ${String(body.evidence_hash || "").slice(0, 16)}…`);
    } catch (error) {
      if (/expired|revoked|410/i.test(error.message)) renderOff("Remote session is no longer active.");
      message(error.message, true);
    } finally {
      remoteBusy = false;
      byId("remoteSend").disabled = !remoteToken;
    }
  });

  byId("remoteOff").addEventListener("click", async () => {
    if (remoteBusy || !remoteToken) return;
    remoteBusy = true;
    const token = remoteToken;
    message("Revoking agent remote authority…");
    try {
      const body = await remoteApi("/remote-browser/disconnect", {
        method: "POST",
        body: JSON.stringify({ session_token: token })
      });
      renderOff(`Remote disabled for ${remoteSessionId || body.session_id || "session"}. User browser remains live.`);
      byId("remoteEvidence").textContent = JSON.stringify(body, null, 2);
      message("Remote OFF. Only agent remote authority was revoked.");
    } catch (error) {
      message(error.message, true);
    } finally {
      remoteBusy = false;
    }
  });

  byId("disconnect").addEventListener("click", () => renderOff("Dashboard disconnected; remote token cleared from this page."));
  window.addEventListener("pagehide", () => {
    remoteToken = "";
    remoteSessionId = "";
  });
})();
