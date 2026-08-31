from __future__ import annotations

from fastapi.testclient import TestClient

import cinema_main


client = TestClient(cinema_main.app)


VALID_PROOF = {
    "request_id": "cinema-test",
    "z3_status": "SAT",
    "verification": "VERIFIED_GLOBAL_OPTIMUM",
    "verified": True,
    "witness": [1, 0, 0],
    "energy_exact": "-4",
    "proof_hash": "a" * 64,
    "request_hash": "b" * 64,
}


def configure(monkeypatch):
    monkeypatch.setenv("DSG_BACKEND_BASE_URL", "https://z3.example.test")
    monkeypatch.setenv("DSG_BACKEND_API_KEY", "z" * 32)
    monkeypatch.setenv("CINEMA_API_SECRET", "c" * 32)


def test_health_is_fail_closed_without_config(monkeypatch):
    monkeypatch.delenv("DSG_BACKEND_BASE_URL", raising=False)
    monkeypatch.delenv("DSG_BACKEND_API_KEY", raising=False)
    monkeypatch.delenv("CINEMA_API_SECRET", raising=False)

    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "blocked"


def test_revenue_cutover_freeze_blocks_writes_but_not_reads(monkeypatch):
    monkeypatch.setenv("DSG_REVENUE_WRITE_FROZEN", "1")

    blocked = client.post("/solve", json={"problem_type": "qubo"})
    assert blocked.status_code == 503
    assert blocked.headers["retry-after"] == "60"
    assert blocked.json() == {
        "error": "REVENUE_WRITE_FROZEN",
        "message": "writes are temporarily paused for a revenue storage cutover",
        "retryable": True,
    }

    readable = client.get("/app")
    assert readable.status_code == 200


def test_revenue_cutover_freeze_is_off_by_default(monkeypatch):
    monkeypatch.delenv("DSG_REVENUE_WRITE_FROZEN", raising=False)
    configure(monkeypatch)
    assert client.post("/solve", json={"problem_type": "qubo"}).status_code == 401


def test_health_passes_only_when_backend_ready(monkeypatch):
    configure(monkeypatch)

    async def fake_z3_request(method, path, payload=None):
        assert method == "GET"
        assert path == "/ready"
        return 200, {"status": "ready"}

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "backend": "ready"}


