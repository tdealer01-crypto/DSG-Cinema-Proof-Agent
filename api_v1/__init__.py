"""DSG ONE v1 verification API.

The contract this package implements is `openapi/dsg-one-v1.yaml`. Its one
non-negotiable rule: DSG computes verdicts, agents submit raw material.
"""

from __future__ import annotations

API_VERSION = "1.0.0"
ENGINE_VERSION = "dsg-one-independent-verification-1.0.0"

__all__ = ["API_VERSION", "ENGINE_VERSION", "install", "router"]


def install(app) -> None:
    """Mount verification, control, evidence attestation, transport, billing, Marketplace, and compliance."""
    import importlib

    router_module = importlib.import_module(f"{__name__}.router")
    importlib.import_module(f"{__name__}.exact_select").install_mcp_tool()
    router_module.install(app)
    importlib.import_module(f"{__name__}.control").install(app)
    # DSG Live reuses the v1 Decision Core, but its customer monitor/control
    # transport deliberately lives outside /api/v1 so the independent
    # verification OpenAPI remains exact. The transport also installs the
    # existing Live MCP tools onto /api/v1/mcp.
    importlib.import_module(f"{__name__}.live_transport").install(app)
    importlib.import_module(f"{__name__}.live_ui").install(app)
    importlib.import_module(f"{__name__}.mutation").install(app)
    importlib.import_module(f"{__name__}.stripe_app_executor").install(app)
    importlib.import_module(f"{__name__}.mobile_control").install(app)
    importlib.import_module(f"{__name__}.improvement_attestation").install(app)
    # Remote browser reuses the v1 Decision Core internally, but its HTTP
    # transport deliberately lives outside /api/v1 so the independent
    # verification contract remains a separate, exact integration surface.
    importlib.import_module(f"{__name__}.remote_transport").install(app)
    # Pairing is the user-facing chat-driven authority switch: the dashboard
    # only enables/disables Remote, while the agent supplies plan/step intent.
    importlib.import_module(f"{__name__}.remote_pairing").install(app)
    # Short-lived agent credentials keep the master API key out of model/tool
    # payloads while preserving the exact existing MCP authorization path.
    importlib.import_module(f"{__name__}.agent_pairing").install(app)
    # Managed execution is exposed only through authenticated signed relays.
    # Browserbase remains supported, while Azure-native Chromium uses the same
    # signature/nonce trust boundary through its own exact route.
    importlib.import_module(f"{__name__}.remote_relay_security").install(app)
    importlib.import_module(f"{__name__}.azure_relay_security").install(app)
    # The Live View bridge is provider-neutral at runtime even though the module
    # keeps its historical filename for dashboard compatibility.
    importlib.import_module(f"{__name__}.browserbase_live_ui").install(app)
    # ChatGPT/MCP-compatible action transport. This is intentionally mounted at
    # /mcp rather than under /api/v1 so remote execution cannot drift the
    # independent verification OpenAPI contract.
    importlib.import_module(f"{__name__}.remote_mcp").install(app)
    # The customer-facing conversation and five-panel monitor stay on /dashboard.
    # Paired agents read/reply through the same /mcp authority; this module does
    # not embed or impersonate an AI model when no agent client is connected.
    importlib.import_module(f"{__name__}.dashboard_chat").install(app)
    # Universal workspace execution reuses the exact stored plan + user approval
    # boundary. Browser work remains on remote_action; local shell/Python execution
    # is test/sandbox-only unless an isolated executor is configured explicitly.
    importlib.import_module(f"{__name__}.universal_runtime").install(app)
    # Browser Memory is always mounted as an authenticated REST/status surface and
    # sanitized capture middleware. MCP tools are advertised only when a durable
    # PostgreSQL memory store is actually configured, so tool discovery never
    # promises an unavailable capability.
    memory_runtime = importlib.import_module(f"{__name__}.browser_memory_runtime")
    app.add_middleware(memory_runtime.BrowserMemoryCaptureMiddleware)
    app.include_router(memory_runtime.router)
    if memory_runtime.browser_memory.configured():
        memory_runtime.install_mcp_tools()
    # Flat REST adapter for ChatGPT Custom Actions. It translates explicit
    # operation-specific inputs back into the same canonical MCP handlers, so
    # Custom Actions never need to preserve nested JSON-RPC params themselves.
    importlib.import_module(f"{__name__}.chatgpt_remote_actions").install(app)
    # Compliance is Cinema-native and intentionally reports readiness evidence,
    # not certification or legal conformity claims.
    importlib.import_module(f"{__name__}.compliance").install(app)
    # Managed browser evaluation keeps free credentials session-only and turns
    # first Run into one-click activation without changing backend gate semantics.
    importlib.import_module(f"{__name__}.free_evaluation_ui").install(app)
    importlib.import_module("revenue.checkout").install(app)
    importlib.import_module("revenue.marketing_api").install(app)
    importlib.import_module("revenue.github_marketplace").install(app)
    importlib.import_module("revenue.stripe_marketplace").install(app)


def __getattr__(name: str):  # lazy so importing constants does not pull FastAPI
    if name == "router":
        import importlib

        return importlib.import_module(f"{__name__}.router").router
    raise AttributeError(name)