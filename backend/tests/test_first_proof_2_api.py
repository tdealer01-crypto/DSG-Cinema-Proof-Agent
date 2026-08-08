from __future__ import annotations

from app.main import app, capabilities, health


def test_first_proof_2_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/v1/math/first-proof-2/closure" in paths
    assert "/v1/math/first-proof-2/reconstruction" in paths


def test_health_and_capabilities_advertise_first_proof_2_certificates() -> None:
    health_payload = health()
    capabilities_payload = capabilities()

    assert health_payload["first_proof_2_closure_endpoint"] == "/v1/math/first-proof-2/closure"
    assert health_payload["first_proof_2_reconstruction_endpoint"] == "/v1/math/first-proof-2/reconstruction"
    assert capabilities_payload["first_proof_2_reference_theorem_closed"] is True
    assert capabilities_payload["first_proof_2_reference_reconstruction_audited"] is True
    assert capabilities_payload["first_proof_2_closure_endpoint"] == "/v1/math/first-proof-2/closure"
    assert capabilities_payload["first_proof_2_reconstruction_endpoint"] == "/v1/math/first-proof-2/reconstruction"
    assert "does not claim an independent formalization" in capabilities_payload["runtime_truth_boundary"]
