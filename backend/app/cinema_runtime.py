from __future__ import annotations

from typing import Any
from uuid import uuid4

from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel, Field

from .agent import build_root_agent
from .config import load_settings

APP_NAME = "dsg_cinema_proof_agent"


class CinemaIncidentRequest(BaseModel):
    incident: str = Field(min_length=3, max_length=8000)
    user_id: str = Field(default="judge", min_length=1, max_length=100)


class CinemaIncidentResponse(BaseModel):
    session_id: str
    answer: str
    final_event_seen: bool
    event_count: int


def _event_text(event: Any) -> str:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    texts = [getattr(part, "text", None) for part in parts]
    return "\n".join(text for text in texts if text)


async def run_cinema_incident(request: CinemaIncidentRequest) -> CinemaIncidentResponse:
    settings = load_settings()
    if not settings.grafana_mcp_url:
        raise RuntimeError(
            "GRAFANA_MCP_URL is not configured; cinema investigation is fail-closed because "
            "the workflow requires a real Grafana MCP evidence source."
        )
    agent = build_root_agent()
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    session = await runner.session_service.create_session(
        app_name=APP_NAME,
        user_id=request.user_id,
        session_id=str(uuid4()),
    )
    message = types.Content(role="user", parts=[types.Part(text=request.incident)])
    answer = ""
    event_count = 0
    final_event_seen = False

    try:
        async for event in runner.run_async(
            user_id=request.user_id,
            session_id=session.id,
            new_message=message,
        ):
            event_count += 1
            text = _event_text(event)
            is_final = bool(getattr(event, "is_final_response", lambda: False)())
            if is_final:
                final_event_seen = True
                if text:
                    answer = text
            elif text and not answer:
                answer = text
    finally:
        close = getattr(runner, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result

    if not answer:
        answer = "Agent completed without a textual final response. Inspect runtime logs."

    return CinemaIncidentResponse(
        session_id=session.id,
        answer=answer,
        final_event_seen=final_event_seen,
        event_count=event_count,
    )
