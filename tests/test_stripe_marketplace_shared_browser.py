from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_v1 import remote_browser, remote_transport
from api_v1.models import PlanDocument, PlanStep


CINEMA_ORIGIN = "https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io"
DASHBOARD_ORIGIN = "https://dashboard.stripe.com"
MARKETPLACE_ORIGIN = "https://marketplace.stripe.com"
ALLOWED_ORIGINS = [CINEMA_ORIGIN, DASHBOARD_ORIGIN, MARKETPLACE_ORIGIN]


@pytest.fixture()
def stripe_marketplace_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "s" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))

    plan = PlanDocument(
        title="Complete DSG Governance Gate Stripe Marketplace submission",
        agent_identity="chatgpt",
        steps=[
            PlanStep(
                step_id="stripe-marketplace-submission",
                action="submit_stripe_marketplace",
                target="dashboard.stripe.com",
                parameters={
                    "browser_allowed_origins": ",".join(ALLOWED_ORIGINS),
                    "user_controller_shared": True,
                    "user_controller_operations": (
                        "identity.secret.inject,"
                        "identity.otp.submit,"
                        "identity.confirmation.click"
                    ),
                    "user_controller_origins": f"{DASHBOARD_ORIGIN},{MARKETPLACE_ORIGIN}",
                },
                description=(
                    "Upload and configure v2.7.1, run External Test, capture review evidence, "
                    "verify the final listing, then submit DSG Governance Gate for Stripe review."
                ),
            )
        ],
    )
    record = {
        "plan_id": "plan-stripe-marketplace-submit",
        "plan_hash": "d" * 64,
        "status": "APPROVED",
    }

    monkeypatch.setattr(remote_browser.service, "get_plan_record", lambda _plan_id: record)
    monkeypatch.setattr(remote_browser.service, "plan_document", lambda _record: plan)
    monkeypatch.setattr(remote_browser.billing, "authorize_request", lambda *_args, **_kwargs: None)

    relayed: list[dict] = []

    async def fake_relay(endpoint: str, payload: dict):
        assert endpoint == "https://1.1.1.1/stripe-browser"
        relayed.append(payload)
        policy = payload["context"]["browser_policy"]
        assert policy["enforced"] is True
        assert policy["enforce_current_origin"] is True
        assert policy["allowed_origins"] == sorted(ALLOWED_ORIGINS)
        return 200, {"ok": True, "kind": payload["action"]["kind"]}, "e" * 64

    monkeypatch.setattr(remote_browser, "_relay", fake_relay)

    app = FastAPI()
    app.include_router(remote_transport.router)
    return TestClient(app), relayed, tmp_path


