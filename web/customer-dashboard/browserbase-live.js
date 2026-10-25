(() => {
  let lastEmbedUrl = "";
  let lastSessionId = "";
  let viewerMountedAt = 0;
  let timer = null;

  // Both routes are same-origin capabilities. /azure/view is a historical
  // path name served by the current AWS self-hosted Playwright provider;
  // it does NOT select or connect to Azure infrastructure.
  const VIEWER_PATH = /^\/remote-browser\/(?:browserbase\/embed|self-hosted\/view|azure\/view)\/[A-Za-z0-9_-]{20,128}$/;
  const VIEWER_RENEW_MS = 50 * 60 * 1000;

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
      <div class="label">Your shared browser · User + Agent</div>
      <p class="status" id="sharedBrowserHint">Preparing your persistent browser.</p>
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

  function clearLiveView(message = "Remote is OFF. Your saved browser context is retained for the next session.") {
    const host = panel();
    if (!host) return;
    const frame = document.getElementById("sharedBrowserFrame");
    const hint = document.getElementById("sharedBrowserHint");
    host.hidden = true;
    if (frame && frame.src) frame.removeAttribute("src");
    if (hint) hint.textContent = message;
    lastEmbedUrl = "";
    lastSessionId = "";
    viewerMountedAt = 0;
  }

  async function refreshLiveView() {
    if (typeof key === "undefined" || !key) {
      clearLiveView();
      return;
    }
    try {
      const body = await api("/remote-browser/browserbase/live-frame");
      const host = panel();
      if (!host) return;
      const frame = document.getElementById("sharedBrowserFrame");
      const hint = document.getElementById("sharedBrowserHint");
      const embedUrl = typeof body.embed_url === "string" ? body.embed_url : "";
      if (!body.connected || !embedUrl) {
        clearLiveView(
          body.prerequisite === "BROWSERBASE_NOT_CONFIGURED"
            ? "Shared browser is not configured on this Cinema runtime."
            : "Remote is preparing your shared browser. Your login context will be reused when it reconnects.",
        );
        return;
      }
      if (!VIEWER_PATH.test(embedUrl)) {
        throw new Error("Cinema returned an invalid shared-browser viewer URL");
      }
      host.hidden = false;
      const sessionId = String(body.browser_session_id || body.browserbase_session_id || "");
      if (!sessionId) throw new Error("Shared browser session identity is unavailable");
      if (hint) {
        hint.textContent = "Viewer session: " + sessionId
          + ". Compare with governed Agent browser.remote.status. Different IDs mean different sessions; stop before mutations. "
          + (body.context_persistent ? "Login is retained in this viewer; do not share session tokens." : "Login persistence is NOT VERIFIED.");
      }
      // Cinema issues a new short-lived URL on every status refresh.
      // Never reload the human iframe on each poll: that loses keyboard focus
      // during sign-in. Remount only for a different verified session or when
      // the existing viewer capability is nearing expiry.
      const renew = !viewerMountedAt || Date.now() - viewerMountedAt >= VIEWER_RENEW_MS;
      if (frame && (sessionId !== lastSessionId || !frame.getAttribute("src") || renew)) {
        frame.src = embedUrl;
        lastEmbedUrl = embedUrl;
        lastSessionId = sessionId;
        viewerMountedAt = Date.now();
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
