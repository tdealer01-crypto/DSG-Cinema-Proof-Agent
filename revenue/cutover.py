"""Runtime guardrails used while revenue storage changes backends."""

from __future__ import annotations

import os
from typing import Mapping


WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_TRUE = frozenset({"1", "true", "yes", "on"})


def writes_frozen(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return (source.get("DSG_REVENUE_WRITE_FROZEN") or "").strip().lower() in _TRUE


def storage_summary(engine) -> dict[str, object]:
    account_backend = getattr(engine.accounts, "backend", "unknown")
    ledger_backend = getattr(engine.ledger, "backend", "unknown")
    backend = account_backend if account_backend == ledger_backend else "mixed"
    durable_attested = (
        (os.getenv("DSG_REVENUE_STORAGE_DURABLE") or "").strip().lower() in _TRUE
    )
    durable = backend == "postgres" or (backend == "file" and durable_attested)
    return {
        "backend": backend,
        "accounts_backend": account_backend,
        "ledger_backend": ledger_backend,
        "durable": durable,
        "writes_frozen": writes_frozen(),
    }


__all__ = ["WRITE_METHODS", "storage_summary", "writes_frozen"]
