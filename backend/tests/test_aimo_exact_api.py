from __future__ import annotations

from app.main import app, capabilities, health


def test_aimo_exact_energy_route_is_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/v1/math/aimo/exact-energy-witness" in paths


def test_health_and_capabilities_advertise_aimo_truth_gate() -> None:
    health_payload = health()
    capabilities_payload = capabilities()

    assert health_payload["aimo_exact_energy_endpoint"] == "/v1/math/aimo/exact-energy-witness"
    assert capabilities_payload["aimo_exact_integer_energy_verifier"] is True
    assert capabilities_payload["aimo_z3_global_optimality_gate"] is True
    assert capabilities_payload["aimo_exact_energy_endpoint"] == "/v1/math/aimo/exact-energy-witness"
    assert "finite integer QUBO/Ising encoding" in capabilities_payload["runtime_truth_boundary"]
    assert "does not by itself prove" in capabilities_payload["runtime_truth_boundary"]
