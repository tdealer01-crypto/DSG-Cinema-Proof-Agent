import os

os.environ.setdefault("DSG_SOLVER_SHARED_SECRET", "test-secret")

from fastapi.testclient import TestClient
import z3_main

client = TestClient(z3_main.app)
AUTH = {"Authorization": "Bearer test-secret"}


def qubo_payload():
    return {
        "request_id": "qubo-001",
        "preset_name": "unit-test",
        "problem_type": "qubo",
        "linear": [-4, -3, 1],
        "quadratic": [[0, 1, 5], [1, 2, 2]],
        "proveOptimality": True,
        "z3TimeoutMs": 30000,
    }


def test_ready_requires_configured_secret(monkeypatch):
    monkeypatch.setattr(z3_main, "SHARED_SECRET", None)
    assert client.get("/ready").status_code == 503
    monkeypatch.setattr(z3_main, "SHARED_SECRET", "test-secret")
    assert client.get("/ready").status_code == 200


def test_solve_requires_bearer_token(monkeypatch):
    monkeypatch.setattr(z3_main, "SHARED_SECRET", "test-secret")
    assert client.post("/solve", json=qubo_payload()).status_code == 401
    assert (
        client.post(
            "/solve",
            json=qubo_payload(),
            headers={"Authorization": "Bearer wrong"},
        ).status_code
        == 403
    )


def test_qubo_exact_global_optimum(monkeypatch):
    monkeypatch.setattr(z3_main, "SHARED_SECRET", "test-secret")
    response = client.post("/solve", json=qubo_payload(), headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["z3_status"] == "SAT"
    assert body["verification"] == "VERIFIED_GLOBAL_OPTIMUM"
    assert body["verified"] is True
    assert body["witness"] == [1, 0, 0]
    assert body["energy_exact"] == "-4"
    assert body["energy"] == -4.0


def test_non_optimal_candidate_is_rejected(monkeypatch):
    monkeypatch.setattr(z3_main, "SHARED_SECRET", "test-secret")
    payload = qubo_payload()
    payload["witness"] = [0, 0, 0]
    response = client.post("/solve", json=payload, headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verification"] == "COUNTEREXAMPLE_FOUND"
    assert body["verified"] is False


def test_deterministic_replay_proof_hash(monkeypatch):
    monkeypatch.setattr(z3_main, "SHARED_SECRET", "test-secret")
    first = client.post("/solve", json=qubo_payload(), headers=AUTH).json()
    second = client.post("/solve", json=qubo_payload(), headers=AUTH).json()
    assert first["request_hash"] == second["request_hash"]
    assert first["proof_hash"] == second["proof_hash"]
    assert first["witness"] == second["witness"]
    assert first["energy_exact"] == second["energy_exact"]


def test_qubo_rejects_out_of_range_term(monkeypatch):
    monkeypatch.setattr(z3_main, "SHARED_SECRET", "test-secret")
    payload = qubo_payload()
    payload["quadratic"] = [[0, 9, 1]]
    response = client.post("/solve", json=payload, headers=AUTH)
    assert response.status_code == 422


def test_qubo_rejects_invalid_witness(monkeypatch):
    monkeypatch.setattr(z3_main, "SHARED_SECRET", "test-secret")
    payload = qubo_payload()
    payload["witness"] = [1, 2, 0]
    response = client.post("/solve", json=payload, headers=AUTH)
    assert response.status_code == 422


def test_sat_deterministic_witness(monkeypatch):
    monkeypatch.setattr(z3_main, "SHARED_SECRET", "test-secret")
    payload = {
        "request_id": "sat-001",
        "preset_name": "unit-test",
        "problem_type": "sat",
        "clauses": [[1, 2], [-1, 2]],
    }
    response = client.post("/solve", json=payload, headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["z3_status"] == "SAT"
    assert body["verification"] == "SATISFIABLE"
    assert body["verified"] is True
    assert body["witness"] == [0, 1]


def test_empty_sat_clause_is_unsat(monkeypatch):
    monkeypatch.setattr(z3_main, "SHARED_SECRET", "test-secret")
    payload = {
        "request_id": "sat-unsat",
        "preset_name": "unit-test",
        "problem_type": "sat",
        "clauses": [[]],
    }
    response = client.post("/solve", json=payload, headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["z3_status"] == "UNSAT"
    assert body["verification"] == "UNSATISFIABLE"
    assert body["verified"] is True


def test_previous_secret_is_accepted_during_a_rotation(monkeypatch):
    monkeypatch.setattr(z3_main, "SHARED_SECRET", "new-secret")
    monkeypatch.setattr(z3_main, "PREVIOUS_SECRET", "old-secret")

    for token in ("new-secret", "old-secret"):
        response = client.post(
            "/solve",
            json=qubo_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, token


def test_previous_secret_is_refused_once_the_rotation_closes(monkeypatch):
    monkeypatch.setattr(z3_main, "SHARED_SECRET", "new-secret")
    monkeypatch.setattr(z3_main, "PREVIOUS_SECRET", None)

    assert (
        client.post(
            "/solve",
            json=qubo_payload(),
            headers={"Authorization": "Bearer old-secret"},
        ).status_code
        == 403
    )


def test_an_unrelated_token_is_still_refused_during_a_rotation(monkeypatch):
    monkeypatch.setattr(z3_main, "SHARED_SECRET", "new-secret")
    monkeypatch.setattr(z3_main, "PREVIOUS_SECRET", "old-secret")

    assert (
        client.post(
            "/solve",
            json=qubo_payload(),
            headers={"Authorization": "Bearer neither-secret"},
        ).status_code
        == 403
    )


def test_an_empty_previous_secret_never_widens_authorization(monkeypatch):
    monkeypatch.setattr(z3_main, "SHARED_SECRET", "new-secret")
    for empty in ("", "   ", None):
        monkeypatch.setattr(z3_main, "PREVIOUS_SECRET", empty)
        assert z3_main.accepted_secrets() == ["new-secret"]
        assert z3_main.token_is_accepted("") is False


def test_rotation_state_is_reported_without_revealing_secrets(monkeypatch):
    monkeypatch.setattr(z3_main, "SHARED_SECRET", "new-secret")
    monkeypatch.setattr(z3_main, "PREVIOUS_SECRET", "old-secret")
    body = client.get("/metrics").json()
    assert body["rotation_in_progress"] is True
    assert "new-secret" not in str(body)
    assert "old-secret" not in str(body)

    monkeypatch.setattr(z3_main, "PREVIOUS_SECRET", None)
    assert client.get("/metrics").json()["rotation_in_progress"] is False


def test_a_previous_secret_equal_to_the_current_one_is_not_a_rotation(monkeypatch):
    monkeypatch.setattr(z3_main, "SHARED_SECRET", "same-secret")
    monkeypatch.setattr(z3_main, "PREVIOUS_SECRET", "same-secret")
    assert z3_main.accepted_secrets() == ["same-secret"]
    assert client.get("/metrics").json()["rotation_in_progress"] is False
