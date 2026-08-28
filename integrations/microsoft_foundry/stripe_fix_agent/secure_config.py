"""Local, argument-free host for the Stripe production configuration function.

The Foundry model never receives a Stripe value.  It can request the
``apply_approved_stripe_production_values`` function with an empty argument
object; this local host then checks the deployed OpenAPI contract before it
reads any value from the process environment.  Only values whose live status
check is not PASS are sent to the fixed-name, plan-gated Cinema executor.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

DEFAULT_CINEMA_API_BASE = (
    "https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io"
)

STATUS_CHECK_TO_VALUE_NAME = {
    "app_signing_secret": "STRIPE_APP_SIGNING_SECRET",
    "oauth_test_secret_key": "STRIPE_APP_OAUTH_TEST_SECRET_KEY",
    "oauth_sandbox_secret_key": "STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY",
    "oauth_test_authorize_url": "STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL",
    "oauth_sandbox_authorize_url": "STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL",
    "oauth_live_authorize_url": "DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL",
}
CONFIGURABLE_VALUE_NAMES = tuple(STATUS_CHECK_TO_VALUE_NAME.values())
SECRET_VALUE_NAMES = frozenset(CONFIGURABLE_VALUE_NAMES[:-1])


def _cinema_base(environ: Mapping[str, str]) -> str:
    value = (environ.get("DSG_CINEMA_API_BASE") or DEFAULT_CINEMA_API_BASE).rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("DSG_CINEMA_API_BASE must be an HTTPS origin")
    return value


def _production_values_schema(spec: Mapping[str, Any]) -> Mapping[str, Any] | None:
    components = spec.get("components")
    schemas = components.get("schemas") if isinstance(components, Mapping) else None
    if not isinstance(schemas, Mapping):
        return None
    exact = schemas.get("StripeAppProductionValues")
    if isinstance(exact, Mapping):
        return exact
    for name, schema in schemas.items():
        if str(name).endswith("StripeAppProductionValues") and isinstance(schema, Mapping):
            return schema
    return None


def live_contract_supports_incremental_values(spec: Mapping[str, Any]) -> bool:
    """Return true only for the deployed non-empty-subset executor contract."""
    schema = _production_values_schema(spec)
    if schema is None:
        return False
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return False
    if not set(CONFIGURABLE_VALUE_NAMES).issubset(properties):
        return False
    required = schema.get("required")
    return required in (None, [])


def missing_value_names(status: Mapping[str, Any]) -> tuple[str, ...]:
    """Map non-PASS live checks to the fixed executor destination names."""
    checks = status.get("checks")
    if not isinstance(checks, Mapping):
        return CONFIGURABLE_VALUE_NAMES
    return tuple(
        value_name
        for check_name, value_name in STATUS_CHECK_TO_VALUE_NAME.items()
        if checks.get(check_name) != "PASS"
    )


def collect_values_from_environment(
    names: tuple[str, ...],
    *,
    environ: Mapping[str, str],
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Read only the requested values without logging or returning them as evidence."""
    values: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        value = environ.get(name)
        if value is None or not value.strip():
            missing.append(name)
        else:
            values[name] = value.strip()
    return values, tuple(missing)


def _idempotency_key(plan_id: str, names: tuple[str, ...]) -> str:
    material = f"{plan_id}:{','.join(names)}".encode("utf-8")
    return "stripe-fix-" + hashlib.sha256(material).hexdigest()[:32]


def _safe_error(
    *,
    decision: str,
    next_step: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "decision": decision,
        "executed": False,
        **details,
        "next_step": next_step,
        "secret_values_exposed": False,
    }


def _sanitized_executor_result(body: Any) -> dict[str, Any]:
    """Retain server evidence while recursively removing value-shaped fields."""
    if not isinstance(body, Mapping):
        return _safe_error(
            decision="ERROR",
            next_step="Inspect the Cinema executor response shape before retrying.",
            error="INVALID_EXECUTOR_RESPONSE",
        )

    forbidden_keys = {
        "values",
        "value",
        "encrypted_value",
        "token",
        "authorization",
        "api_key",
    }

    def clean(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): clean(item)
                for key, item in value.items()
                if str(key).lower() not in forbidden_keys
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    cleaned = clean(body)
    assert isinstance(cleaned, dict)
    cleaned["secret_values_exposed"] = False
    return cleaned


