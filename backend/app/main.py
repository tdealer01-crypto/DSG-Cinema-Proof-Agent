from __future__ import annotations

import contextlib
import hmac
import json
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse
from mcp.server.fastmcp import FastMCP

from .audit import create_audit_store
from .auth import ApiKeyASGI
from .cinema_runtime import CinemaIncidentRequest, CinemaIncidentResponse, run_cinema_incident
from .config import load_settings
from .hybrid_solver import HybridSolveRequest, HybridSolveResponse, solve_and_verify
from .models import VerificationRequest, VerificationResponse
from .service import VerificationService
from .verifier import verify_candidate

settings = load_settings()
audit_store = create_audit_store(
    settings.audit_backend,
    settings.audit_db_path,
    settings.firestore_collection,
    settings.google_cloud_project,
    settings.supabase_url,
    settings.supabase_service_role_key,
)
verification_service = VerificationService(audit_store, settings.proof_signing_secret)

mcp = FastMCP(
    "DSG QUBO Ising Z3 Verification",
    instructions=(
        "Search policy configurations with deterministic QUBO/Ising-equivalent annealing, "
        "verify fixed candidates with server-side Z3, and return tamper-evident proof/audit evidence."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


@mcp.tool()
def solve_policy_hybrid(payload: dict[str, Any]) -> dict[str, Any]:
    """Search with deterministic annealing, verify with real server-side Z3, and persist proof."""
    request = HybridSolveRequest.model_validate(payload)
    return solve_and_verify(request, verification_service).model_dump(mode="json")


@mcp.tool()
def verify_policy_solution(payload: dict[str, Any]) -> dict[str, Any]:
    """Verify one candidate policy solution with Z3 and persist its audit proof."""
    request = VerificationRequest.model_validate(payload)
    return verification_service.verify(request).model_dump(mode="json")


@mcp.tool()
def validate_policy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a policy payload and report Z3 status without writing an audit event."""
    request = VerificationRequest.model_validate(payload)
    outcome = verify_candidate(request)
    return {
        "request_id": request.request_id,
        "z3_status": outcome.status,
        "accepted": outcome.accepted,
        "unsat_core": outcome.unsat_core,
        "constraint_results": [
            item.model_dump(mode="json") for item in outcome.constraint_results
        ],
        "solver_version": outcome.solver_version,
    }


@mcp.resource("dsg://capabilities")
def capabilities_resource() -> str:
    """Describe the verification service's supported capabilities."""
    return json.dumps(
        {
            "service": "DSG QUBO Ising Z3 Verification",
            "transport": "MCP Streamable HTTP",
            "tools": [
                "solve_policy_hybrid",
                "verify_policy_solution",
                "validate_policy_payload",
            ],
            "candidate_solver": "deterministic QUBO/Ising-equivalent simulated annealing",
            "authoritative_verifier": "server-side z3-solver",
            "audit": f"{settings.audit_backend} tamper-evident hash chain",
            "authentication": "X-API-Key or Bearer when DSG_API_KEY is configured",
        },
        sort_keys=True,
    )


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    audit_store.initialize()
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="DSG Cinema Proof Agent",
    version="0.2.0",
    description=(
        "Gemini/Google ADK cinema incident agent with Grafana MCP evidence plus "
        "deterministic QUBO/Ising candidate search and authoritative server-side Z3 verification."
    ),
    lifespan=lifespan,
)
app.mount("/mcp", ApiKeyASGI(mcp.streamable_http_app(), settings.api_key))


def require_api_key(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    expected = settings.api_key
    if expected is None:
        return
    bearer = authorization.removeprefix("Bearer ").strip() if authorization else None
    provided = x_api_key or bearer
    if provided is None or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )


@app.get("/", response_class=HTMLResponse)
def landing() -> str:
    page = Path(__file__).with_name("static").joinpath("index.html")
    if page.exists():
        return page.read_text(encoding="utf-8")
    return "<h1>DSG Cinema Proof Agent</h1>"


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "dsg-cinema-proof-agent",
        "mcp_endpoint": "/mcp",
        "hybrid_solver_endpoint": "/v1/hybrid/solve",
        "api_auth_enabled": settings.api_key is not None,
        "grafana_mcp_configured": settings.grafana_mcp_url is not None,
        "gemini_model": settings.gemini_model,
        "vertex_ai_mode": settings.use_vertex_ai,
        "audit_backend": settings.audit_backend,
    }


@app.get("/v1/capabilities", dependencies=[Depends(require_api_key)])
def capabilities() -> dict[str, Any]:
    return {
        "google_adk_source_integrated": True,
        "gemini_model": settings.gemini_model,
        "vertex_ai_mode": settings.use_vertex_ai,
        "google_cloud_project_configured": settings.google_cloud_project is not None,
        "grafana_mcp_configured": settings.grafana_mcp_url is not None,
        "deterministic_qubo_annealing": True,
        "qubo_to_ising_transform": True,
        "hybrid_solver_endpoint": "/v1/hybrid/solve",
        "server_side_z3": True,
        "tamper_evident_audit_chain": True,
        "proof_signature_enabled": settings.proof_signing_secret is not None,
        "mcp_transport": "streamable-http",
        "mcp_endpoint": "/mcp",
        "runtime_truth_boundary": (
            "Annealing output is a candidate only; a verified claim requires server-side Z3 SAT. "
            "External Gemini/Grafana calls are only claimed after successful runtime responses."
        ),
    }


@app.post(
    "/v1/hybrid/solve",
    response_model=HybridSolveResponse,
    dependencies=[Depends(require_api_key)],
)
def hybrid_solve(request: HybridSolveRequest) -> HybridSolveResponse:
    return solve_and_verify(request, verification_service)


@app.post(
    "/v1/verify",
    response_model=VerificationResponse,
    dependencies=[Depends(require_api_key)],
)
def verify(request: VerificationRequest) -> VerificationResponse:
    return verification_service.verify(request)


@app.post(
    "/v1/cinema/investigate",
    response_model=CinemaIncidentResponse,
    dependencies=[Depends(require_api_key)],
)
async def investigate(request: CinemaIncidentRequest) -> CinemaIncidentResponse:
    try:
        return await run_cinema_incident(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/v1/audit/{event_hash}", dependencies=[Depends(require_api_key)])
def audit_event(event_hash: str) -> dict[str, Any]:
    event = audit_store.get(event_hash)
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found")
    return event
