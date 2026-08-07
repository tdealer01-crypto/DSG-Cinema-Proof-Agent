from __future__ import annotations

from functools import lru_cache
from typing import Any

from .audit import create_audit_store
from .config import load_settings
from .models import VerificationRequest
from .service import VerificationService


CINEMA_RULES = [
    {
        "id": 0,
        "name": "inspect_playback_metrics",
        "cost": 0,
        "risk_reduction": 25,
        "business_value": 20,
        "category": "OBSERVE",
        "description": "Inspect production playback or render metrics before changing runtime state.",
    },
    {
        "id": 1,
        "name": "inspect_error_logs",
        "cost": 0,
        "risk_reduction": 25,
        "business_value": 20,
        "category": "OBSERVE",
        "description": "Inspect production logs before changing runtime state.",
    },
    {
        "id": 2,
        "name": "notify_operator",
        "cost": 1,
        "risk_reduction": 15,
        "business_value": 15,
        "category": "COORDINATE",
        "description": "Notify the studio operator or incident commander.",
    },
    {
        "id": 3,
        "name": "pause_noncritical_jobs",
        "cost": 2,
        "risk_reduction": 30,
        "business_value": 25,
        "category": "STABILIZE",
        "description": "Pause non-critical render or batch jobs to reduce production pressure.",
    },
    {
        "id": 4,
        "name": "restart_streaming_service",
        "cost": 5,
        "risk_reduction": 40,
        "business_value": 30,
        "category": "MUTATE",
        "description": "Restart a production streaming service. This is high risk and approval-gated.",
    },
    {
        "id": 5,
        "name": "human_approval",
        "cost": 0,
        "risk_reduction": 50,
        "business_value": 10,
        "category": "APPROVAL",
        "description": "Explicit human approval for a high-risk production mutation.",
    },
]

CINEMA_CONSTRAINTS = [
    {
        "type": "at_least_one_of",
        "rules": [0, 1],
        "description": "A plan must include production evidence from metrics or logs.",
    },
    {
        "type": "implication",
        "if_rule": 4,
        "then_rule": 0,
        "description": "A service restart requires metrics evidence.",
    },
    {
        "type": "implication",
        "if_rule": 4,
        "then_rule": 1,
        "description": "A service restart requires log evidence.",
    },
    {
        "type": "implication",
        "if_rule": 4,
        "then_rule": 5,
        "description": "A service restart requires explicit human approval.",
    },
    {
        "type": "implication",
        "if_rule": 3,
        "then_rule": 2,
        "description": "Pausing non-critical jobs requires notifying an operator.",
    },
]


@lru_cache(maxsize=1)
def _service() -> VerificationService:
    settings = load_settings()
    store = create_audit_store(
        settings.audit_backend,
        settings.audit_db_path,
        settings.firestore_collection,
        settings.google_cloud_project,
        settings.supabase_url,
        settings.supabase_service_role_key,
    )
    store.initialize()
    return VerificationService(store, settings.proof_signing_secret)


def verify_recovery_plan(
    inspect_playback_metrics: bool,
    inspect_error_logs: bool,
    notify_operator: bool,
    pause_noncritical_jobs: bool,
    restart_streaming_service: bool,
    human_approval: bool,
) -> dict[str, Any]:
    """Run the proposed cinema incident-recovery plan through the deterministic Z3 gate.

    Call this before recommending or executing any runtime-changing production action.
    A restart is rejected unless metrics, logs, and explicit human approval are present.
    The returned proof and audit hashes are server-generated evidence; never invent them.
    """
    configuration = [
        int(inspect_playback_metrics),
        int(inspect_error_logs),
        int(notify_operator),
        int(pause_noncritical_jobs),
        int(restart_streaming_service),
        int(human_approval),
    ]
    request = VerificationRequest.model_validate(
        {
            "preset_name": "CINEMA_PRODUCTION_INCIDENT",
            "configuration": configuration,
            "rules": CINEMA_RULES,
            "constraints": CINEMA_CONSTRAINTS,
            "solver": {
                "seed": 0,
                "iterations": 0,
                "qubo_energy": 0.0,
                "solution_hash": "agent-proposed-plan",
            },
            "client_name": "google-adk-cinema-agent",
            "client_version": "0.1.0",
        }
    )
    return _service().verify(request).model_dump(mode="json")