def execute_secure_configuration(
    *,
    client: httpx.Client | Any | None = None,
    environ: Mapping[str, str] | None = None,
    collector: Callable[..., tuple[dict[str, str], tuple[str, ...]]] = (
        collect_values_from_environment
    ),
) -> dict[str, Any]:
    """Apply only missing fixed-name values after a live compatibility gate.

    The first network operation is always ``GET /openapi.json``.  If the live
    service still advertises the legacy all-values-required schema, this
    function returns ``WAITING_DEPLOYMENT`` before invoking ``collector``.
    """
    current_env = os.environ if environ is None else environ
    try:
        base = _cinema_base(current_env)
    except ValueError as exc:
        return _safe_error(
            decision="WAITING_OPERATOR_INPUT",
            next_step=str(exc),
            missing=["DSG_CINEMA_API_BASE"],
        )

    owns_client = client is None
    active_client = client or httpx.Client(timeout=20.0, follow_redirects=False)
    try:
        try:
            spec_response = active_client.get(f"{base}/openapi.json")
            spec_response.raise_for_status()
            spec = spec_response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            return _safe_error(
                decision="WAITING_DEPLOYMENT",
                next_step=(
                    "Restore the live Cinema OpenAPI endpoint, then retry; no Stripe "
                    "value was read."
                ),
                live_contract_incremental=False,
            )

        if not isinstance(spec, Mapping) or not live_contract_supports_incremental_values(spec):
            return _safe_error(
                decision="WAITING_DEPLOYMENT",
                next_step=(
                    "Deploy the incremental Stripe executor contract before retrying; "
                    "no Stripe value was read."
                ),
                live_contract_incremental=False,
            )

        try:
            status_response = active_client.get(f"{base}/marketplace/stripe/status")
            status_response.raise_for_status()
            status = status_response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            return _safe_error(
                decision="WAITING_DEPLOYMENT",
                next_step="Restore the live Stripe readiness endpoint, then retry.",
                live_contract_incremental=True,
            )
        if not isinstance(status, Mapping):
            return _safe_error(
                decision="WAITING_DEPLOYMENT",
                next_step="Restore the live Stripe readiness response contract, then retry.",
                live_contract_incremental=True,
            )

        names = missing_value_names(status)
        if not names:
            return _safe_error(
                decision="ALLOW",
                next_step="No configuration write is required; proceed to External Test.",
                live_contract_incremental=True,
                stripe_status="READY",
            )

        values, locally_missing = collector(names, environ=current_env)
        if locally_missing:
            return _safe_error(
                decision="WAITING_OPERATOR_INPUT",
                next_step=(
                    "Load the listed Stripe-issued values into the local host environment "
                    "without placing them in a prompt or URL, then retry."
                ),
                live_contract_incremental=True,
                missing=list(locally_missing),
            )

        test_key = values.get("STRIPE_APP_OAUTH_TEST_SECRET_KEY")
        sandbox_key = values.get("STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY")
        if test_key is not None and sandbox_key is not None and test_key == sandbox_key:
            return _safe_error(
                decision="WAITING_OPERATOR_INPUT",
                next_step="Load distinct test-mode and managed-sandbox Stripe keys.",
                live_contract_incremental=True,
                missing=[
                    "STRIPE_APP_OAUTH_TEST_SECRET_KEY",
                    "STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY",
                ],
            )

        plan_id = (current_env.get("DSG_STRIPE_FIX_PLAN_ID") or "").strip()
        api_key = (current_env.get("DSG_API_KEY") or "").strip()
        missing_control = []
        if not plan_id:
            missing_control.append("DSG_STRIPE_FIX_PLAN_ID")
        if not api_key:
            missing_control.append("DSG_API_KEY")
        if missing_control:
            return _safe_error(
                decision="WAITING_OPERATOR_INPUT",
                next_step="Load the approved plan id and tenant API key, then retry.",
                live_contract_incremental=True,
                missing=missing_control,
            )

        identity = (
            current_env.get("DSG_STRIPE_FIX_AGENT_IDENTITY")
            or "microsoft-foundry-stripe-fix-agent"
        ).strip()
        idempotency_key = (
            current_env.get("DSG_STRIPE_FIX_IDEMPOTENCY_KEY")
            or _idempotency_key(plan_id, names)
        ).strip()
        trace_id = (current_env.get("DSG_STRIPE_FIX_TRACE_ID") or "").strip() or None
        payload = {
            "plan_id": plan_id,
            "agent_identity": identity,
            "idempotency_key": idempotency_key,
            "values": values,
            "trace_id": trace_id,
        }
        try:
            response = active_client.post(
                f"{base}/api/v1/control/configure-stripe-app",
                headers={"X-DSG-API-Key": api_key},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            return _safe_error(
                decision="ERROR",
                next_step="Inspect Cinema availability and retry the same approved plan.",
                live_contract_incremental=True,
                configured_value_names=list(names),
            )
        result = _sanitized_executor_result(body)
        result["live_contract_incremental"] = True
        result["configured_value_names"] = list(names)
        result["secret_values_exposed"] = False
        return result
    finally:
        if owns_client:
            active_client.close()


def main() -> None:
    """Run the secure host directly without exposing values on the command line."""
    print(json.dumps(execute_secure_configuration(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
