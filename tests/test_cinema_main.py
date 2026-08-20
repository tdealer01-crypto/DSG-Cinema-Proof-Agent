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
