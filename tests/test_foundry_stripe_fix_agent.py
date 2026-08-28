"""The Foundry agent diagnoses publicly but keeps production values local."""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi.testclient import TestClient

import cinema_main
from integrations.microsoft_foundry.stripe_fix_agent import agent, secure_config


def incremental_spec(*, required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {name: {"type": "string"} for name in secure_config.CONFIGURABLE_VALUE_NAMES},
    }
    if required is not None:
        schema["required"] = required
    return {
        "openapi": "3.1.0",
        "components": {"schemas": {"StripeAppProductionValues": schema}},
    }


class Response:
    def __init__(self, body: Any, status_code: int = 200):
        self.body = body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("request failed")

    def json(self) -> Any:
        return self.body


class FakeClient:
    def __init__(self, *, spec: dict[str, Any], status: dict[str, Any], result: dict[str, Any]):
        self.spec = spec
        self.status = status
        self.result = result
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get(self, url: str) -> Response:
        self.calls.append(("GET", url, {}))
        if url.endswith("/openapi.json"):
            return Response(self.spec)
        if url.endswith("/marketplace/stripe/status"):
            return Response(self.status)
        raise AssertionError(url)

    def post(self, url: str, **kwargs: Any) -> Response:
        self.calls.append(("POST", url, kwargs))
        return Response(self.result)


def status_with(**overrides: str) -> dict[str, Any]:
    checks = {name: "PASS" for name in secure_config.STATUS_CHECK_TO_VALUE_NAME}
    checks.update(overrides)
    return {"status": "READY" if all(value == "PASS" for value in checks.values()) else "ACTION_REQUIRED", "checks": checks}


def control_environment(**overrides: str) -> dict[str, str]:
    values = {
        "DSG_CINEMA_API_BASE": "https://cinema.example.test",
        "DSG_STRIPE_FIX_PLAN_ID": "plan-approved-1",
        "DSG_STRIPE_FIX_AGENT_IDENTITY": "microsoft-foundry-stripe-fix-agent",
        "DSG_API_KEY": "dsg_test_tenant-key",
    }
    values.update(overrides)
    return values


def test_foundry_openapi_tool_is_read_only_and_operation_ids_are_supported():
    spec = agent.load_read_only_openapi_spec()

    assert set(spec["paths"]) == {
        "/health",
        "/openapi.json",
        "/marketplace/stripe/status",
    }
    for operations in spec["paths"].values():
        assert set(operations) == {"get"}
        assert re.fullmatch(r"[A-Za-z_-]+", operations["get"]["operationId"])


