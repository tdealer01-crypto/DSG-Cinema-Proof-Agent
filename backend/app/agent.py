from __future__ import annotations

from google.adk.agents import Agent
from google.adk.models import Gemini
try:
    from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
except ImportError:  # ADK compatibility alias
    from google.adk.tools.mcp_tool.mcp_session_manager import (
        StreamableHTTPServerParams as StreamableHTTPConnectionParams,
    )

try:
    from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
except ImportError:  # compatibility with older ADK naming
    from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset as McpToolset

from .cinema_gate import verify_recovery_plan
from .config import load_settings

settings = load_settings()

READ_ONLY_GRAFANA_TOOLS = [
    "search_dashboards",
    "get_dashboard_summary",
    "list_datasources",
    "query_prometheus",
    "query_loki_logs",
    "list_incidents",
    "get_incident",
]


def _grafana_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    if settings.grafana_cloud_stack_url:
        headers["X-Grafana-URL"] = settings.grafana_cloud_stack_url
    if settings.grafana_mcp_access_token:
        headers["Authorization"] = f"Bearer {settings.grafana_mcp_access_token}"
    elif settings.grafana_mcp_audience:
        # Secure Cloud Run-to-Cloud Run path for a self-hosted official mcp-grafana service.
        from google.auth.transport.requests import Request
        from google.oauth2.id_token import fetch_id_token

        token = fetch_id_token(Request(), settings.grafana_mcp_audience)
        headers["Authorization"] = f"Bearer {token}"
    return headers


def build_root_agent() -> Agent:
    tools = [verify_recovery_plan]
    if settings.grafana_mcp_url:
        grafana = McpToolset(
            connection_params=StreamableHTTPConnectionParams(
                url=settings.grafana_mcp_url,
                headers=_grafana_headers(),
                timeout=30,
                sse_read_timeout=60,
            ),
            tool_filter=READ_ONLY_GRAFANA_TOOLS,
        )
        tools.insert(0, grafana)

    return Agent(
        name="dsg_cinema_proof_agent",
        model=Gemini(model=settings.gemini_model),
        description=(
            "Production incident agent for film and media workloads. It uses Grafana MCP telemetry "
            "and a deterministic Z3 gate before high-risk recovery actions."
        ),
        instruction="""
You are DSG Cinema Proof Agent, an incident-response agent for film, streaming, rendering,
and studio production systems.

Mandatory execution policy:
1. Use Grafana MCP tools to gather real production evidence. Never invent metrics, logs,
   dashboards, incidents, tool results, proof hashes, or HTTP outcomes.
2. Prefer read-only Grafana investigation first: dashboards, datasources, Prometheus, Loki,
   and existing incidents.
3. Before recommending any runtime-changing recovery action, call verify_recovery_plan.
4. If the Z3 gate returns accepted=false, do not recommend the blocked action as executable.
   Explain which constraint failed and propose the smallest safe alternative.
5. restart_streaming_service is high risk. It requires both metrics and log evidence plus
   explicit human_approval=true. Never infer human approval from silence or from telemetry.
6. If Grafana MCP cannot be reached or Gemini authentication is unavailable, report the
   workflow as UNVERIFIED/BLOCKED rather than fabricating a result.
7. Keep the final response operational: observed evidence, likely cause (clearly labeled as
   inference), Z3 gate decision, safe next action, proof_hash, and audit.event_hash when present.
""".strip(),
        tools=tools,
    )


root_agent = build_root_agent()
