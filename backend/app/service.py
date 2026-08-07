from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Protocol, Any

from .audit import canonical_json
from .models import AuditChainProof, VerificationRequest, VerificationResponse
from .verifier import verify_candidate


class AuditStoreProtocol(Protocol):
    def append(self, payload: dict[str, Any], proof_hash: str) -> AuditChainProof: ...


class VerificationService:
    def __init__(self, audit_store: AuditStoreProtocol, signing_secret: str | None = None):
        self.audit_store = audit_store
        self.signing_secret = signing_secret

    def verify(self, request: VerificationRequest) -> VerificationResponse:
        outcome = verify_candidate(request)
        request_payload = request.model_dump(mode="json")
        input_hash = hashlib.sha256(canonical_json(request_payload).encode("utf-8")).hexdigest()
        verified_at = datetime.now(timezone.utc)

        proof_payload = {
            "request_id": request.request_id,
            "input_hash": input_hash,
            "client_solution_hash": request.solver.solution_hash,
            "z3_status": outcome.status,
            "accepted": outcome.accepted,
            "active_rule_ids": outcome.active_rule_ids,
            "total_cost": outcome.total_cost,
            "active_count": outcome.active_count,
            "constraint_results": [
                item.model_dump(mode="json") for item in outcome.constraint_results
            ],
            "unsat_core": outcome.unsat_core,
            "solver_version": outcome.solver_version,
            "verified_at": verified_at.isoformat(),
        }
        proof_hash = hashlib.sha256(canonical_json(proof_payload).encode("utf-8")).hexdigest()
        signature = (
            hmac.new(
                self.signing_secret.encode("utf-8"),
                proof_hash.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if self.signing_secret
            else None
        )
        audit = self.audit_store.append(
            payload={"request": request_payload, "proof": proof_payload, "signature": signature},
            proof_hash=proof_hash,
        )

        return VerificationResponse(
            request_id=request.request_id,
            accepted=outcome.accepted,
            z3_status=outcome.status,
            all_constraints_satisfied=outcome.accepted,
            constraint_results=outcome.constraint_results,
            unsat_core=outcome.unsat_core,
            active_rule_ids=outcome.active_rule_ids,
            total_cost=outcome.total_cost,
            active_count=outcome.active_count,
            input_hash=input_hash,
            proof_hash=proof_hash,
            proof_signature=signature,
            client_solution_hash=request.solver.solution_hash,
            solver_version=outcome.solver_version,
            verified_at=verified_at,
            audit=audit,
        )
