"""DSG ONE v1 verification API.

The contract this package implements is `openapi/dsg-one-v1.yaml`. Its one
non-negotiable rule: DSG computes verdicts, agents submit raw material.
"""

from __future__ import annotations

API_VERSION = "1.0.0"
ENGINE_VERSION = "dsg-one-independent-verification-1.0.0"

__all__ = ["API_VERSION", "ENGINE_VERSION", "install", "router"]


def install(app) -> None:
    """Mount verification, mobile control, billing checkout, and Marketplace bridge."""
    import importlib

    importlib.import_module(f"{__name__}.router").install(app)
    importlib.import_module(f"{__name__}.mobile_control").install(app)
    importlib.import_module("revenue.checkout").install(app)
    importlib.import_module("revenue.github_marketplace").install(app)


def __getattr__(name: str):  # lazy so importing constants does not pull FastAPI
    if name == "router":
        import importlib

        return importlib.import_module(f"{__name__}.router").router
    raise AttributeError(name)
