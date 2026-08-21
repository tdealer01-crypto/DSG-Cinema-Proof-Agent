"""DSG ONE v1 verification API.

The contract this package implements is `openapi/dsg-one-v1.yaml`. Its one
non-negotiable rule: DSG computes verdicts, agents submit raw material.
"""

from __future__ import annotations

API_VERSION = "1.0.0"
ENGINE_VERSION = "dsg-one-independent-verification-1.0.0"

__all__ = ["API_VERSION", "ENGINE_VERSION", "install", "router"]


def __getattr__(name: str):  # lazy so importing constants does not pull FastAPI
    if name in {"router", "install"}:
        import importlib

        return getattr(importlib.import_module(f"{__name__}.router"), name)
    raise AttributeError(name)