def test_azure_landing_origin_can_call_public_verification_api(monkeypatch):
    configure(monkeypatch)
    response = client.options(
        "/verify/evaluate",
        headers={
            "Origin": "https://dsgoneverifiedweb.z1.web.core.windows.net",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "https://dsgoneverifiedweb.z1.web.core.windows.net"
    )


def test_any_azure_storage_static_site_origin_matches_cors_policy(monkeypatch):
    configure(monkeypatch)
    origin = "https://dsgoneverifiedweb.z99.web.core.windows.net"
    response = client.options(
        "/verify/evaluate",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_render_landing_origin_can_call_public_verification_api(monkeypatch):
    configure(monkeypatch)
    origin = "https://dsgoneverifiedweb.z1.web.core.windows.net"
    response = client.options(
        "/verify/evaluate",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_stripe_ui_null_origin_can_preflight_signed_endpoint(monkeypatch):
    configure(monkeypatch)
    response = client.options(
        "/stripe/evaluate",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,stripe-signature",
        },
    )
    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "*"
    assert "Stripe-Signature" in response.headers["access-control-allow-headers"]


def test_solve_rejects_missing_token(monkeypatch):
    configure(monkeypatch)
    response = client.post("/solve", json={"problem_type": "qubo"})
    assert response.status_code == 401


def test_solve_rejects_wrong_token(monkeypatch):
    configure(monkeypatch)
    response = client.post(
        "/solve",
        headers={"Authorization": "Bearer wrong-token"},
        json={"problem_type": "qubo"},
    )
    assert response.status_code == 403


def test_solve_returns_verified_exact_proof(monkeypatch):
    configure(monkeypatch)

    async def fake_z3_request(method, path, payload=None):
        assert method == "POST"
        assert path == "/solve"
        assert payload == {"problem_type": "qubo"}
        return 200, VALID_PROOF

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    response = client.post(
        "/solve",
        headers={"Authorization": f"Bearer {'c' * 32}"},
        json={"problem_type": "qubo"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cinema_status"] == "VERIFIED"
    assert body["verification"] == "VERIFIED_GLOBAL_OPTIMUM"
    assert body["verified"] is True
    assert body["proof_hash"] == "a" * 64
    assert body["z3_proof"]["energy_exact"] == "-4"


def test_solve_blocks_non_verified_backend_result(monkeypatch):
    configure(monkeypatch)

    async def fake_z3_request(method, path, payload=None):
        return 200, {
            **VALID_PROOF,
            "verified": False,
            "verification": "COUNTEREXAMPLE_FOUND",
        }

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    response = client.post(
        "/solve",
        headers={"Authorization": f"Bearer {'c' * 32}"},
        json={"problem_type": "qubo"},
    )
    assert response.status_code == 502


def test_stripe_low_risk_is_allow_with_exact_z3_proof(monkeypatch):
    configure(monkeypatch)

    async def fake_z3_request(method, path, payload=None):
        assert method == "POST"
        assert path == "/solve"
        assert payload["problem_type"] == "qubo"
        assert payload["linear"] == [-100, -70, -40]
        assert payload["quadratic"] == [[0, 1, 200], [0, 2, 200], [1, 2, 200]]
        return 200, {
            **VALID_PROOF,
            "witness": [1, 0, 0],
            "energy_exact": "-100",
        }

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    response = client.post(
        "/stripe/evaluate",
        json={
            "stripe_account_id": "acct_test123",
            "object_type": "charge",
            "object_id": "ch_test123",
            "amount_cents": 5000,
            "currency": "usd",
            "stripe_status": "succeeded",
            "risk_level": "low",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "ALLOW"
    assert body["verified"] is True
    assert body["verification"] == "VERIFIED_GLOBAL_OPTIMUM"
    assert body["risk_score"] == 0
    assert body["policy_version"] == "cinema-stripe-z3-1.0.0"
    assert len(body["context_hash"]) == 64


def test_stripe_missing_amount_is_fail_closed_review(monkeypatch):
    configure(monkeypatch)

    async def fake_z3_request(method, path, payload=None):
        assert payload["linear"] == [-60, -100, -60]
        return 200, {
            **VALID_PROOF,
            "witness": [0, 1, 0],
            "energy_exact": "-100",
        }

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    response = client.post(
        "/stripe/evaluate",
        json={
            "stripe_account_id": "acct_test123",
            "object_type": "payment_intent",
            "object_id": "pi_test123",
            "currency": "usd",
            "stripe_status": "processing",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "REVIEW"
    assert body["risk_score"] == 35
    assert "amount unavailable" in body["reason"]


def test_stripe_critical_risk_is_block(monkeypatch):
    configure(monkeypatch)

    async def fake_z3_request(method, path, payload=None):
        assert payload["linear"] == [-40, -70, -100]
        return 200, {
            **VALID_PROOF,
            "witness": [0, 0, 1],
            "energy_exact": "-100",
        }

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    response = client.post(
        "/stripe/evaluate",
        json={
            "stripe_account_id": "acct_test123",
            "object_type": "payout",
            "object_id": "po_test123",
            "amount_cents": 6_000_000,
            "currency": "thb",
            "stripe_status": "pending",
            "risk_level": "critical",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "BLOCK"
    assert body["risk_score"] == 100
    assert body["risk_level"] == "critical"


def test_stripe_endpoint_rejects_object_type_prefix_mismatch(monkeypatch):
    configure(monkeypatch)
    response = client.post(
        "/stripe/evaluate",
        json={
            "stripe_account_id": "acct_test123",
            "object_type": "charge",
            "object_id": "pi_wrong",
            "amount_cents": 1000,
        },
    )
    assert response.status_code == 400


def test_stripe_endpoint_blocks_unverified_z3_result(monkeypatch):
    configure(monkeypatch)

    async def fake_z3_request(method, path, payload=None):
        return 200, {
            **VALID_PROOF,
            "verified": False,
            "verification": "COUNTEREXAMPLE_FOUND",
        }

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    response = client.post(
        "/stripe/evaluate",
        json={
            "stripe_account_id": "acct_test123",
            "object_type": "charge",
            "object_id": "ch_test123",
            "amount_cents": 1000,
        },
    )
    assert response.status_code == 502


def test_stripe_context_hash_is_deterministic(monkeypatch):
    configure(monkeypatch)
    seen_request_ids: list[str] = []

    async def fake_z3_request(method, path, payload=None):
        seen_request_ids.append(payload["request_id"])
        return 200, {
            **VALID_PROOF,
            "witness": [1, 0, 0],
            "energy_exact": "-100",
        }

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    payload = {
        "stripe_account_id": "acct_test123",
        "object_type": "charge",
        "object_id": "ch_test123",
        "amount_cents": 5000,
        "currency": "USD",
        "stripe_status": "SUCCEEDED",
        "risk_level": "low",
    }
    first = client.post("/stripe/evaluate", json=payload)
    second = client.post("/stripe/evaluate", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["context_hash"] == second.json()["context_hash"]
    assert seen_request_ids[0] == seen_request_ids[1]


def _verification_payload(**overrides):
    payload = {
        "execution_id": "exec-marketplace-001",
        "trace_id": "trace-marketplace-001",
        "channel": "github",
        "agent_identity": "github-actions",
        "approved_plan_hash": "1" * 64,
        "proposed_action_hash": "2" * 64,
        "authorized": True,
        "plan_aligned": True,
        "constraints_pass": True,
        "execution_succeeded": True,
        "replay_match": True,
        "evidence_complete": True,
        "cost_microunits": 125000,
    }
    payload.update(overrides)
    return payload


def test_marketplace_verified_execution_allow(monkeypatch):
    configure(monkeypatch)

    async def fake_z3_request(method, path, payload=None):
        assert method == "POST"
        assert path == "/solve"
        assert payload["preset_name"] == "verified-execution-v1"
        assert payload["linear"] == [-100, -70, -40]
        assert payload["quadratic"] == [[0, 1, 200], [0, 2, 200], [1, 2, 200]]
        return 200, {
            **VALID_PROOF,
            "witness": [1, 0, 0],
            "energy_exact": "-100",
        }

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    response = client.post("/verify/evaluate", json=_verification_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "ALLOW"
    assert body["verified"] is True
    assert body["verification"] == "VERIFIED_GLOBAL_OPTIMUM"
    assert body["receipt_version"] == "dsg-proof-receipt-1.0.0"
    assert body["policy_version"] == "dsg-verified-execution-1.0.0"
    assert body["authorized_action_completion"] is True
    assert body["out_of_plan_rejection"] is False
    assert body["replay_match"] is True
    assert body["evidence_completeness"] == 1.0
    assert body["cost_microunits"] == 125000
    assert len(body["context_hash"]) == 64


def test_marketplace_out_of_plan_is_block(monkeypatch):
    configure(monkeypatch)

    async def fake_z3_request(method, path, payload=None):
        assert payload["linear"] == [-40, -70, -100]
        return 200, {
            **VALID_PROOF,
            "witness": [0, 0, 1],
            "energy_exact": "-100",
        }

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    response = client.post(
        "/verify/evaluate",
        json=_verification_payload(plan_aligned=False),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "BLOCK"
    assert body["out_of_plan_rejection"] is True
    assert "outside the approved plan" in body["reason"]


def test_marketplace_incomplete_evidence_is_review(monkeypatch):
    configure(monkeypatch)

    async def fake_z3_request(method, path, payload=None):
        assert payload["linear"] == [-60, -100, -60]
        return 200, {
            **VALID_PROOF,
            "witness": [0, 1, 0],
            "energy_exact": "-100",
        }

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    response = client.post(
        "/verify/evaluate",
        json=_verification_payload(evidence_complete=False),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "REVIEW"
    assert body["evidence_completeness"] == 0.0
    assert "evidence is incomplete" in body["reason"]


def test_marketplace_context_hash_is_deterministic(monkeypatch):
    configure(monkeypatch)
    request_ids: list[str] = []

    async def fake_z3_request(method, path, payload=None):
        request_ids.append(payload["request_id"])
        return 200, {
            **VALID_PROOF,
            "witness": [1, 0, 0],
            "energy_exact": "-100",
        }

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    payload = _verification_payload()
    first = client.post("/verify/evaluate", json=payload)
    second = client.post("/verify/evaluate", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["context_hash"] == second.json()["context_hash"]
    assert request_ids[0] == request_ids[1]


def test_marketplace_rejects_non_sha256_plan_hash(monkeypatch):
    configure(monkeypatch)
    response = client.post(
        "/verify/evaluate",
        json=_verification_payload(approved_plan_hash="not-a-sha256"),
    )
    assert response.status_code == 422


def test_openai_plugin_channel_is_supported(monkeypatch):
    configure(monkeypatch)

    async def fake_z3_request(method, path, payload=None):
        return 200, {
            **VALID_PROOF,
            "witness": [1, 0, 0],
            "energy_exact": "-100",
        }

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    response = client.post(
        "/verify/evaluate",
        json=_verification_payload(channel="openai_plugin"),
    )
    assert response.status_code == 200
    assert response.json()["channel"] == "openai_plugin"
