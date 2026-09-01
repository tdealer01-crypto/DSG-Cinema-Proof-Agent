(() => {
  let lastEmbedUrl = "";
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
      if (!embedUrl.startsWith("/remote-browser/browserbase/embed/")) {
        throw new Error("Cinema returned an invalid shared-browser viewer URL");
      }
      host.hidden = false;
      if (hint) {
        hint.textContent = body.context_persistent
          ? "This is your persistent browser. Sign in once; when Remote is ON an approved agent joins this same session and plan scope."
          : "You and the agent are viewing and controlling this same browser session.";
      }
      if (frame && embedUrl !== lastEmbedUrl) {
        frame.src = embedUrl;
        lastEmbedUrl = embedUrl;
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
