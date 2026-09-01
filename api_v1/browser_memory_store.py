"""Provider facade for Browser Operational Memory.

PostgreSQL remains the structured/table backend when explicitly configured.
Azure production can instead use the already-mounted Azure Files store without
provisioning a second paid service.
"""

from __future__ import annotations

import os
from typing import Any

from . import browser_memory as postgres
from . import browser_memory_file as azure_files

DEFAULT_ACTIVE_TOKEN_BUDGET = postgres.DEFAULT_ACTIVE_TOKEN_BUDGET
MAX_ACTIVE_TOKEN_BUDGET = postgres.MAX_ACTIVE_TOKEN_BUDGET


def backend() -> str:
    if postgres.database_url():
        return "postgres"
    requested = (os.getenv("DSG_BROWSER_MEMORY_BACKEND") or "").strip().lower()
    if requested in {"azure_files", "files"}:
        return "azure_files"
    return "disabled"


def configured() -> bool:
    return backend() != "disabled"


def record_observation(**kwargs: Any):
    selected = backend()
    if selected == "postgres":
        return postgres.record_observation(**kwargs)
    if selected == "azure_files":
        return azure_files.record_observation(**kwargs)
    return None


def search_context(**kwargs: Any) -> dict[str, Any]:
    selected = backend()
    if selected == "postgres":
        result = postgres.search_context(**kwargs)
        result.setdefault("backend", "postgres")
        return result
    if selected == "azure_files":
        return azure_files.search_context(**kwargs)
    budget = max(
        1_000,
        min(int(kwargs.get("token_budget", DEFAULT_ACTIVE_TOKEN_BUDGET)), MAX_ACTIVE_TOKEN_BUDGET),
    )
    return {
        "available": False,
        "backend": "disabled",
        "stored_memory_count": 0,
        "stored_token_estimate": 0,
        "selected_token_estimate": 0,
        "token_budget": budget,
        "memories": [],
    }


__all__ = [
    "DEFAULT_ACTIVE_TOKEN_BUDGET",
    "MAX_ACTIVE_TOKEN_BUDGET",
    "backend",
    "configured",
    "record_observation",
    "search_context",
]
