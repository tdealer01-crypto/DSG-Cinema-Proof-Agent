"""Guarded mutation execution writes a tenant-bound row and answers with it.

These tests hold the boundary this feature exists for: the response body is the
row that was read back from storage, an idempotency key is unique per tenant and
bound to one action, and a decision short of ALLOW leaves no evidence behind.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import cinema_main
from api_v1 import guarded_store, service
from api_v1.guarded_store import (
    IdempotencyConflict,
    MemoryGuardedEvidenceStore,
    PostgresGuardedEvidenceStore,
    build_record,
    reset_guarded_store,
)
from api_v1.models import ApprovePlanRequest, PlanDocument
from api_v1.mutation import GuardedMutationRequest
from api_v1.store import RecordStore, reset_store
from revenue import api as billing
from revenue.engine import RevenueEngine

client = TestClient(cinema_main.app)

DATABASE_URL = "postgresql://user:secret@db.example/dsg?sslmode=require"


@pytest.fixture
def tenant(tmp_path, monkeypatch):
    """An isolated record store, guarded store, and one authenticated tenant."""
    monkeypatch.delenv("DSG_REVENUE_ENFORCE", raising=False)
    monkeypatch.delenv("DSG_REVENUE_DATABASE_URL", raising=False)
    reset_store(RecordStore(str(tmp_path / "guarded-mutation.json")))
    reset_guarded_store(MemoryGuardedEvidenceStore())
    engine = billing.reset_engine(RevenueEngine(enforce=False))
    account, api_key = engine.accounts.issue(display_name="Guarded Tenant", plan="free")
    yield account, api_key
    billing.reset_engine(RevenueEngine(enforce=False))
    reset_guarded_store(MemoryGuardedEvidenceStore())
    reset_store(RecordStore(None))


def approved_plan(*, target: str = "production/app") -> dict:
    created = service.create_plan(
        PlanDocument.model_validate(
            {
                "title": "Authorized production mutation",
                "agent_identity": "dsg-executor",
                "channel": "api",
                "steps": [
                    {
                        "step_id": "deploy",
                        "action": "deploy_product",
                        "target": target,
                        "parameters": {"environment": "production"},
                    }
                ],
            }
        )
    )
    return service.approve_plan(
        created["plan_id"],
        ApprovePlanRequest(approver="owner", plan_hash=created["plan_hash"]),
    )


def mutation_payload(plan_id: str, *, key: str = "idem-mutation-0001", **overrides) -> dict:
    action = {
        "step_id": "deploy",
        "action": "deploy_product",
        "target": "production/app",
        "parameters": {"environment": "production"},
        "status": "succeeded",
    }
    action.update(overrides.pop("action", {}))
    body = {
        "plan_id": plan_id,
        "agent_identity": "dsg-executor",
        "idempotency_key": key,
        "action": action,
        "outputs": {"revision": "rev-17"},
    }
    body.update(overrides)
    return body


def post(payload: dict, api_key: str | None):
    headers = {"X-DSG-API-Key": api_key} if api_key else {}
    return client.post("/api/v1/control/mutations", json=payload, headers=headers)


# ------------------------------------------------------- authorized execution
def test_allowed_mutation_returns_the_row_read_back_from_storage(tenant):
    account, api_key = tenant
    plan = approved_plan()

    response = post(mutation_payload(plan["plan_id"]), api_key)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["executed"] is True
    assert body["created"] is True
    assert body["control"]["decision"] == "ALLOW"

    observed = body["observed_evidence"]
    assert observed["tenant_id"] == account.account_id
    assert observed["idempotency_key"] == "idem-mutation-0001"
    assert observed["plan_id"] == plan["plan_id"]
    assert observed["plan_hash"] == plan["plan_hash"]
    assert observed["outputs"] == {"revision": "rev-17"}
    assert observed["mutation_status"] == "succeeded"

    # The digest is recomputed from what storage returned, not from the request.
    assert body["integrity"]["source"] == "read-back-from-store"
    assert body["integrity"]["matches_stored"] is True
    assert body["integrity"]["evidence_hash_recomputed"] == observed["evidence_hash"]

    # The row is really there, and it is readable by its owner.
    stored = guarded_store.get_guarded_store().get(account.account_id, observed["evidence_id"])
    assert stored == observed


def test_row_is_bound_to_the_tenant_that_executed_it(tenant):
    _, api_key = tenant
    plan = approved_plan()
    created = post(mutation_payload(plan["plan_id"]), api_key).json()

    other_account, other_key = billing.get_engine().accounts.issue(display_name="Other Tenant")
    evidence_id = created["observed_evidence"]["evidence_id"]

    mine = client.get(f"/api/v1/control/mutations/{evidence_id}", headers={"X-DSG-API-Key": api_key})
    assert mine.status_code == 200
    assert mine.json()["observed_evidence"]["evidence_id"] == evidence_id

    theirs = client.get(
        f"/api/v1/control/mutations/{evidence_id}", headers={"X-DSG-API-Key": other_key}
    )
    assert theirs.status_code == 404
    assert theirs.json()["error"] == "MUTATION_NOT_FOUND"
    assert other_account.account_id != created["observed_evidence"]["tenant_id"]


def test_two_tenants_may_hold_the_same_idempotency_key(tenant):
    account, api_key = tenant
    plan = approved_plan()
    other_account, other_key = billing.get_engine().accounts.issue(display_name="Second Tenant")

    first = post(mutation_payload(plan["plan_id"], key="shared-key-0001"), api_key)
    second = post(mutation_payload(plan["plan_id"], key="shared-key-0001"), other_key)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["observed_evidence"]["tenant_id"] == account.account_id
    assert second.json()["observed_evidence"]["tenant_id"] == other_account.account_id
    assert (
        first.json()["observed_evidence"]["evidence_id"]
        != second.json()["observed_evidence"]["evidence_id"]
    )


# ------------------------------------------------------------- idempotency
def test_retrying_the_same_action_replays_the_original_row(tenant):
    _, api_key = tenant
    plan = approved_plan()

    first = post(mutation_payload(plan["plan_id"]), api_key)
    second = post(mutation_payload(plan["plan_id"]), api_key)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["replayed"] is True
    assert (
        second.json()["observed_evidence"] == first.json()["observed_evidence"]
    ), "a retry must return the stored row, not a second mutation"
    assert guarded_store.get_guarded_store().count() == 1


def test_same_key_for_a_different_action_is_refused_not_replayed(tenant):
    _, api_key = tenant
    plan = approved_plan(target="production/app")
    other_plan = approved_plan(target="production/other-app")

    first = post(mutation_payload(plan["plan_id"]), api_key)
    assert first.status_code == 201

    changed = mutation_payload(
        other_plan["plan_id"],
        action={"target": "production/other-app"},
    )
    conflict = post(changed, api_key)

    assert conflict.status_code == 409, conflict.text
    body = conflict.json()
    assert body["error"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert body["details"]["stored_action_hash"] != body["details"]["submitted_action_hash"]
    assert body["remediation"]["next_step"]
    assert guarded_store.get_guarded_store().count() == 1


def test_outputs_may_differ_on_a_retry_without_conflicting(tenant):
    _, api_key = tenant
    plan = approved_plan()

    post(mutation_payload(plan["plan_id"]), api_key)
    replay = post(
        mutation_payload(plan["plan_id"], outputs={"revision": "rev-18"}),
        api_key,
    )

    assert replay.status_code == 200
    assert replay.json()["observed_evidence"]["outputs"] == {"revision": "rev-17"}


# ------------------------------------------------------------------ refusals
def test_a_blocked_action_writes_no_guarded_evidence(tenant):
    _, api_key = tenant
    plan = approved_plan()

    response = post(
        mutation_payload(plan["plan_id"], action={"target": "unapproved/app"}),
        api_key,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["control"]["decision"] == "BLOCK"
    assert body["executed"] is False
    assert body["observed_evidence"] is None
    assert guarded_store.get_guarded_store().count() == 0


def test_a_draft_plan_is_blocked_before_any_mutation(tenant):
    _, api_key = tenant
    created = service.create_plan(
        PlanDocument.model_validate(
            {
                "title": "Unapproved mutation",
                "agent_identity": "dsg-executor",
                "steps": [
                    {
                        "step_id": "deploy",
                        "action": "deploy_product",
                        "target": "production/app",
                        "parameters": {"environment": "production"},
                    }
                ],
            }
        )
    )

    response = post(mutation_payload(created["plan_id"]), api_key)

    assert response.status_code == 200
    assert response.json()["control"]["code"] == "PLAN_NOT_APPROVED"
    assert response.json()["executed"] is False
    assert guarded_store.get_guarded_store().count() == 0


def test_a_pending_capability_waits_instead_of_mutating(tenant, monkeypatch):
    _, api_key = tenant
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    plan = approved_plan()

    response = post(
        mutation_payload(plan["plan_id"], required_capabilities=[{"capability": "stripe_api"}]),
        api_key,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["control"]["decision"] == "WAITING_PERMISSION"
    assert body["executed"] is False
    assert guarded_store.get_guarded_store().count() == 0


def test_an_anonymous_caller_has_no_tenant_to_bind_a_row_to(tenant):
    plan = approved_plan()

    response = post(mutation_payload(plan["plan_id"]), None)

    assert response.status_code == 401
    assert response.json()["error"] == "UNKNOWN_KEY"
    assert guarded_store.get_guarded_store().count() == 0


def test_a_submitted_verdict_is_refused_before_the_mutation_runs(tenant):
    _, api_key = tenant
    plan = approved_plan()

    response = post(mutation_payload(plan["plan_id"], verified=True), api_key)

    assert response.status_code == 422
    assert response.json()["error"] == "AGENT_ASSERTED_VERDICT_REJECTED"
    assert guarded_store.get_guarded_store().count() == 0


def test_enforced_billing_refuses_a_memory_backed_guarded_store(tenant):
    plan = approved_plan()
    enforced = billing.reset_engine(RevenueEngine(enforce=True))
    _, api_key = enforced.accounts.issue(display_name="Enforced Tenant", plan="free")
    reset_guarded_store(MemoryGuardedEvidenceStore())

    response = post(mutation_payload(plan["plan_id"]), api_key)

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["error"] == "GUARDED_STORAGE_NOT_READY"
    assert body["details"]["storage"]["durable"] is False
    assert guarded_store.get_guarded_store().count() == 0


# ------------------------------------------------------------------ contract
def test_status_reports_how_guarded_evidence_is_stored(tenant):
    body = client.get("/api/v1/status").json()["guarded_mutation_storage"]
    assert body["unique_on"] == ["tenant_id", "idempotency_key"]
    assert body["read_back_in_write_transaction"] is True
    assert body["tenant_bound"] is True
    assert body["durable"] is False  # memory backend, stated rather than implied


def test_control_contract_names_the_mutation_surface(tenant):
    body = client.get("/api/v1/control/contract").json()["mutation"]
    assert body["execute"] == "POST /api/v1/control/mutations"
    assert "same transaction" in body["guarantee"]


def test_database_url_selects_the_postgres_guarded_store():
    store = guarded_store.build_guarded_store({"DSG_REVENUE_DATABASE_URL": DATABASE_URL})
    assert isinstance(store, PostgresGuardedEvidenceStore)
    assert store.durable is True
    assert store.summary()["table"] == "dsg_guarded_evidence"
    assert isinstance(guarded_store.build_guarded_store({}), MemoryGuardedEvidenceStore)


# ------------------------------------------------------- postgres SQL contract
class _Cursor:
    def __init__(self, script: list) -> None:
        self._script = script
        self.rowcount = 0
        self._result = None

    def __enter__(self): return self
    def __exit__(self, *args): return False

    def execute(self, statement, params=()):
        self._script.append((" ".join(statement.split()), params))
        self._result = None
        if statement.lstrip().upper().startswith("INSERT"):
            self.rowcount = 1
        elif statement.lstrip().upper().startswith("SELECT"):
            self.rowcount = 1
            self._result = self._script  # replaced by the harness below

    def fetchone(self):
        return self._result


class _Connection:
    def __init__(self, script: list, row) -> None:
        self._script = script
        self._row = row
        self.committed = 0
        self.rolled_back = 0

    def cursor(self):
        cursor = _Cursor(self._script)
        original = cursor.execute

        def execute(statement, params=()):
            original(statement, params)
            if statement.lstrip().upper().startswith("SELECT"):
                cursor._result = self._row

        cursor.execute = execute
        return cursor

    def commit(self): self.committed += 1
    def rollback(self): self.rolled_back += 1
    def __enter__(self): return self
    def __exit__(self, *args): return False


def _postgres_store(monkeypatch, row):
    script: list = []
    connection = _Connection(script, row)
    monkeypatch.setattr("api_v1.guarded_store.connect", lambda _: connection)
    monkeypatch.setattr("api_v1.guarded_store.initialize_schema", lambda _: None)
    monkeypatch.setattr("api_v1.guarded_store.initialize_guarded_schema", lambda _: None)
    return PostgresGuardedEvidenceStore(DATABASE_URL), script, connection


def _candidate(**overrides) -> dict:
    body = dict(
        tenant_id="acct_dsg_tenant",
        idempotency_key="idem-postgres-0001",
        action_hash="a" * 64,
        plan_id="plan_1",
        plan_hash="b" * 64,
        agent_identity="dsg-executor",
        channel="api",
        step_id="deploy",
        action="deploy_product",
        target="production/app",
        parameters={"environment": "production"},
        decision="ALLOW",
        control_hash="c" * 64,
        mutation_status="succeeded",
        outputs={"revision": "rev-17"},
    )
    body.update(overrides)
    return build_record(**body)


def _row(record: dict) -> tuple:
    return tuple(record[name] for name in guarded_store.COLUMNS)


def test_postgres_insert_and_read_back_share_one_committed_transaction(monkeypatch):
    candidate = _candidate()
    store, script, connection = _postgres_store(monkeypatch, _row(candidate))

    observed, created = store.record(candidate)

    assert created is True
    assert observed == candidate
    assert connection.committed == 1
    assert connection.rolled_back == 0
    insert, select = script[0], script[1]
    assert insert[0].startswith("INSERT INTO dsg_guarded_evidence")
    assert "ON CONFLICT (tenant_id, idempotency_key) DO NOTHING" in insert[0]
    assert select[0].startswith("SELECT evidence_id")
    assert select[1] == ("acct_dsg_tenant", "idem-postgres-0001")


def test_postgres_refuses_a_key_whose_stored_action_differs(monkeypatch):
    stored = _candidate(action_hash="d" * 64)
    store, _script, connection = _postgres_store(monkeypatch, _row(stored))

    with pytest.raises(IdempotencyConflict) as error:
        store.record(_candidate(action_hash="e" * 64))

    assert error.value.stored_action_hash == "d" * 64
    assert error.value.submitted_action_hash == "e" * 64
    assert connection.committed == 0
    assert connection.rolled_back == 1


def test_the_executor_observations_are_stored_not_dropped(tenant):
    _, api_key = tenant
    plan = approved_plan()
    digest = "9" * 64

    response = post(
        mutation_payload(
            plan["plan_id"],
            action={
                "output_sha256": digest,
                "started_at": "2026-08-23T12:00:00Z",
                "finished_at": "2026-08-23T12:00:04Z",
            },
        ),
        api_key,
    )

    observed = response.json()["observed_evidence"]
    assert observed["output_sha256"] == digest
    assert observed["started_at"] == "2026-08-23T12:00:00Z"
    assert observed["finished_at"] == "2026-08-23T12:00:04Z"
    assert response.json()["integrity"]["matches_stored"] is True


def test_a_differing_output_digest_is_a_retry_not_a_new_record(tenant):
    """action_hash names the action; a result that differs is still the same action."""
    _, api_key = tenant
    plan = approved_plan()

    first = post(mutation_payload(plan["plan_id"], action={"output_sha256": "a" * 64}), api_key)
    second = post(mutation_payload(plan["plan_id"], action={"output_sha256": "b" * 64}), api_key)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["observed_evidence"]["output_sha256"] == "a" * 64
    assert guarded_store.get_guarded_store().count() == 1


def test_a_value_that_has_no_json_spelling_is_refused(tenant):
    """A digest must be recomputable, so NaN/Infinity never reach a stored row."""
    _, api_key = tenant
    plan = approved_plan()

    # 1e999 parses to inf, which JSON cannot spell and PostgreSQL will not store.
    payload = mutation_payload(plan["plan_id"])
    response = client.post(
        "/api/v1/control/mutations",
        content=json.dumps(payload).replace('{"revision": "rev-17"}', '{"ratio": 1e999}'),
        headers={"X-DSG-API-Key": api_key, "Content-Type": "application/json"},
    )
    assert response.status_code in {400, 422}, response.text
    assert guarded_store.get_guarded_store().count() == 0

    # And the model refuses it directly, for callers that do not arrive over HTTP.
    with pytest.raises(ValueError, match="finite"):
        GuardedMutationRequest.model_validate(
            {
                "plan_id": plan["plan_id"],
                "agent_identity": "dsg-executor",
                "idempotency_key": "idem-nonfinite-01",
                "action": {"action": "deploy_product", "target": "production/app"},
                "outputs": {"ratio": float("inf")},
            }
        )


def test_a_malformed_id_is_a_refusal_not_a_storage_error(tenant):
    _, api_key = tenant
    response = client.get(
        "/api/v1/control/mutations/not-a-uuid", headers={"X-DSG-API-Key": api_key}
    )
    assert response.status_code == 404
    assert response.json()["error"] == "MUTATION_NOT_FOUND"


def test_postgres_rejects_a_non_uuid_id_without_asking_the_database(monkeypatch):
    store, script, _connection = _postgres_store(monkeypatch, None)
    assert store.get("acct_dsg_tenant", "not-a-uuid") is None
    assert script == [], "a malformed id must not reach the database"


def test_a_row_that_cannot_be_read_back_is_refused_with_a_next_step(tenant, monkeypatch):
    _, api_key = tenant
    plan = approved_plan()

    def lose_the_row(_candidate):
        raise guarded_store.GuardedEvidenceLost("row not readable")

    monkeypatch.setattr(guarded_store.get_guarded_store(), "record", lose_the_row)
    response = post(mutation_payload(plan["plan_id"]), api_key)

    assert response.status_code == 503, response.text
    assert response.json()["error"] == "GUARDED_EVIDENCE_UNREADABLE"
    assert "same idempotency_key" in response.json()["remediation"]["next_step"]


def test_payload_columns_are_canonical_json_text_so_the_digest_reproduces():
    """JSONB normalises numbers on read-back; the evidence digest cannot survive that."""
    sql = guarded_store.GUARDED_EVIDENCE_SCHEMA_SQL
    assert "parameters TEXT NOT NULL" in sql
    assert "outputs TEXT NOT NULL" in sql
    assert "JSONB" not in sql

    record = _candidate(parameters={"threshold": 1e16}, outputs={"ratio": 0.1})
    values = {
        name: json.dumps(record[name], sort_keys=True, separators=(",", ":"))
        for name in ("parameters", "outputs")
    }
    round_tripped = {name: json.loads(text) for name, text in values.items()}
    assert round_tripped["parameters"] == record["parameters"]
    assert guarded_store.evidence_hash(dict(record, **round_tripped)) == record["evidence_hash"]


def test_postgres_schema_binds_the_tenant_and_the_unique_key():
    sql = guarded_store.GUARDED_EVIDENCE_SCHEMA_SQL
    assert "tenant_id TEXT NOT NULL REFERENCES dsg_revenue_accounts(account_id)" in sql
    assert "UNIQUE (tenant_id, idempotency_key)" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql


def test_evidence_hash_is_reproducible_from_the_stored_row():
    record = _candidate()
    assert guarded_store.evidence_hash(record) == record["evidence_hash"]
    tampered = dict(record, outputs={"revision": "rev-99"})
    assert guarded_store.evidence_hash(tampered) != record["evidence_hash"]
