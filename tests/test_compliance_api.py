from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_v1 import compliance


def _client() -> TestClient:
    app = FastAPI()
    compliance.install(app)
    return TestClient(app)


def test_compliance_status_is_truth_bounded():
    response = _client().get("/api/v1/compliance/status")
    assert response.status_code == 200
    body = response.json()
    assert body["product"] == "DSG Cinema"
    assert body["certification_status"] == "NOT_CERTIFIED"
    assert body["eu_ai_act_classification"] == "USE_CASE_ASSESSMENT_REQUIRED"
    assert body["truth_boundary"] == {
        "z3_is_conformity_assessment": False,
        "internal_proof_is_external_certification": False,
        "universal_annex_iii_high_risk_claim": False,
    }


def test_annex_iv_mapping_does_not_claim_100_percent():
    response = _client().get("/api/v1/compliance/annex-iv")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "READINESS_MAPPING"
    assert body["summary"]["total"] == 9
    assert body["summary"]["covered"] == 5
    assert body["summary"]["partial"] == 4
    assert body["summary"]["coverage_percent"] == 55.6
    assert "not a declaration of conformity" in body["note"]


def test_annex_iv_partial_items_have_gaps():
    items = _client().get("/api/v1/compliance/annex-iv").json()["items"]
    partial = [item for item in items if item["status"] == "PARTIAL"]
    assert len(partial) == 4
    assert all(item.get("gap") for item in partial)
