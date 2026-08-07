from __future__ import annotations

from app.cinema_gate import CINEMA_CONSTRAINTS, CINEMA_RULES
from app.models import VerificationRequest
from app.verifier import verify_candidate


def _request(configuration: list[int]) -> VerificationRequest:
    return VerificationRequest.model_validate(
        {
            "preset_name": "CINEMA_PRODUCTION_INCIDENT",
            "configuration": configuration,
            "rules": CINEMA_RULES,
            "constraints": CINEMA_CONSTRAINTS,
            "solver": {
                "seed": 0,
                "iterations": 0,
                "qubo_energy": 0,
                "solution_hash": "test-plan",
            },
        }
    )


def test_read_only_evidence_plan_is_sat() -> None:
    result = verify_candidate(_request([1, 1, 1, 0, 0, 0]))
    assert result.accepted is True
    assert result.status == "SAT"


def test_restart_without_approval_is_blocked() -> None:
    result = verify_candidate(_request([1, 1, 1, 0, 1, 0]))
    assert result.accepted is False
    assert result.status == "UNSAT"
    assert "A service restart requires explicit human approval." in result.unsat_core


def test_restart_without_evidence_is_blocked() -> None:
    result = verify_candidate(_request([0, 0, 1, 0, 1, 1]))
    assert result.accepted is False
    assert result.status == "UNSAT"


def test_pause_requires_operator_notification() -> None:
    result = verify_candidate(_request([1, 0, 0, 1, 0, 0]))
    assert result.accepted is False
    assert "Pausing non-critical jobs requires notifying an operator." in result.unsat_core