def _connect(client: TestClient) -> tuple[str, dict]:
    response = client.post(
        "/remote-browser/sessions",
        json={
            "plan_id": "plan-stripe-marketplace-submit",
            "agent_identity": "chatgpt",
            "step_id": "stripe-marketplace-submission",
            "remote_endpoint": "https://1.1.1.1/stripe-browser",
            "ttl_seconds": 900,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["session_token"], body


def _action(client: TestClient, token: str, kind: str, *, controller="agent_executor", parameters=None):
    return client.post(
        "/remote-browser/actions",
        json={
            "session_token": token,
            "action": {
                "kind": kind,
                "controller": controller,
                "parameters": parameters or {},
            },
        },
    )


def test_stripe_marketplace_pending_submission_flow_is_plan_scoped_and_evidenced(
    stripe_marketplace_client,
) -> None:
    client, relayed, tmp_path = stripe_marketplace_client
    token, session = _connect(client)

    assert session["controllers"] == ["user", "agent_executor", "agent_verifier"]
    assert session["browser_policy"] == {
        "enforced": True,
        "allowed_origins": sorted(ALLOWED_ORIGINS),
    }
    assert session["user_controller_delegation"] == {
        "enabled": True,
        "operations": [
            "identity.confirmation.click",
            "identity.otp.submit",
            "identity.secret.inject",
        ],
        "origins": sorted([DASHBOARD_ORIGIN, MARKETPLACE_ORIGIN]),
    }

    # 1. Open the Cinema onboarding/setup page that precedes Stripe External Test.
    setup = _action(
        client,
        token,
        "browser.navigate",
        parameters={"url": f"{CINEMA_ORIGIN}/marketplace/stripe/setup?link_type=sandbox"},
    )
    assert setup.status_code == 200, setup.text

    # 2. Follow the documented Stripe OAuth v2 authorization surface.
    oauth = _action(
        client,
        token,
        "browser.navigate",
        parameters={"url": f"{MARKETPLACE_ORIGIN}/oauth/v2/authorize"},
    )
    assert oauth.status_code == 200, oauth.text

    # 3. The user may have delegated login/identity input, but only as opaque refs.
    secret_ref = "vault://stripe/marketplace-account-password"
    secret = _action(
        client,
        token,
        "identity.secret.inject",
        controller="user_delegated",
        parameters={
            "origin": DASHBOARD_ORIGIN,
            "target": "input[type=password]",
            "secret_ref": secret_ref,
        },
    )
    assert secret.status_code == 200, secret.text
    assert secret.json()["actor"] == "AGENT_VIA_USER_CONTROLLER"

    otp_ref = "otp://stripe/current-login"
    otp = _action(
        client,
        token,
        "identity.otp.submit",
        controller="user_delegated",
        parameters={
            "origin": DASHBOARD_ORIGIN,
            "target": "input[autocomplete=one-time-code]",
            "otp_ref": otp_ref,
        },
    )
    assert otp.status_code == 200, otp.text

    # 4. Executor handles the approved review workflow while verifier remains read-only.
    review = _action(
        client,
        token,
        "browser.workflow",
        parameters={
            "instruction": (
                "Verify v2.7.1 is selected, External Test is complete, the listing uses real "
                "Dashboard screenshots, and the final review fields match the approved plan."
            )
        },
    )
    assert review.status_code == 200, review.text

    evidence = _action(
        client,
        token,
        "browser.screenshot",
        controller="agent_verifier",
        parameters={"label": "stripe-marketplace-final-review"},
    )
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["actor"] == "AGENT_VERIFIER"

    # 5. Final Submit-for-review confirmation is allowed only because it was pre-authorized.
    submit = _action(
        client,
        token,
        "identity.confirmation.click",
        controller="user_delegated",
        parameters={
            "origin": DASHBOARD_ORIGIN,
            "target": "button:has-text('Submit for review')",
        },
    )
    assert submit.status_code == 200, submit.text

    # 6. An out-of-plan domain is deterministically blocked before relay.
    before = len(relayed)
    blocked = _action(
        client,
        token,
        "browser.navigate",
        parameters={"url": "https://example.com/out-of-plan"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["error"] == "BROWSER_ORIGIN_BLOCKED"
    assert len(relayed) == before

    # 7. Durable evidence may hash opaque refs but must never persist them verbatim.
    session_id = submit.json()["session_id"]
    event_files = list((tmp_path / "remote-store" / "events" / session_id).glob("*.json"))
    assert event_files
    combined = "\n".join(path.read_text(encoding="utf-8") for path in event_files)
    assert secret_ref not in combined
    assert otp_ref not in combined
    assert "sha256:" in combined


def test_stripe_marketplace_plaintext_identity_material_remains_blocked(
    stripe_marketplace_client,
) -> None:
    client, _relayed, _tmp_path = stripe_marketplace_client
    token, _ = _connect(client)
    response = _action(
        client,
        token,
        "identity.secret.inject",
        controller="user_delegated",
        parameters={
            "origin": DASHBOARD_ORIGIN,
            "target": "input[type=password]",
            "password": "must-never-cross-mcp",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "DIRECT_USER_INPUT_REQUIRED"


def test_stripe_marketplace_verifier_cannot_submit_or_mutate(
    stripe_marketplace_client,
) -> None:
    client, _relayed, _tmp_path = stripe_marketplace_client
    token, _ = _connect(client)
    response = _action(
        client,
        token,
        "browser.click",
        controller="agent_verifier",
        parameters={"selector": "button:has-text('Submit for review')"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "VERIFIER_MUTATION_BLOCKED"
