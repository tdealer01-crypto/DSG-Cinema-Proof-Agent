from __future__ import annotations

import os
from typing import Any

import httpx

CINEMA_MCP_URL = os.getenv(
    "CINEMA_MCP_URL",
    "https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/api/v1/mcp",
)
CINEMA_API_KEY = os.getenv("CINEMA_API_KEY", "").strip()
CINEMA_MCP_TIMEOUT_SECONDS = float(os.getenv("CINEMA_MCP_TIMEOUT_SECONDS", "20"))


class CinemaMcpError(RuntimeError):
    pass


async def call_cinema_mcp(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if CINEMA_API_KEY:
        headers["X-DSG-API-Key"] = CINEMA_API_KEY

    payload = {
        "jsonrpc": "2.0",
        "id": "pibench-cinema",
        "method": method,
    }
    if params is not None:
        payload["params"] = params

    try:
        async with httpx.AsyncClient(timeout=CINEMA_MCP_TIMEOUT_SECONDS) as client:
            response = await client.post(CINEMA_MCP_URL, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise CinemaMcpError(f"Cinema MCP transport failed: {type(exc).__name__}") from exc

    if response.status_code != 200:
        raise CinemaMcpError(f"Cinema MCP returned HTTP {response.status_code}")

    try:
        body = response.json()
    except ValueError as exc:
        raise CinemaMcpError("Cinema MCP returned non-JSON data") from exc

    if not isinstance(body, dict):
        raise CinemaMcpError("Cinema MCP returned an invalid JSON-RPC envelope")
    if body.get("error"):
        error = body.get("error")
        if isinstance(error, dict):
            raise CinemaMcpError(str(error.get("message") or "Cinema MCP error"))
        raise CinemaMcpError("Cinema MCP error")

    result = body.get("result")
    if not isinstance(result, dict):
        raise CinemaMcpError("Cinema MCP returned no object result")
    return result


async def cinema_status() -> dict[str, Any]:
    return await call_cinema_mcp("tools/call", {"name": "dsg_status", "arguments": {}})


async def cinema_tools() -> dict[str, Any]:
    return await call_cinema_mcp("tools/list")
