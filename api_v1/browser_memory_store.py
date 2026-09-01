"""Provider facade for Browser Operational Memory.

PostgreSQL remains the structured/table backend when explicitly configured.
Azure production can instead use the already-mounted Azure Files store without
provisioning a second paid service.

The facade is also the final active-context budget boundary. Individual storage
backends may evolve independently, but no caller through this module can receive
more estimated tokens than the requested bounded budget.
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


def _budget(kwargs: dict[str, Any]) -> int:
    return max(
        1_000,
        min(int(kwargs.get("token_budget", DEFAULT_ACTIVE_TOKEN_BUDGET)), MAX_ACTIVE_TOKEN_BUDGET),
    )


def _enforce_active_budget(result: dict[str, Any], budget: int) -> dict[str, Any]:
    """Fail closed on retrieval expansion beyond the declared active budget.

    Memory records are atomic in V1; an oversized record is skipped rather than
    truncated because truncation could change meaning or provenance. Later
    summary/chunk layers can produce smaller derived records explicitly.
    """

    memories = result.get("memories")
    if not isinstance(memories, list):
        memories = []
    selected: list[dict[str, Any]] = []
    selected_tokens = 0
    for item in memories:
        if not isinstance(item, dict):
            continue
        try:
            estimated = max(0, int(item.get("token_estimate", 0)))
        except (TypeError, ValueError):
            continue
        if selected_tokens + estimated > budget:
            continue
        selected.append(item)
        selected_tokens += estimated
        if selected_tokens >= budget:
            break
    bounded = dict(result)
    bounded["token_budget"] = budget
    bounded["memories"] = selected
    bounded["selected_token_estimate"] = selected_tokens
    bounded["active_context_bounded"] = True
    return bounded


def search_context(**kwargs: Any) -> dict[str, Any]:
    budget = _budget(kwargs)
    selected = backend()
    if selected == "postgres":
        result = postgres.search_context(**kwargs)
        result.setdefault("backend", "postgres")
        return _enforce_active_budget(result, budget)
    if selected == "azure_files":
        return _enforce_active_budget(azure_files.search_context(**kwargs), budget)
    return {
        "available": False,
        "backend": "disabled",
        "stored_memory_count": 0,
        "stored_token_estimate": 0,
        "selected_token_estimate": 0,
        "token_budget": budget,
        "active_context_bounded": True,
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
