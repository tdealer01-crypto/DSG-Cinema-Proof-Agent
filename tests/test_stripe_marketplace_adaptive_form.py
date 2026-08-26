from __future__ import annotations

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


LISTING_DATA = {
    "app_name": "DSG Governance Gate",
    "logo": "artifact://stripe-app/icon.png",
    "built_by": "Thanawat Suparongsuwan",
    "category": "Data and analytics",
    "works_with": "Payments",
    "privacy_url": "https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/main/marketplace/stripe/PRIVACY.md",
    "company_website": "https://dsgoneverifiedweb.z1.web.core.windows.net/",
    "pricing_url": "https://dsgoneverifiedweb.z1.web.core.windows.net/#pricing",
    "support_email": "t.dealer01@dsg.pics",
    "support_url": "https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/issues",
    "subtitle": "Exact Z3-verified policy decisions for Stripe payments.",
    "language": "English",
    "version": "2.7.1",
    "feature_1": "Verified payment decision",
    "feature_2": "Exact proof receipt",
    "feature_3": "Transaction-bound verification",
    # This value represents a publisher-profile fact that was explicitly approved
    # before execution. The test deliberately does not infer a real headquarters.
    "based_in": "APPROVED_TEST_LOCATION",
}


MISSING_HQ_DATA = {key: value for key, value in LISTING_DATA.items() if key != "based_in"}


class FakeStripePublishWizard:
    """Small deterministic browser-executor double for an evolving Stripe UI.

    The important behavior is that later steps are not known to the agent up front.
    They are discovered only through browser.extract after the previous step is
    completed, matching the real publish wizard behavior shown in the screenshots.
    """

    def __init__(self) -> None:
        self.step = 1
        self.values: dict[str, str] = {}
        self.actions: list[dict] = []

    def schema(self) -> dict:
        if self.step == 1:
            return {
                "step": 1,
                "of": 4,
                "required_fields": [
                    {"name": "logo", "type": "upload"},
                    {"name": "built_by", "type": "text"},
                    {"name": "category", "type": "select"},
                    {"name": "works_with", "type": "select"},
                    {"name": "privacy_url", "type": "text"},
                    {"name": "company_website", "type": "text"},
                    {"name": "pricing_url", "type": "text"},
                    {"name": "support_email", "type": "text"},
                    {"name": "support_url", "type": "text"},
                    # This field is intentionally discovered from the UI and was
                    # not enumerated as a special-case action in the approved plan.
                    {"name": "based_in", "type": "select"},
                ],
                "continue_control": "button:has-text('Continue')",
            }
        if self.step == 2:
            return {
                "step": 2,
                "of": 4,
                "required_fields": [
                    {"name": "subtitle", "type": "text"},
                    {"name": "language", "type": "select"},
                    # New field appears only after Step 1 is accepted.
                    {"name": "version", "type": "select"},
                ],
                "continue_control": "button:has-text('Continue')",
            }
        if self.step == 3:
            return {
                "step": 3,
                "of": 4,
                "required_fields": [
                    {"name": "feature_1", "type": "text"},
                    {"name": "feature_2", "type": "text"},
                    {"name": "feature_3", "type": "text"},
                ],
                "continue_control": "button:has-text('Continue')",
            }
        return {
            "step": 4,
            "of": 4,
            "required_fields": [],
            "completion_control": "button:has-text('Submit for review')",
            "ready_for_submit": True,
        }

    def missing_for_current_step(self) -> list[str]:
        return [
            field["name"]
            for field in self.schema()["required_fields"]
            if not self.values.get(field["name"])
        ]

    async def relay(self, endpoint: str, payload: dict):
        assert endpoint == "https://1.1.1.1/stripe-browser"
        self.actions.append(payload)
        action = payload["action"]
        kind = action["kind"]
        params = action.get("parameters") or {}

        if kind == "browser.extract":
            return 200, self.schema(), "a" * 64

        if kind in {"browser.type", "browser.select"}:
            field = str(params["field"])
            self.values[field] = str(params["value"])
            return 200, {"ok": True, "field": field}, "b" * 64

        if kind == "browser.upload":
            field = str(params["field"])
            self.values[field] = str(params["file_ref"])
            return 200, {"ok": True, "field": field}, "c" * 64

        if kind == "browser.click" and params.get("selector") == "button:has-text('Continue')":
            missing = self.missing_for_current_step()
            if missing:
                return 422, {"ok": False, "missing": missing}, "d" * 64
            self.step = min(self.step + 1, 4)
            return 200, {"ok": True, "step": self.step}, "e" * 64

        if kind == "identity.confirmation.click":
            assert self.step == 4
            assert params.get("target") == "button:has-text('Submit for review')"
            return 200, {"ok": True, "submitted": True}, "f" * 64

        return 200, {"ok": True, "kind": kind}, "0" * 64


