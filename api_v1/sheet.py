"""DSG Sheet: a deterministic 1..100 capability fabric for MCP composition.

The sheet is intentionally provider-agnostic. DSG owns the execution/governance
contract; external systems occupy cells as capabilities rather than becoming the
system topology. Persistent storage is represented by a source-controlled Neon
migration, while this module is the canonical runtime contract used by MCP and
tests so absence of a database can never fabricate a READY state.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .models import Strict

SHEET_SIZE = 100

# Cell IDs are stable API. Renaming a provider does not move the cell silently.
# `capabilities` are intentionally coarse DSG capabilities, not vendor API names.
ASSIGNED_CELLS: dict[int, dict[str, Any]] = {
    1: {"slug": "dsg-core", "name": "DSG Core", "kind": "core", "provider": "dsg", "capabilities": ["runtime"]},
    2: {"slug": "governance", "name": "Governance", "kind": "core", "provider": "dsg", "capabilities": ["governance", "policy", "permission"]},
    3: {"slug": "execution", "name": "Execution", "kind": "core", "provider": "dsg", "capabilities": ["execution"]},
    4: {"slug": "z3", "name": "Z3", "kind": "core", "provider": "dsg", "capabilities": ["exact-verification", "solver"]},
    5: {"slug": "evidence", "name": "Evidence", "kind": "core", "provider": "dsg", "capabilities": ["evidence"]},
    6: {"slug": "proof", "name": "Proof", "kind": "core", "provider": "dsg", "capabilities": ["proof"]},
    7: {"slug": "replay", "name": "Replay", "kind": "core", "provider": "dsg", "capabilities": ["replay"]},
    8: {"slug": "identity", "name": "Identity", "kind": "core", "provider": "dsg", "capabilities": ["identity"]},
    9: {"slug": "connection-broker", "name": "Connection Broker", "kind": "core", "provider": "dsg", "capabilities": ["connection", "credential-broker"]},
    10: {"slug": "mcp", "name": "MCP Surface", "kind": "interface", "provider": "dsg", "capabilities": ["mcp"]},
    11: {"slug": "neon-postgres", "name": "Neon Postgres", "kind": "provider", "provider": "neon", "capabilities": ["memory", "postgres", "state"]},
    12: {"slug": "github", "name": "GitHub", "kind": "provider", "provider": "github", "capabilities": ["source", "repository", "ci"]},
    13: {"slug": "stripe", "name": "Stripe", "kind": "provider", "provider": "stripe", "capabilities": ["payment", "billing", "commerce"]},
    14: {"slug": "azure-devops", "name": "Azure DevOps", "kind": "provider", "provider": "microsoft", "capabilities": ["devops", "pipeline", "deployment"]},
    15: {"slug": "aws-cdk", "name": "AWS CDK", "kind": "provider", "provider": "aws", "capabilities": ["infrastructure", "cloud", "deployment"]},
    16: {"slug": "nvidia", "name": "NVIDIA", "kind": "provider", "provider": "nvidia", "capabilities": ["gpu", "inference"]},
    17: {"slug": "openai", "name": "OpenAI Developers", "kind": "provider", "provider": "openai", "capabilities": ["model", "agent", "inference"]},
    18: {"slug": "activecampaign", "name": "ActiveCampaign", "kind": "provider", "provider": "activecampaign", "capabilities": ["crm", "marketing"]},
    19: {"slug": "appdeploy", "name": "AppDeploy", "kind": "provider", "provider": "appdeploy", "capabilities": ["app-delivery", "deployment"]},
    20: {"slug": "marketplace", "name": "Marketplace", "kind": "surface", "provider": "dsg", "capabilities": ["storefront", "distribution"]},
    21: {"slug": "supabase", "name": "Supabase", "kind": "provider", "provider": "supabase", "capabilities": ["database", "auth", "storage", "realtime"]},
}


class SheetCellArgs(Strict):
    cell_id: int = Field(ge=1, le=SHEET_SIZE)


class SheetComposeArgs(Strict):
    goal: str = Field(min_length=1, max_length=1024)
    required_capabilities: list[str] = Field(min_length=1, max_length=64)


def _cell(cell_id: int) -> dict[str, Any]:
    assigned = ASSIGNED_CELLS.get(cell_id)
    if assigned is None:
        return {
            "cell_id": cell_id,
            "occupied": False,
            "slug": None,
            "name": None,
            "kind": "empty",
            "provider": None,
            "capabilities": [],
        }
    return {"cell_id": cell_id, "occupied": True, **assigned}


def sheet_snapshot() -> dict[str, Any]:
    cells = [_cell(cell_id) for cell_id in range(1, SHEET_SIZE + 1)]
    occupied = sum(1 for item in cells if item["occupied"])
    return {
        "status": "PASSED",
        "sheet_size": SHEET_SIZE,
        "occupied_count": occupied,
        "empty_count": SHEET_SIZE - occupied,
        "cells": cells,
    }


def get_cell(cell_id: int) -> dict[str, Any]:
    return {"status": "PASSED", "cell": _cell(cell_id)}


def compose(goal: str, required_capabilities: list[str]) -> dict[str, Any]:
    required = sorted({item.strip().lower() for item in required_capabilities if item.strip()})
    if not required:
        return {
            "status": "BLOCKED",
            "reason": "NO_CAPABILITIES_REQUESTED",
            "goal": goal,
            "required_capabilities": [],
            "selected_cells": [],
        }

    providers_by_capability: dict[str, list[int]] = {}
    for cell_id, item in ASSIGNED_CELLS.items():
        for capability in item["capabilities"]:
            providers_by_capability.setdefault(capability, []).append(cell_id)

    selected: set[int] = set()
    resolution: list[dict[str, Any]] = []
    missing: list[str] = []
    for capability in required:
        choices = sorted(providers_by_capability.get(capability, []))
        if not choices:
            missing.append(capability)
            resolution.append({"capability": capability, "status": "MISSING", "cell_id": None})
            continue
        cell_id = choices[0]
        selected.add(cell_id)
        resolution.append({"capability": capability, "status": "RESOLVED", "cell_id": cell_id})

    selected_cells = [_cell(cell_id) for cell_id in sorted(selected)]
    if missing:
        return {
            "status": "BLOCKED",
            "reason": "MISSING_CAPABILITY",
            "goal": goal,
            "required_capabilities": required,
            "missing_capabilities": missing,
            "resolution": resolution,
            "selected_cells": selected_cells,
        }

    return {
        "status": "PASSED",
        "goal": goal,
        "required_capabilities": required,
        "resolution": resolution,
        "selected_cells": selected_cells,
    }


async def _sheet_list(_: Any) -> dict[str, Any]:
    return sheet_snapshot()


async def _sheet_get(args: SheetCellArgs) -> dict[str, Any]:
    return get_cell(args.cell_id)


async def _sheet_compose(args: SheetComposeArgs) -> dict[str, Any]:
    return compose(args.goal, args.required_capabilities)


def install_mcp_tools() -> None:
    """Register read-only deterministic Sheet tools on the existing MCP server."""
    from . import mcp

    definitions = (
        mcp._Tool(
            "dsg_sheet_list",
            "List the deterministic DSG Sheet of exactly 100 capability cells. Empty cells are explicit.",
            None,
            _sheet_list,
        ),
        mcp._Tool(
            "dsg_sheet_get",
            "Read one DSG Sheet cell by stable numeric cell_id (1..100).",
            SheetCellArgs,
            _sheet_get,
        ),
        mcp._Tool(
            "dsg_sheet_compose",
            "Resolve required DSG capabilities into stable Sheet cells. Missing capability fails closed as BLOCKED.",
            SheetComposeArgs,
            _sheet_compose,
        ),
    )

    changed = False
    for tool in definitions:
        if tool.name in mcp._BY_NAME:
            continue
        mcp._BY_NAME[tool.name] = tool
        mcp.TOOLS = (*mcp.TOOLS, tool)
        changed = True

    if changed:
        # The current MCP transport advertises listChanged=False; tools are installed
        # during application startup before any MCP client initializes.
        assert len({tool.name for tool in mcp.TOOLS}) == len(mcp.TOOLS)
