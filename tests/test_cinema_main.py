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