def test_foundry_function_accepts_no_arguments():
    schema = agent.function_tool_schema()

    assert schema["name"] == agent.FUNCTION_NAME
    assert schema["parameters"] == {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    assert schema["strict"] is True


def test_research_mode_has_web_search_but_no_configuration_function():
    request = agent.research_request("research Stripe review requirements", model="gpt-5.5")

    assert request["tools"] == [{"type": "web_search"}]
    assert agent.FUNCTION_NAME not in json.dumps(request)


def test_live_contract_requires_all_fixed_properties_and_no_required_list():
    assert secure_config.live_contract_supports_incremental_values(incremental_spec()) is True
    assert (
        secure_config.live_contract_supports_incremental_values(
            incremental_spec(required=list(secure_config.CONFIGURABLE_VALUE_NAMES))
        )
        is False
    )
    incomplete = incremental_spec()
    del incomplete["components"]["schemas"]["StripeAppProductionValues"]["properties"][
        "STRIPE_APP_SIGNING_SECRET"
    ]
    assert secure_config.live_contract_supports_incremental_values(incomplete) is False


def test_live_fastapi_contract_is_incremental():
    spec = TestClient(cinema_main.app).get("/openapi.json").json()

    assert secure_config.live_contract_supports_incremental_values(spec) is True


def test_legacy_live_contract_blocks_before_collecting_any_value():
    old_spec = incremental_spec(required=list(secure_config.CONFIGURABLE_VALUE_NAMES))
    client = FakeClient(
        spec=old_spec,
        status=status_with(app_signing_secret="MISSING"),
        result={},
    )

    def must_not_collect(*args: Any, **kwargs: Any):
        raise AssertionError("collector must not run before deployment")

    result = secure_config.execute_secure_configuration(
        client=client,
        environ=control_environment(STRIPE_APP_SIGNING_SECRET="absec_sensitive"),
        collector=must_not_collect,
    )

    assert result["decision"] == "WAITING_DEPLOYMENT"
    assert result["live_contract_incremental"] is False
    assert result["secret_values_exposed"] is False
    assert [call[0:2] for call in client.calls] == [
        ("GET", "https://cinema.example.test/openapi.json")
    ]


def test_secure_host_posts_only_non_pass_values_and_returns_no_secret():
    sensitive = "absec_local-only-sensitive-value"
    client = FakeClient(
        spec=incremental_spec(),
        status=status_with(app_signing_secret="MISSING"),
        result={
            "decision": "ALLOW",
            "executed": True,
            "evidence": {
                "environment_secrets": [{"name": "STRIPE_APP_SIGNING_SECRET"}],
                "secret_values_exposed": False,
            },
        },
    )
    result = secure_config.execute_secure_configuration(
        client=client,
        environ=control_environment(STRIPE_APP_SIGNING_SECRET=sensitive),
    )

    assert result["decision"] == "ALLOW"
    assert result["configured_value_names"] == ["STRIPE_APP_SIGNING_SECRET"]
    assert sensitive not in json.dumps(result)
    post = client.calls[-1]
    assert post[0] == "POST"
    assert post[2]["json"]["values"] == {"STRIPE_APP_SIGNING_SECRET": sensitive}
    assert post[2]["headers"] == {"X-DSG-API-Key": "dsg_test_tenant-key"}


def test_secure_host_names_missing_local_values_without_posting():
    client = FakeClient(
        spec=incremental_spec(),
        status=status_with(oauth_test_authorize_url="MISSING"),
        result={},
    )
    result = secure_config.execute_secure_configuration(
        client=client,
        environ=control_environment(),
    )

    assert result["decision"] == "WAITING_OPERATOR_INPUT"
    assert result["missing"] == ["STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL"]
    assert all(call[0] == "GET" for call in client.calls)


def test_secure_host_refuses_reused_non_live_keys():
    reused = "sk_test_same-local-key"
    client = FakeClient(
        spec=incremental_spec(),
        status=status_with(
            oauth_test_secret_key="REUSED",
            oauth_sandbox_secret_key="REUSED",
        ),
        result={},
    )
    result = secure_config.execute_secure_configuration(
        client=client,
        environ=control_environment(
            STRIPE_APP_OAUTH_TEST_SECRET_KEY=reused,
            STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY=reused,
        ),
    )

    assert result["decision"] == "WAITING_OPERATOR_INPUT"
    assert set(result["missing"]) == {
        "STRIPE_APP_OAUTH_TEST_SECRET_KEY",
        "STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY",
    }
    assert reused not in json.dumps(result)
    assert all(call[0] == "GET" for call in client.calls)


def test_ready_status_performs_no_configuration_write():
    client = FakeClient(
        spec=incremental_spec(),
        status=status_with(),
        result={},
    )
    result = secure_config.execute_secure_configuration(
        client=client,
        environ=control_environment(),
    )

    assert result["decision"] == "ALLOW"
    assert result["executed"] is False
    assert result["stripe_status"] == "READY"
    assert all(call[0] == "GET" for call in client.calls)


def test_executor_result_sanitizer_removes_value_shaped_fields():
    body = {
        "decision": "ALLOW",
        "executed": True,
        "value": "secret",
        "nested": {"token": "secret", "safe": "evidence"},
    }

    result = secure_config._sanitized_executor_result(body)

    assert result == {
        "decision": "ALLOW",
        "executed": True,
        "nested": {"safe": "evidence"},
        "secret_values_exposed": False,
    }
