from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_v1 import compliance


def _client() -> TestClient:
    app = FastAPI()
    compliance.install(app)
    return TestClient(app)


def test_compliance_status_is_truth_bounded():
    response = _client().get("/compliance/status")
    assert response.status_code == 200
    body = response.json()
    assert body["product"] == "DSG Cinema"
    assert body["certification_status"] == "NOT_CERTIFIED"
    assert body["eu_ai_act_classification"] == "USE_CASE_ASSESSMENT_REQUIRED"
    assert body["evidence_package"] == {
        "status": "AUTOMATED_INTERNAL_EVIDENCE",
        "workflow": ".github/workflows/compliance-evidence-package.yml",
        "artifact_prefix": "cinema-compliance-evidence-",
        "source_sha_bound": True,
        "production_probe_on_main": True,
        "external_certification_included": False,
        "independent_external_audit_included": False,
    }
    assert body["truth_boundary"] == {
        "z3_is_conformity_assessment": False,
        "internal_proof_is_external_certification": False,
        "universal_annex_iii_high_risk_claim": False,
    }


def test_annex_iv_mapping_does_not_claim_100_percent():
    response = _client().get("/compliance/annex-iv")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "READINESS_MAPPING"
    assert body["summary"]["total"] == 9
    assert body["summary"]["covered"] == 5
    assert body["summary"]["partial"] == 4
    assert body["summary"]["coverage_percent"] == 55.6
    assert body["evidence_package"]["source_sha_bound"] is True
    assert "not a declaration of conformity" in body["note"]


def test_annex_iv_partial_items_have_gaps():
    items = _client().get("/compliance/annex-iv").json()["items"]
    partial = [item for item in items if item["status"] == "PARTIAL"]
    assert len(partial) == 4
    assert all(item.get("gap") for item in partial)


def test_compliance_gaps_are_machine_readable_and_truth_bounded():
    response = _client().get("/compliance/gaps")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ACTION_REQUIRED"
    assert body["open_gap_count"] == 4
    assert {gap["id"] for gap in body["gaps"]} == {5, 7, 8, 9}
    assert all(gap["gap"] for gap in body["gaps"])
    assert body["truth_boundary"] == {
        "gap_list_is_certification_assessment": False,
        "closing_internal_gaps_equals_certification": False,
    }


def test_compliance_routes_do_not_expand_exact_v1_contract():
    app = FastAPI()
    compliance.install(app)
    paths = {route.path for route in app.routes}
    assert "/compliance/status" in paths
    assert "/compliance/annex-iv" in paths
    assert "/compliance/gaps" in paths
    assert not any(path.startswith("/api/v1/compliance") for path in paths)
