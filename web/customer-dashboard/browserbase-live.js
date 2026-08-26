(() => {
  let lastUrl = "";
  let timer = null;

  function panel() {
    let host = document.getElementById("sharedBrowserLive");
    if (host) return host;
    const card = document.querySelector(".remote-card");
    if (!card) return null;

    host = document.createElement("section");
    host.id = "sharedBrowserLive";
    host.hidden = true;
    host.style.marginTop = "14px";
    host.innerHTML = `
      <div class="label">Shared live browser · User + Agent</div>
      <p class="status" id="sharedBrowserHint">Waiting for the managed browser session.</p>
      <div style="margin-top:8px;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#0c0d0f">
        <iframe id="sharedBrowserFrame" title="Shared Browser Live View"
          allow="clipboard-read; clipboard-write"
          style="display:block;width:100%;height:min(68vh,720px);border:0;background:#fff"></iframe>
      </div>`;

    const evidence = card.querySelector(".remote-evidence");
    if (evidence) card.insertBefore(host, evidence);
    else card.appendChild(host);
    return host;
  }

  function clearLiveView(message = "Waiting for the managed browser session.") {
    const host = panel();
    if (!host) return;
    const frame = document.getElementById("sharedBrowserFrame");
    const hint = document.getElementById("sharedBrowserHint");
    host.hidden = true;
    if (frame && frame.src) frame.removeAttribute("src");
    if (hint) hint.textContent = message;
    lastUrl = "";
  }

  async function refreshLiveView() {
    if (typeof key === "undefined" || !key) {
      clearLiveView();
      return;
    }
    try {
      const body = await api("/remote-browser/browserbase/live-view");
      const host = panel();
      if (!host) return;
      const frame = document.getElementById("sharedBrowserFrame");
      const hint = document.getElementById("sharedBrowserHint");
      const liveUrl = typeof body.live_view_url === "string" ? body.live_view_url : "";
      if (!body.connected || !liveUrl) {
        clearLiveView("Remote is armed, but the agent has not provisioned the shared Browserbase session yet.");
        return;
      }
      if (!liveUrl.startsWith("https://")) throw new Error("Live View returned a non-HTTPS URL");
      host.hidden = false;
      if (hint) hint.textContent = "You and the agent are viewing and controlling this same browser session.";
      if (frame && liveUrl !== lastUrl) {
        frame.src = liveUrl;
        lastUrl = liveUrl;
      }
    } catch (error) {
      const host = panel();
      if (!host) return;
      const hint = document.getElementById("sharedBrowserHint");
      if (hint) hint.textContent = `Shared browser: ${error.message}`;
    }
  }

  window.addEventListener("pagehide", () => {
    if (timer) clearInterval(timer);
    clearLiveView();
  });
  document.addEventListener("DOMContentLoaded", () => {
    panel();
    refreshLiveView();
    timer = setInterval(refreshLiveView, 2500);
  });
})();
