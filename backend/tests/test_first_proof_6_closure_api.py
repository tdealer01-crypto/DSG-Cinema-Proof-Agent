from __future__ import annotations

from app.main import app, capabilities, health


def test_first_proof_6_closure_route_is_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/v1/math/first-proof-6/closure" in paths


def test_health_and_capabilities_advertise_reference_closure() -> None:
    health_payload = health()
    capabilities_payload = capabilities()

    assert health_payload["first_proof_6_closure_endpoint"] == "/v1/math/first-proof-6/closure"
    assert capabilities_payload["first_proof_6_reference_theorem_closed"] is True
    assert capabilities_payload["first_proof_6_reference_constant"] == "1/42"
    assert capabilities_payload["first_proof_6_closure_endpoint"] == "/v1/math/first-proof-6/closure"
    assert "does not claim independent discovery" in capabilities_payload["runtime_truth_boundary"]
