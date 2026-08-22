"""Contract tests for the DSG ONE v1 verification API.

The property under test throughout: a caller cannot reach a verified receipt by
asserting one. Every verdict in a receipt has to be reproducible from the raw
plan, actions and evidence DSG stored, and no receipt exists without a proof.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

import cinema_main
from api_v1 import service
from api_v1.models import ExecutionVerifyRequest
from api_v1.store import RecordStore, reset_store

client = TestClient(cinema_main.app)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DSG_BACKEND_BASE_URL", "https://z3.example.test")
    monkeypatch.setenv("DSG_BACKEND_API_KEY", "z" * 32)
    monkeypatch.setenv("CINEMA_API_SECRET", "c" * 32)
    monkeypatch.delenv("DSG_REVENUE_ENFORCE", raising=False)
    reset_store(RecordStore(str(tmp_path / "v1-store.json")))
    yield
    reset_store(RecordStore(None))


def install_solver(monkeypatch, *, ready: bool = True, fail: bool = False):
    """A Z3 stand-in that proves exactly the decision the caller encoded."""
    calls: list[dict] = []

    async def fake_z3_request(method, path, payload=None):
        calls.append({"method": method, "path": path, "payload": payload})
        if path == "/ready":
            return (200, {"status": "ready"}) if ready else (503, {"status": "blocked"})
        if fail:
            return 503, {"error": "backend down"}
        linear = payload["linear"]
        index = min(range(3), key=lambda position: linear[position])
        witness = [1 if position == index else 0 for position in range(3)]
        return 200, {
            "request_id": payload["request_id"],
            "verified": True,
            "verification": "VERIFIED_GLOBAL_OPTIMUM",
            "witness": witness,
            "energy_exact": "-140",
            "proof_hash": sha256(json.dumps(payload, sort_keys=True)),
            "request_hash": sha256(payload["request_id"]),
        }

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    return calls


PLAN = {
    "title": "Deploy release v1.8.2 to production",
    "agent_identity": "github-copilot",
    "channel": "github",
    "steps": [
        {"step_id": "build", "action": "build", "target": "acme/web-app", "parameters": {"branch": "main"}},
        {"step_id": "test", "action": "test", "target": "acme/web-app"},
        {
            "step_id": "deploy",
            "action": "deploy",
            "target": "vercel/production",
            "parameters": {"environment": "production"},
        },
    ],
    "constraints": [
        {"constraint_id": "cost_cap", "field": "cost_microunits", "op": "lte", "value": 500000},
        {
            "constraint_id": "environment",
            "field": "environment",
            "op": "in",
            "value": ["production", "staging"],
        },
    ],
}


def approved_plan() -> dict:
    created = client.post("/api/v1/plans", json=PLAN)
    assert created.status_code == 201, created.text
    plan = created.json()
    approved = client.post(
        f"/api/v1/plans/{plan['plan_id']}/approve",
        json={"approver": "release-manager@acme.test", "plan_hash": plan["plan_hash"]},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def evidence_for(step_id: str, body: str) -> dict:
    return {
        "artifact_id": f"{step_id}-log",
        "source": "vercel-api",
        "step_id": step_id,
        "media_type": "application/json",
        "content": body,
    }


def clean_run(monkeypatch) -> dict:
    install_solver(monkeypatch)
    plan = approved_plan()
    bodies = {step: json.dumps({"step": step, "status": "ok"}) for step in ("build", "test", "deploy")}
    execution = client.post(
        "/api/v1/executions",
        json={
            "plan_id": plan["plan_id"],
            "agent_identity": "github-copilot",
            "environment": "production",
            "channel": "github",
            "cost_microunits": 230000,
            "actions": [
                {
                    "step_id": "build",
                    "action": "build",
                    "target": "acme/web-app",
                    "parameters": {"branch": "main"},
                    "output_sha256": sha256(bodies["build"]),
                },
                {
                    "step_id": "test",
                    "action": "test",
                    "target": "acme/web-app",
                    "output_sha256": sha256(bodies["test"]),
                },
                {
                    "step_id": "deploy",
                    "action": "deploy",
                    "target": "vercel/production",
                    "parameters": {"environment": "production"},
                    "output_sha256": sha256(bodies["deploy"]),
                },
            ],
        },
    )
    assert execution.status_code == 201, execution.text
    execution_id = execution.json()["execution_id"]

    submitted = client.post(
        f"/api/v1/executions/{execution_id}/evidence",
        json={"artifacts": [evidence_for(step, body) for step, body in bodies.items()]},
    )
    assert submitted.status_code == 201, submitted.text
    return {"plan": plan, "execution_id": execution_id, "bodies": bodies}


# --------------------------------------------------------------------- status
def test_status_reports_degraded_when_the_verifier_is_not_ready(monkeypatch):
    install_solver(monkeypatch, ready=False)
    body = client.get("/api/v1/status").json()
    assert body["status"] == "DEGRADED"
    assert body["verification_backend"]["ready"] is False


def test_status_advertises_the_flow_and_the_mcp_endpoint(monkeypatch):
    install_solver(monkeypatch)
    body = client.get("/api/v1/status").json()
    assert body["status"] == "READY"
    assert [item["step"] for item in body["flow"]] == [
        "approve_plan",
        "plan_alignment",
        "constraints",
        "execute",
        "evidence",
        "replay_verify",
        "proof",
    ]
    assert body["mcp"]["endpoint"] == "/api/v1/mcp"
    assert "dsg_verify_execution" in body["mcp"]["tools"]
    assert body["independent_verification"]["verdicts_accepted_from_agent"] is False
    assert body["storage"]["durable"] is True


# ------------------------------------------------- refusing asserted verdicts
@pytest.mark.parametrize(
    "path,payload",
    [
        (
            "/api/v1/verify/plan-alignment",
            {
                "plan": PLAN,
                "actions": [{"action": "build", "target": "acme/web-app"}],
                "plan_aligned": True,
            },
        ),
        (
            "/api/v1/verify/constraints",
            {"constraints": [], "facts": {}, "constraints_pass": True},
        ),
        (
            "/api/v1/executions",
            {
                "plan_id": "plan_x",
                "agent_identity": "a",
                "actions": [{"action": "build", "target": "t", "replay_match": True}],
            },
        ),
    ],
)
def test_asserted_verdicts_are_refused(path, payload):
    response = client.post(path, json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "AGENT_ASSERTED_VERDICT_REJECTED"
    assert body["details"]["asserted_fields"]
    assert "raw material" in body["remediation"]["next_step"]


def test_agent_data_named_like_a_verdict_is_still_accepted(monkeypatch):
    install_solver(monkeypatch)
    response = client.post(
        "/api/v1/verify/plan-alignment",
        json={
            "plan": PLAN,
            "actions": [
                {
                    "step_id": "build",
                    "action": "build",
                    "target": "acme/web-app",
                    "parameters": {"branch": "main", "verified": "signature-checked"},
                }
            ],
        },
    )
    assert response.status_code == 200, response.text


# ------------------------------------------------------------ plan lifecycle
def test_approval_must_echo_the_hash_dsg_computed():
    created = client.post("/api/v1/plans", json=PLAN).json()
    response = client.post(
        f"/api/v1/plans/{created['plan_id']}/approve",
        json={"approver": "someone", "plan_hash": "f" * 64},
    )
    assert response.status_code == 409
    assert response.json()["error"] == "PLAN_HASH_MISMATCH"


def test_plan_hash_is_recomputed_on_read():
    created = client.post("/api/v1/plans", json=PLAN).json()
    read = client.get(f"/api/v1/plans/{created['plan_id']}").json()
    assert read["plan_hash_verified"] is True
    assert read["plan_hash"] == created["plan_hash"]


def test_execution_requires_an_approved_plan():
    created = client.post("/api/v1/plans", json=PLAN).json()
    response = client.post(
        "/api/v1/executions",
        json={
            "plan_id": created["plan_id"],
            "agent_identity": "github-copilot",
            "actions": [{"action": "build", "target": "acme/web-app"}],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"] == "PLAN_NOT_APPROVED"


def test_execution_by_an_unapproved_agent_is_refused():
    plan = approved_plan()
    response = client.post(
        "/api/v1/executions",
        json={
            "plan_id": plan["plan_id"],
            "agent_identity": "some-other-agent",
            "actions": [{"action": "build", "target": "acme/web-app"}],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"] == "AGENT_IDENTITY_MISMATCH"


# ---------------------------------------------------------------- alignment
def test_alignment_is_computed_action_by_action(monkeypatch):
    plan = approved_plan()
    response = client.post(
        "/api/v1/verify/plan-alignment",
        json={
            "plan_id": plan["plan_id"],
            "actions": [
                {"step_id": "build", "action": "build", "target": "acme/web-app", "parameters": {"branch": "main"}},
                {"step_id": "deploy", "action": "deploy", "target": "vercel/staging"},
            ],
        },
    )
    body = response.json()
    assert body["plan_aligned"] is False
    codes = {item["code"] for item in body["findings"]}
    assert "OUT_OF_PLAN_ACTION" in codes
    assert body["computed_by"] == "dsg"


# --------------------------------------------------------------- constraints
def test_constraints_violation_is_proved_as_block(monkeypatch):
    calls = install_solver(monkeypatch)
    plan = approved_plan()
    response = client.post(
        "/api/v1/verify/constraints",
        json={"plan_id": plan["plan_id"], "facts": {"cost_microunits": 900000, "environment": "production"}},
    )
    body = response.json()
    assert body["constraints_pass"] is False
    assert body["decision"] == "BLOCK"
    assert body["witness"] == [0, 0, 1]
    assert len(body["proof_hash"]) == 64
    assert calls[-1]["payload"]["proveOptimality"] is True


def test_constraints_fail_closed_when_the_verifier_is_down(monkeypatch):
    install_solver(monkeypatch, fail=True)
    plan = approved_plan()
    response = client.post(
        "/api/v1/verify/constraints",
        json={"plan_id": plan["plan_id"], "facts": {"cost_microunits": 1, "environment": "production"}},
    )
    assert response.status_code == 502
    body = response.json()
    assert body["error"] == "BACKEND_UNAVAILABLE"
    assert "verified" not in body


# ------------------------------------------------------------------ evidence
def test_evidence_that_misdescribes_its_own_hash_is_rejected(monkeypatch):
    run = clean_run(monkeypatch)
    response = client.post(
        f"/api/v1/executions/{run['execution_id']}/evidence",
        json={
            "artifacts": [
                {
                    "artifact_id": "forged",
                    "source": "agent",
                    "step_id": "deploy",
                    "content": "deployment failed",
                    "declared_sha256": sha256("deployment succeeded"),
                }
            ]
        },
    )
    assert response.status_code == 422
    assert response.json()["error"] == "EVIDENCE_HASH_MISMATCH"


def test_hash_only_evidence_is_never_counted_as_verified(monkeypatch):
    install_solver(monkeypatch)
    plan = approved_plan()
    execution = client.post(
        "/api/v1/executions",
        json={
            "plan_id": plan["plan_id"],
            "agent_identity": "github-copilot",
            "environment": "production",
            "actions": [
                {"step_id": "build", "action": "build", "target": "acme/web-app", "parameters": {"branch": "main"}},
                {"step_id": "test", "action": "test", "target": "acme/web-app"},
                {
                    "step_id": "deploy",
                    "action": "deploy",
                    "target": "vercel/production",
                    "parameters": {"environment": "production"},
                },
            ],
        },
    ).json()
    submitted = client.post(
        f"/api/v1/executions/{execution['execution_id']}/evidence",
        json={
            "artifacts": [
                {
                    "artifact_id": f"{step}-attestation",
                    "source": "agent",
                    "step_id": step,
                    "declared_sha256": sha256(step),
                }
                for step in ("build", "test", "deploy")
            ]
        },
    ).json()
    assert submitted["evidence"]["evidence_complete"] is False
    assert submitted["evidence"]["artifacts_content_verified"] == 0
    assert {gap["code"] for gap in submitted["evidence"]["gaps"]} == {"EVIDENCE_NOT_CONTENT_VERIFIED"}


# -------------------------------------------------------------- verification
def test_clean_run_is_allowed_only_behind_a_proof(monkeypatch):
    run = clean_run(monkeypatch)
    response = client.post(f"/api/v1/executions/{run['execution_id']}/verify", json={})
    assert response.status_code == 200, response.text
    receipt = response.json()

    assert receipt["decision"] == "ALLOW"
    assert receipt["verification"] == "VERIFIED_GLOBAL_OPTIMUM"
    assert len(receipt["proof_hash"]) == 64
    assert receipt["computed"] == {
        "authorized": True,
        "plan_aligned": True,
        "constraints_pass": True,
        "execution_succeeded": True,
        "replay_match": True,
        "evidence_complete": True,
        "evidence_completeness": 1.0,
    }
    assert receipt["independent_verification"]["verdicts_accepted_from_agent"] is False

    proof = client.get(f"/api/v1/proofs/{receipt['proof_id']}").json()
    assert proof["receipt_hash_verified"] is True
    assert proof["decision"] == "ALLOW"


def test_billed_receipt_hash_verifies_on_read(monkeypatch):
    run = clean_run(monkeypatch)

    async def fake_meter(authorization, *, sku, receipt, channel):
        return {"metered": True, "ledger_entry_hash": "a" * 64}

    receipt = asyncio.run(
        service.verify_execution(
            run["execution_id"],
            ExecutionVerifyRequest(),
            authorization=object(),
            meter=fake_meter,
        )
    )

    proof = service.read_proof(receipt["proof_id"])
    assert proof["billing"]["metered"] is True
    assert proof["receipt_hash_verified"] is True


def test_out_of_plan_action_blocks_even_though_the_agent_cannot_say_otherwise(monkeypatch):
    install_solver(monkeypatch)
    plan = approved_plan()
    body = json.dumps({"step": "deploy", "status": "ok"})
    execution = client.post(
        "/api/v1/executions",
        json={
            "plan_id": plan["plan_id"],
            "agent_identity": "github-copilot",
            "environment": "production",
            "actions": [
                {"step_id": "build", "action": "build", "target": "acme/web-app", "parameters": {"branch": "main"}},
                {"step_id": "test", "action": "test", "target": "acme/web-app"},
                {
                    "step_id": "deploy",
                    "action": "deploy",
                    "target": "vercel/production",
                    "parameters": {"environment": "staging"},
                    "output_sha256": sha256(body),
                },
            ],
        },
    ).json()
    client.post(
        f"/api/v1/executions/{execution['execution_id']}/evidence",
        json={"artifacts": [evidence_for("deploy", body)]},
    )
    receipt = client.post(f"/api/v1/executions/{execution['execution_id']}/verify", json={}).json()
    assert receipt["decision"] == "BLOCK"
    assert receipt["computed"]["plan_aligned"] is False
    assert any(item["code"] == "PARAMETER_MISMATCH" for item in receipt["findings"]["alignment"])


def test_replay_mismatch_downgrades_to_review(monkeypatch):
    install_solver(monkeypatch)
    plan = approved_plan()
    bodies = {step: json.dumps({"step": step}) for step in ("build", "test", "deploy")}
    execution = client.post(
        "/api/v1/executions",
        json={
            "plan_id": plan["plan_id"],
            "agent_identity": "github-copilot",
            "environment": "production",
            "actions": [
                {
                    "step_id": "build",
                    "action": "build",
                    "target": "acme/web-app",
                    "parameters": {"branch": "main"},
                    "output_sha256": sha256(bodies["build"]),
                },
                {"step_id": "test", "action": "test", "target": "acme/web-app", "output_sha256": sha256(bodies["test"])},
                {
                    "step_id": "deploy",
                    "action": "deploy",
                    "target": "vercel/production",
                    "parameters": {"environment": "production"},
                    "output_sha256": sha256("a deploy log that was never submitted"),
                },
            ],
        },
    ).json()
    client.post(
        f"/api/v1/executions/{execution['execution_id']}/evidence",
        json={"artifacts": [evidence_for(step, body) for step, body in bodies.items()]},
    )
    receipt = client.post(f"/api/v1/executions/{execution['execution_id']}/verify", json={}).json()
    assert receipt["decision"] == "REVIEW"
    assert receipt["computed"]["replay_match"] is False
    assert receipt["computed"]["plan_aligned"] is True


def test_cost_constraint_uses_the_recorded_cost_not_the_agents_claim(monkeypatch):
    install_solver(monkeypatch)
    plan = approved_plan()
    body = json.dumps({"step": "deploy"})
    execution = client.post(
        "/api/v1/executions",
        json={
            "plan_id": plan["plan_id"],
            "agent_identity": "github-copilot",
            "environment": "production",
            "cost_microunits": 900000,
            # The agent reports a cheaper number in its own facts block.
            "observed_facts": {"cost_microunits": 1000},
            "actions": [
                {"step_id": "build", "action": "build", "target": "acme/web-app", "parameters": {"branch": "main"}},
                {"step_id": "test", "action": "test", "target": "acme/web-app"},
                {
                    "step_id": "deploy",
                    "action": "deploy",
                    "target": "vercel/production",
                    "parameters": {"environment": "production"},
                    "output_sha256": sha256(body),
                },
            ],
        },
    ).json()
    client.post(
        f"/api/v1/executions/{execution['execution_id']}/evidence",
        json={"artifacts": [evidence_for("deploy", body)]},
    )
    receipt = client.post(f"/api/v1/executions/{execution['execution_id']}/verify", json={}).json()
    assert receipt["decision"] == "BLOCK"
    violated = {item["constraint_id"] for item in receipt["findings"]["constraints"]}
    assert "cost_cap" in violated


def test_verification_fails_closed_and_issues_no_receipt(monkeypatch):
    run = clean_run(monkeypatch)
    install_solver(monkeypatch, fail=True)
    response = client.post(f"/api/v1/executions/{run['execution_id']}/verify", json={})
    assert response.status_code == 502
    assert response.json()["error"] == "BACKEND_UNAVAILABLE"
    assert service.get_store().count("proofs") == 0


def test_an_execution_cannot_be_verified_twice(monkeypatch):
    run = clean_run(monkeypatch)
    first = client.post(f"/api/v1/executions/{run['execution_id']}/verify", json={})
    assert first.status_code == 200
    second = client.post(f"/api/v1/executions/{run['execution_id']}/verify", json={})
    assert second.status_code == 409
    assert second.json()["error"] == "EXECUTION_ALREADY_VERIFIED"
    assert second.json()["details"]["proof_id"] == first.json()["proof_id"]


def test_unknown_proof_is_a_named_refusal():
    response = client.get("/api/v1/proofs/proof_missing")
    assert response.status_code == 404
    assert response.json()["error"] == "PROOF_NOT_FOUND"
    assert response.json()["remediation"]["next_step"]


# ----------------------------------------------------------------------- mcp
def test_mcp_initialize_and_tools_list(monkeypatch):
    install_solver(monkeypatch)
    initialized = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    ).json()
    assert initialized["result"]["serverInfo"]["name"] == "dsg-one"

    listed = client.post("/api/v1/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert {
        "dsg_status",
        "dsg_create_plan",
        "dsg_approve_plan",
        "dsg_verify_plan_alignment",
        "dsg_verify_constraints",
        "dsg_record_execution",
        "dsg_submit_evidence",
        "dsg_verify_execution",
        "dsg_get_proof",
    } <= names
    for tool in listed["result"]["tools"]:
        assert tool["inputSchema"]["type"] == "object"


def test_mcp_tool_call_creates_a_plan(monkeypatch):
    install_solver(monkeypatch)
    response = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "dsg_create_plan", "arguments": PLAN},
        },
    ).json()
    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["plan_id"].startswith("plan_")


def test_mcp_rejects_a_tool_call_carrying_a_verdict():
    response = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "dsg_verify_plan_alignment",
                "arguments": {"plan": PLAN, "actions": [], "plan_aligned": True},
            },
        },
    )
    assert response.status_code == 422
    assert response.json()["error"] == "AGENT_ASSERTED_VERDICT_REJECTED"


def test_mcp_reports_a_refusal_as_a_tool_error(monkeypatch):
    install_solver(monkeypatch)
    response = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "dsg_get_proof", "arguments": {"proof_id": "proof_nope"}},
        },
    ).json()
    assert response["result"]["isError"] is True
    assert response["result"]["structuredContent"]["error"] == "PROOF_NOT_FOUND"


def test_mcp_unknown_method_is_a_jsonrpc_error():
    response = client.post("/api/v1/mcp", json={"jsonrpc": "2.0", "id": 6, "method": "tools/run"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32601


def test_mcp_get_explains_the_transport():
    response = client.get("/api/v1/mcp")
    assert response.status_code == 405
    assert response.json()["error"] == "MCP_TRANSPORT_IS_POST"
