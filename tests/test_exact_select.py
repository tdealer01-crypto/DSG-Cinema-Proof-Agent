from __future__ import annotations

import hashlib
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

import cinema_main
from z3_exact_topk import install_exact_topk


def sha256_json(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def exact_args(*, use_z3: bool = False) -> dict:
    return {
        "candidates": [
            {"id": "a", "composite": "0.50003"},
            {"id": "b", "composite": "0.50004"},
            {"id": "c", "composite": "0.50004"},
        ],
        "k": 2,
        "minComposite": "0",
        "useZ3": use_z3,
    }


def mcp_call(client: TestClient, arguments: dict) -> dict:
    response = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 91,
            "method": "tools/call",
            "params": {"name": "dsg_exact_select", "arguments": arguments},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def proof_response(payload: dict, *, corrupt_proof_hash: bool = False) -> dict:
    selected = [
        {"id": "b", "composite": "0.50004"},
        {"id": "c", "composite": "0.50004"},
    ]
    request_payload = {**payload, "seed": 42}
    request_hash = sha256_json(request_payload)
    proof_payload = {
        "request_hash": request_hash,
        "z3_status": "SAT",
        "verification": "VERIFIED_EXACT_TOP_K",
        "verified": True,
        "selected": selected,
        "total_score_exact": "1.00008",
        "score_optimality": "UNSAT_BETTER_SCORE",
        "tie_break_optimality": "UNSAT_BETTER_TIE",
    }
    proof_hash = sha256_json(proof_payload)
    if corrupt_proof_hash:
        proof_hash = "0" * 64
    return {
        "request_id": payload["request_id"],
        **proof_payload,
        "proof_hash": proof_hash,
        "eligible_count": 3,
        "selected_count": 2,
        "compute_ms": 1,
        "timestamp": "2026-08-28T00:00:00Z",
        "audit": {
            "solver": "z3-native Real Optimize + independent Solver",
            "seed": 42,
            "score_optimality": "UNSAT_BETTER_SCORE",
            "tie_break_optimality": "UNSAT_BETTER_TIE",
        },
    }


def test_native_z3_endpoint_proves_exact_top_k():
    verifier_app = FastAPI()
    install_exact_topk(verifier_app, lambda _authorization: None)
    client = TestClient(verifier_app)
    response = client.post(
        "/exact-select",
        json={
            "request_id": "native-proof",
            "candidates": exact_args()["candidates"],
            "k": 2,
            "minComposite": "0",
            "z3TimeoutMs": 5000,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verified"] is True
    assert body["verification"] == "VERIFIED_EXACT_TOP_K"
    assert body["z3_status"] == "SAT"
    assert [candidate["id"] for candidate in body["selected"]] == ["b", "c"]
    assert body["total_score_exact"] == "1.00008"
    assert body["audit"]["score_optimality"] == "UNSAT_BETTER_SCORE"
    assert body["audit"]["tie_break_optimality"] == "UNSAT_BETTER_TIE"
    assert len(body["request_hash"]) == 64
    assert len(body["proof_hash"]) == 64


def test_native_z3_endpoint_handles_exact_values_beyond_ieee754():
    verifier_app = FastAPI()
    install_exact_topk(verifier_app, lambda _authorization: None)
    client = TestClient(verifier_app)
    response = client.post(
        "/exact-select",
        json={
            "request_id": "ieee-proof",
            "candidates": [
                {"id": "lower", "composite": "9007199254740992"},
                {"id": "higher", "composite": "9007199254740993"},
            ],
            "k": 1,
            "minComposite": "-0",
            "z3TimeoutMs": 5000,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verified"] is True
    assert body["selected"] == [{"id": "higher", "composite": "9007199254740993"}]


def test_mcp_lists_exact_tool_with_read_only_annotations():
    client = TestClient(cinema_main.app)
    response = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 90, "method": "tools/list", "params": {}},
    )
    assert response.status_code == 200, response.text
    tools = {tool["name"]: tool for tool in response.json()["result"]["tools"]}
    tool = tools["dsg_exact_select"]
    assert tool["annotations"] == {
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
    }
    assert tool["inputSchema"]["properties"]["candidates"]["maxItems"] == 24
    assert tool["inputSchema"]["properties"]["k"]["maximum"] == 12


def test_mcp_exact_sort_is_deterministic_without_z3():
    client = TestClient(cinema_main.app)
    result = mcp_call(client, exact_args(use_z3=False))
    body = result["structuredContent"]
    assert result["isError"] is False
    assert body["status"] == "PASSED"
    assert body["mode"] == "exact-sort"
    assert body["solver"] == "none"
    assert [candidate["id"] for candidate in body["selected"]] == ["b", "c"]
    assert len(body["evidenceHash"]) == 64


def test_mcp_z3_path_recomputes_backend_proof_hashes(monkeypatch):
    async def fake_z3_request(method, path, payload=None):
        assert method == "POST"
        assert path == "/exact-select"
        return 200, proof_response(payload)

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    client = TestClient(cinema_main.app)
    result = mcp_call(client, exact_args(use_z3=True))
    body = result["structuredContent"]
    assert result["isError"] is False
    assert body["status"] == "PASSED"
    assert body["mode"] == "verified-exact"
    assert body["solverResult"] == "sat"
    assert [candidate["id"] for candidate in body["selected"]] == ["b", "c"]
    assert len(body["z3ProofHash"]) == 64


def test_mcp_z3_path_blocks_tampered_proof_hash(monkeypatch):
    async def fake_z3_request(_method, _path, payload=None):
        return 200, proof_response(payload, corrupt_proof_hash=True)

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    client = TestClient(cinema_main.app)
    result = mcp_call(client, exact_args(use_z3=True))
    body = result["structuredContent"]
    assert result["isError"] is True
    assert body["status"] == "BLOCKED"
    assert body["reason"] == "Z3_PROOF_HASH_MISMATCH"


def test_mcp_z3_path_blocks_backend_unavailable(monkeypatch):
    async def unavailable(_method, _path, _payload=None):
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(cinema_main, "z3_request", unavailable)
    client = TestClient(cinema_main.app)
    result = mcp_call(client, exact_args(use_z3=True))
    body = result["structuredContent"]
    assert result["isError"] is True
    assert body["status"] == "BLOCKED"
    assert body["reason"] == "Z3_BACKEND_UNAVAILABLE"


def test_mcp_rejects_duplicate_ids_before_execution():
    client = TestClient(cinema_main.app)
    args = exact_args(use_z3=False)
    args["candidates"][1]["id"] = "a"
    result = mcp_call(client, args)
    assert result["isError"] is True
    assert result["structuredContent"]["error"] == "INVALID_ARGUMENTS"
