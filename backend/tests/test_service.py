from __future__ import annotations

from app.audit import AuditStore
from app.models import VerificationRequest
from app.service import VerificationService


def test_service_creates_proof_and_signature(tmp_path) -> None:
    store = AuditStore(str(tmp_path / "audit.sqlite3"))
    store.initialize()
    service = VerificationService(store, signing_secret="test-secret")
    request = VerificationRequest.model_validate(
        {
            "preset_name": "TEST",
            "configuration": [1],
            "rules": [
                {
                    "id": 7,
                    "name": "ONLY",
                    "cost": 10,
                    "risk_reduction": 1,
                    "business_value": 1,
                    "category": "TEST",
                }
            ],
            "constraints": [{"type": "min_active", "minimum": 1}],
            "solver": {
                "seed": 42,
                "iterations": 10,
                "qubo_energy": -2,
                "solution_hash": "client-hash",
            },
        }
    )

    result = service.verify(request)

    assert result.accepted is True
    assert len(result.input_hash) == 64
    assert len(result.proof_hash) == 64
    assert result.proof_signature is not None
    assert len(result.proof_signature) == 64
    assert result.audit.sequence == 1
