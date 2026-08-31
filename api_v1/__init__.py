"""DSG ONE v1 verification API.

The contract this package implements is `openapi/dsg-one-v1.yaml`. Its one
non-negotiable rule: DSG computes verdicts, agents submit raw material.
"""

from __future__ import annotations

API_VERSION = "1.0.0"
ENGINE_VERSION = "dsg-one-independent-verification-1.0.0"

__all__ = ["API_VERSION", "ENGINE_VERSION", "install", "router"]


def install(app) -> None:
    """Mount verification, control, evidence attestation, transport, billing, and Marketplace."""
    import importlib

    router_module = importlib.import_module(f"{__name__}.router")
    importlib.import_module(f"{__name__}.exact_select").install_mcp_tool()
    router_module.install(app)
    importlib.import_module(f"{__name__}.control").install(app)
    importlib.import_module(f"{__name__}.live_monitor").install(app)
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
    # Managed execution is exposed only through the authenticated relay wrapper.
    # The implementation module itself is intentionally not mounted directly,
    # so no unsigned public path can reach Browserbase.
    importlib.import_module(f"{__name__}.remote_relay_security").install(app)
    # The Live View bridge keeps the dashboard CSP same-origin while giving the
    # user an interactive view of the exact Browserbase session used by agents.
    importlib.import_module(f"{__name__}.browserbase_live_ui").install(app)
    # ChatGPT/MCP-compatible action transport. This is intentionally mounted at
    # /mcp rather than under /api/v1 so remote execution cannot drift the
    # independent verification OpenAPI contract.
    importlib.import_module(f"{__name__}.remote_mcp").install(app)
    # Flat REST adapter for ChatGPT Custom Actions. It translates explicit
    # operation-specific inputs back into the same canonical MCP handlers, so
    # Custom Actions never need to preserve nested JSON-RPC params themselves.
    importlib.import_module(f"{__name__}.chatgpt_remote_actions").install(app)
    importlib.import_module("revenue.checkout").install(app)
    importlib.import_module("revenue.marketing_api").install(app)
    importlib.import_module("revenue.github_marketplace").install(app)
    importlib.import_module("revenue.stripe_marketplace").install(app)


def __getattr__(name: str):  # lazy so importing constants does not pull FastAPI
    if name == "router":
        import importlib

        return importlib.import_module(f"{__name__}.router").router
    raise AttributeError(name)