@pytest.fixture()
def adaptive_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "s" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))

    plan = PlanDocument(
        title="Complete Stripe Marketplace publish wizard adaptively",
        agent_identity="chatgpt",
        steps=[
            PlanStep(
                step_id="stripe-publish-wizard",
                action="complete_stripe_marketplace_submission",
                target="dashboard.stripe.com",
                parameters={
                    "browser_allowed_origins": ",".join(ALLOWED_ORIGINS),
                    "user_controller_shared": True,
                    "user_controller_operations": "identity.confirmation.click",
                    "user_controller_origins": DASHBOARD_ORIGIN,
                },
                description=(
                    "Discover each Stripe publish step from the live shared browser, fill all required "
                    "listing fields from approved sources, verify each step, and submit for review only "
                    "after the final review step is reached. Newly rendered form fields remain in-plan "
                    "when they are required to complete this approved Marketplace submission."
                ),
            )
        ],
    )
    record = {
        "plan_id": "plan-stripe-adaptive-publish",
        "plan_hash": "9" * 64,
        "status": "APPROVED",
    }

    monkeypatch.setattr(remote_browser.service, "get_plan_record", lambda _plan_id: record)
    monkeypatch.setattr(remote_browser.service, "plan_document", lambda _record: plan)
    monkeypatch.setattr(remote_browser.billing, "authorize_request", lambda *_args, **_kwargs: None)

    wizard = FakeStripePublishWizard()
    monkeypatch.setattr(remote_browser, "_relay", wizard.relay)

    app = FastAPI()
    app.include_router(remote_transport.router)
    return TestClient(app), wizard


def _connect(client: TestClient) -> str:
    response = client.post(
        "/remote-browser/sessions",
        json={
            "plan_id": "plan-stripe-adaptive-publish",
            "agent_identity": "chatgpt",
            "step_id": "stripe-publish-wizard",
            "remote_endpoint": "https://1.1.1.1/stripe-browser",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["session_token"]


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


def _run_adaptive_agent(client: TestClient, token: str, approved_data: dict[str, str]) -> dict:
    discovered_steps: list[int] = []

    for _ in range(12):
        observed = _action(
            client,
            token,
            "browser.extract",
            controller="agent_verifier",
            parameters={"query": "Return the current publish step and all required visible fields."},
        )
        assert observed.status_code == 200, observed.text
        page = observed.json()["response"]
        step = int(page["step"])
        if step not in discovered_steps:
            discovered_steps.append(step)

        for field in page.get("required_fields", []):
            name = field["name"]
            if name not in approved_data:
                return {
                    "status": "WAITING_APPROVED_DATA",
                    "field": name,
                    "step": step,
                    "discovered_steps": discovered_steps,
                }
            value = approved_data[name]
            if field["type"] == "upload":
                result = _action(
                    client,
                    token,
                    "browser.upload",
                    parameters={"field": name, "file_ref": value},
                )
            elif field["type"] == "select":
                result = _action(
                    client,
                    token,
                    "browser.select",
                    parameters={"field": name, "value": value},
                )
            else:
                result = _action(
                    client,
                    token,
                    "browser.type",
                    parameters={"field": name, "value": value},
                )
            assert result.status_code == 200, result.text

        if page.get("ready_for_submit"):
            submitted = _action(
                client,
                token,
                "identity.confirmation.click",
                controller="user_delegated",
                parameters={
                    "origin": DASHBOARD_ORIGIN,
                    "target": page["completion_control"],
                },
            )
            assert submitted.status_code == 200, submitted.text
            return {
                "status": "SUCCESS",
                "submitted": submitted.json()["response"]["submitted"],
                "discovered_steps": discovered_steps,
            }

        continued = _action(
            client,
            token,
            "browser.click",
            parameters={"selector": page["continue_control"]},
        )
        assert continued.status_code == 200, continued.text

    return {"status": "FAILED_MAX_STEPS", "discovered_steps": discovered_steps}


def test_agent_discovers_new_stripe_steps_and_continues_to_final_submission(adaptive_client) -> None:
    client, wizard = adaptive_client
    token = _connect(client)

    result = _run_adaptive_agent(client, token, LISTING_DATA)

    assert result == {
        "status": "SUCCESS",
        "submitted": True,
        "discovered_steps": [1, 2, 3, 4],
    }
    assert wizard.step == 4
    assert wizard.values["version"] == "2.7.1"
    assert wizard.values["privacy_url"].endswith("marketplace/stripe/PRIVACY.md")
    assert any(item["action"]["kind"] == "browser.upload" for item in wizard.actions)
    assert any(item["action"]["kind"] == "identity.confirmation.click" for item in wizard.actions)


def test_agent_does_not_guess_new_required_field_without_approved_source(adaptive_client) -> None:
    client, wizard = adaptive_client
    token = _connect(client)

    result = _run_adaptive_agent(client, token, MISSING_HQ_DATA)

    assert result == {
        "status": "WAITING_APPROVED_DATA",
        "field": "based_in",
        "step": 1,
        "discovered_steps": [1],
    }
    assert wizard.step == 1
    assert not any(item["action"]["kind"] == "identity.confirmation.click" for item in wizard.actions)
