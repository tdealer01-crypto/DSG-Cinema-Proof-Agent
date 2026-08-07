from __future__ import annotations

from app.models import VerificationRequest
from app.verifier import verify_candidate


def request_payload(configuration: list[int]) -> VerificationRequest:
    return VerificationRequest.model_validate(
        {
            "request_id": "test-request",
            "preset_name": "TEST",
            "configuration": configuration,
            "rules": [
                {
                    "id": 10,
                    "name": "A",
                    "cost": 100,
                    "risk_reduction": 10,
                    "business_value": 20,
                    "category": "TEST",
                },
                {
                    "id": 20,
                    "name": "B",
                    "cost": 200,
                    "risk_reduction": 20,
                    "business_value": 30,
                    "category": "TEST",
                },
            ],
            "constraints": [
                {
                    "type": "implication",
                    "if_rule": 10,
                    "then_rule": 20,
                    "description": "A requires B",
                },
                {
                    "type": "max_cost",
                    "budget": 300,
                    "description": "Budget cap",
                },
            ],
            "solver": {
                "seed": 42,
                "iterations": 5000,
                "qubo_energy": -10.0,
                "solution_hash": "client-hash",
            },
        }
    )


def test_sat_candidate() -> None:
    outcome = verify_candidate(request_payload([1, 1]))
    assert outcome.status == "SAT"
    assert outcome.accepted is True
    assert outcome.active_rule_ids == [10, 20]
    assert outcome.total_cost == 300.0


def test_unsat_candidate_returns_policy_core() -> None:
    outcome = verify_candidate(request_payload([1, 0]))
    assert outcome.status == "UNSAT"
    assert outcome.accepted is False
    assert "A requires B" in outcome.unsat_core
