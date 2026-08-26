"""The console must never show a verification state it did not receive.

A dashboard that renders a green PASS from its own markup is a screenshot, not a
console. These tests hold the prototype to the same standard as the API: before
a response arrives it says NOT CONNECTED or PENDING, and every verified state it
can display is read from a field the API returned.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import cinema_main

CONSOLE_PATH = Path(__file__).resolve().parent.parent / "web" / "dsg-one-3d" / "index.html"

client = TestClient(cinema_main.app)


@pytest.fixture(scope="module")
def page() -> str:
    return CONSOLE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def markup(page: str) -> str:
    return page.split("<script>")[0]


def test_console_is_served_from_the_api_origin():
    response = client.get("/app")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "DSG ONE" in response.text


def test_customer_dashboard_is_served_from_the_api_origin():
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "DSG ONE Customer" in response.text
    assert "Activate free account" in response.text
    assert 'id="disconnect"' in response.text
    assert 'id="remoteOn"' in response.text
    assert 'id="remoteOff"' in response.text
    assert 'id="remoteEvidence"' in response.text
    for forbidden in (
        'id="remotePlanId"',
        'id="remoteAgentId"',
        'id="remoteStepId"',
        'id="remoteEndpoint"',
        'id="remoteActionKind"',
        'id="remoteActionParameters"',
        'id="remoteSend"',
    ):
        assert forbidden not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    script = client.get("/dashboard-assets/dashboard.js")
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("application/javascript")
    for endpoint in (
        "/onboarding/status",
        "/billing/usage",
        "/billing/activate",
        "/billing/checkout/session",
        "/billing/portal/session",
        "/remote-browser/status",
        "/remote-browser/enable",
        "/remote-browser/disable",
    ):
        assert endpoint in script.text
    for developer_endpoint in (
        "/remote-browser/sessions",
        "/remote-browser/actions",
        "/remote-browser/disconnect",
    ):
        assert developer_endpoint not in script.text


def test_remote_dashboard_is_chat_driven_and_preserves_shared_browser_semantics():
    response = client.get("/dashboard")
    script = client.get("/dashboard-assets/dashboard.js")
    live_script = client.get("/dashboard-assets/browserbase-live.js")
    assert "สั่งงานกับ Agent ในแชทตามปกติ" in response.text
    assert "managed browser environment are prepared by Cinema automatically" in response.text
    assert "remoteEndpoint" not in response.text
    assert "your browser session stays live" in script.text
    assert live_script.status_code == 200
    assert "/remote-browser/browserbase/live-frame" in live_script.text
    assert "/remote-browser/browserbase/embed/" in live_script.text
    assert "same browser session" in live_script.text
    assert "takeover" not in response.text.lower()
    assert "resume agent" not in response.text.lower()
    assert "localStorage" not in script.text
    assert "sessionStorage" not in script.text


def test_static_markup_shows_no_verification_state(markup: str):
    for forbidden in ("PASS", "VERIFIED", "MATCH", "COMPLETE", "SUCCESS", "HEALTHY"):
        assert forbidden not in markup, f"static markup ships a {forbidden} state"
    assert "NOT CONNECTED" in markup


def test_no_fabricated_hashes_or_amounts(page: str):
    assert not re.search(r"[0-9a-f]{64}", page), "the page ships a literal hash"
    assert not re.search(r"\$\d", page), "the page ships a literal currency amount"


def test_every_displayed_verdict_is_read_from_a_response(page: str):
    for guard in (
        'alignment.plan_aligned ? "PASS"',
        'constraints.constraints_pass ? "PASS"',
        'ev.evidence_complete ? "COMPLETE"',
        'rp.replay_match ? "MATCH"',
        "state: receipt.decision",
    ):
        assert guard in page, f"missing computed guard: {guard}"


def test_console_drives_the_documented_flow(page: str):
    for endpoint in (
        "/api/v1/status",
        "/api/v1/plans",
        "/approve",
        "/api/v1/verify/plan-alignment",
        "/api/v1/verify/constraints",
        "/api/v1/executions",
        "/evidence",
        "/verify",
        "/api/v1/proofs/",
        "/api/v1/mcp",
    ):
        assert endpoint in page, f"the console never calls {endpoint}"


def test_console_never_submits_a_verdict(page: str):
    for verdict in ("plan_aligned:", "constraints_pass:", "replay_match:", "evidence_complete:", "verified:"):
        assert verdict not in page, f"the console assembles {verdict} into a request"


def test_failure_path_states_that_nothing_is_verified(page: str):
    assert "NOT VERIFIED" in page
    assert "fails closed" in page or "no verdict is shown" in page.lower()
