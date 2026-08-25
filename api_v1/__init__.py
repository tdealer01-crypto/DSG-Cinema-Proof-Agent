"""DSG ONE v1 verification API.

The contract this package implements is `openapi/dsg-one-v1.yaml`. Its one
non-negotiable rule: DSG computes verdicts, agents submit raw material.
"""

from __future__ import annotations

API_VERSION = "1.0.0"
ENGINE_VERSION = "dsg-one-independent-verification-1.0.0"

__all__ = ["API_VERSION", "ENGINE_VERSION", "install", "router"]


def install(app) -> None:
    """Mount verification, control, remote transport, mobile, billing, and Marketplace."""
    import importlib

    importlib.import_module(f"{__name__}.router").install(app)
    importlib.import_module(f"{__name__}.control").install(app)
    importlib.import_module(f"{__name__}.mutation").install(app)
    importlib.import_module(f"{__name__}.stripe_app_executor").install(app)
    importlib.import_module(f"{__name__}.mobile_control").install(app)
    # Remote browser reuses the v1 Decision Core internally, but its HTTP
    # transport deliberately lives outside /api/v1 so the independent
    # verification contract remains a separate, exact integration surface.
    importlib.import_module(f"{__name__}.remote_transport").install(app)
    # Pairing is the user-facing chat-driven authority switch: the dashboard
    # only enables/disables Remote, while the agent supplies plan/step/endpoint.
    importlib.import_module(f"{__name__}.remote_pairing").install(app)
    importlib.import_module("revenue.checkout").install(app)
    importlib.import_module("revenue.github_marketplace").install(app)
    importlib.import_module("revenue.stripe_marketplace").install(app)


def __getattr__(name: str):  # lazy so importing constants does not pull FastAPI
    if name == "router":
        import importlib

        return importlib.import_module(f"{__name__}.router").router
    raise AttributeError(name)
