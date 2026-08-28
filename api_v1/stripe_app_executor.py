"""Plan-gated Stripe App production configuration through a GitHub App.

The endpoint in this module is intentionally narrow.  A caller supplies one or
more values from a fixed allowlist, but cannot choose the action, target,
repository, environment, or destination names.  DSG re-runs the approved-plan
preflight, then a server-side GitHub App writes only the submitted production
environment secrets or repository variable.  This incremental contract avoids
collecting already-configured secrets again.  The response is built from
GitHub read-back metadata and never contains a secret value.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Callable, Optional
from urllib.parse import quote, urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import APIRouter, Depends, Header
from nacl.public import PublicKey, SealedBox
from pydantic import Field, SecretStr, field_validator

from .canonical import utc_now
from .capability_broker import CapabilityRequirement
from .control import UnifiedPreflightRequest, evaluate_unified_preflight
from .errors import ApiError
from .models import ObservedAction, Strict
from .mutation import GuardedMutationRequest, execute_guarded_mutation, tenant_for
from .router import reject_agent_verdicts

ACTION = "configure_stripe_app"
TARGET = "pics.dsg.governance"
STEP_ID = "stripe-production-setup"
CAPABILITY = "github_actions_admin"
ENVIRONMENT = "production"
VARIABLE_NAME = "DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL"
SECRET_NAMES = (
    "STRIPE_APP_SIGNING_SECRET",
    "STRIPE_APP_OAUTH_TEST_SECRET_KEY",
    "STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY",
    "STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL",
    "STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL",
)

_GITHUB_API = "https://api.github.com"
_GITHUB_API_VERSION = "2026-03-10"
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{7,127}$")

router = APIRouter(
    prefix="/api/v1/control",
    tags=["dsg-stripe-app-executor"],
    dependencies=[Depends(reject_agent_verdicts)],
)


def _https_url(value: str, label: str) -> str:
    if len(value) > 2048:
        raise ValueError(f"{label} is too long")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{label} must be an absolute HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{label} must not contain URL credentials")
    return value


class StripeAppProductionValues(Strict):
    """A non-empty subset of fixed Stripe production destinations."""

    STRIPE_APP_SIGNING_SECRET: SecretStr | None = None
    STRIPE_APP_OAUTH_TEST_SECRET_KEY: SecretStr | None = None
    STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY: SecretStr | None = None
    STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL: SecretStr | None = None
    STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL: SecretStr | None = None
    DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL: str | None = Field(
        default=None,
        min_length=8,
        max_length=2048,
    )

    def validate_for_execution(self) -> None:
        """Validate without attaching raw secret inputs to a Pydantic 422 body."""
        secret_values = self.secret_values()
        live_url = self.live_authorize_url()
        if not secret_values and live_url is None:
            raise StripeAppValueError(
                "values",
                "provide at least one fixed Stripe App production value",
            )

        signing = secret_values.get("STRIPE_APP_SIGNING_SECRET")
        test_key = secret_values.get("STRIPE_APP_OAUTH_TEST_SECRET_KEY")
        sandbox_key = secret_values.get("STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY")
        if signing is not None and not signing.startswith("absec_"):
            raise StripeAppValueError(
                "STRIPE_APP_SIGNING_SECRET",
                "Stripe App signing secret must start with absec_",
            )
        if test_key is not None and not test_key.startswith("sk_test_"):
            raise StripeAppValueError(
                "STRIPE_APP_OAUTH_TEST_SECRET_KEY",
                "Stripe test secret key must start with sk_test_",
            )
        if sandbox_key is not None and not sandbox_key.startswith("sk_test_"):
            raise StripeAppValueError(
                "STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY",
                "Stripe managed-sandbox secret key must start with sk_test_",
            )
        if test_key is not None and sandbox_key is not None and test_key == sandbox_key:
            raise StripeAppValueError(
                "STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY",
                "test and managed-sandbox secret keys must be different",
            )
        for field_name, value in (
            (
                "STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL",
                secret_values.get("STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL"),
            ),
            (
                "STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL",
                secret_values.get("STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL"),
            ),
            (
                "DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL",
                live_url,
            ),
        ):
            if value is None:
                continue
            try:
                _https_url(value, field_name)
            except ValueError as exc:
                raise StripeAppValueError(field_name, str(exc)) from exc
        for field_name, value in secret_values.items():
            if not value or len(value) > 4096:
                raise StripeAppValueError(
                    field_name,
                    "value must contain between 1 and 4096 characters",
                )

    def secret_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for name in SECRET_NAMES:
            value = getattr(self, name)
            if value is not None:
                values[name] = value.get_secret_value()
        return values

    def live_authorize_url(self) -> str | None:
        return self.DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL


class ConfigureStripeAppRequest(Strict):
    plan_id: str = Field(min_length=1, max_length=64)
    agent_identity: str = Field(min_length=1, max_length=255)
    idempotency_key: str = Field(min_length=8, max_length=128)
    values: StripeAppProductionValues
    trace_id: str | None = Field(default=None, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def _idempotency(cls, value: str) -> str:
        if not _IDEMPOTENCY_KEY.fullmatch(value):
            raise ValueError(f"idempotency_key must match {_IDEMPOTENCY_KEY.pattern}")
        return value


class StripeAppValueError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


@dataclass(frozen=True)
class GitHubAppConfig:
    client_id: str
    private_key: str
    owner: str
    repository: str
    environment: str = ENVIRONMENT

    @classmethod
    def from_environment(cls) -> "GitHubAppConfig":
        repository = (os.getenv("DSG_GITHUB_REPOSITORY") or "").strip()
        if not _REPOSITORY.fullmatch(repository):
            raise GitHubPermissionError(
                operation="load server configuration",
                missing_permissions=["DSG_GITHUB_REPOSITORY=owner/repository"],
            )
        owner, name = repository.split("/", 1)
        client_id = (os.getenv("GITHUB_APP_CLIENT_ID") or "").strip()
        private_key = (os.getenv("GITHUB_APP_PRIVATE_KEY") or "").strip()
        missing = []
        if not client_id:
            missing.append("GITHUB_APP_CLIENT_ID")
        if not private_key:
            missing.append("GITHUB_APP_PRIVATE_KEY")
        if missing:
            raise GitHubPermissionError(
                operation="load server configuration",
                missing_permissions=missing,
            )
        return cls(
            client_id=client_id,
            private_key=private_key,
            owner=owner,
            repository=name,
        )

    @property
    def full_repository(self) -> str:
        return f"{self.owner}/{self.repository}"


class GitHubPermissionError(RuntimeError):
    def __init__(
        self,
        *,
        operation: str,
        missing_permissions: list[str],
        status_code: int | None = None,
    ) -> None:
        super().__init__(f"GitHub capability is not ready for {operation}")
        self.operation = operation
        self.missing_permissions = missing_permissions
        self.status_code = status_code


class GitHubExecutionError(RuntimeError):
    def __init__(self, *, operation: str, status_code: int | None = None) -> None:
        super().__init__(f"GitHub request failed during {operation}")
        self.operation = operation
        self.status_code = status_code


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def github_app_jwt(config: GitHubAppConfig, *, now: int | None = None) -> str:
    issued_at = int(time.time() if now is None else now) - 60
    header = _base64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _base64url(
        json.dumps(
            {"iat": issued_at, "exp": issued_at + 9 * 60, "iss": config.client_id},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    try:
        private_key = serialization.load_pem_private_key(config.private_key.encode(), password=None)
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    except (TypeError, ValueError) as exc:
        raise GitHubPermissionError(
            operation="sign GitHub App JWT",
            missing_permissions=["valid GITHUB_APP_PRIVATE_KEY"],
        ) from exc
    return f"{header}.{payload}.{_base64url(signature)}"


def encrypt_github_secret(public_key: str, value: str) -> str:
    try:
        key = PublicKey(base64.b64decode(public_key, validate=True))
        encrypted = SealedBox(key).encrypt(value.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise GitHubExecutionError(operation="encrypt environment secret") from exc
    return base64.b64encode(encrypted).decode("ascii")


class GitHubActionsConfigurator:
    """Minimal GitHub REST client scoped to one repository and environment."""

    def __init__(self, config: GitHubAppConfig, *, client: httpx.Client | None = None) -> None:
        self.config = config
        self.client = client or httpx.Client(
            base_url=_GITHUB_API,
            timeout=20.0,
            follow_redirects=False,
        )

    @classmethod
    def from_environment(cls) -> "GitHubActionsConfigurator":
        return cls(GitHubAppConfig.from_environment())

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        operation: str,
        expected: set[int],
        payload: dict[str, Any] | None = None,
        permission_failure: list[str] | None = None,
    ) -> httpx.Response:
        try:
            response = self.client.request(
                method,
                path,
                headers=self._headers(token),
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise GitHubExecutionError(operation=operation) from exc
        if response.status_code in expected:
            return response
        if response.status_code in {401, 403, 404, 422} and permission_failure:
            raise GitHubPermissionError(
                operation=operation,
                missing_permissions=permission_failure,
                status_code=response.status_code,
            )
        raise GitHubExecutionError(operation=operation, status_code=response.status_code)

    def _installation_token(
        self,
        *,
        needs_secrets: bool,
        needs_variable: bool,
    ) -> tuple[str, dict[str, Any]]:
        jwt = github_app_jwt(self.config)
        repo_path = f"/repos/{quote(self.config.owner)}/{quote(self.config.repository)}/installation"
        installation_response = self._request(
            "GET",
            repo_path,
            token=jwt,
            operation="find repository installation",
            expected={200},
            permission_failure=["install the GitHub App on the target repository"],
        )
        installation = installation_response.json()
        permissions = installation.get("permissions") if isinstance(installation, dict) else None
        permissions = permissions if isinstance(permissions, dict) else {}
        missing: list[str] = []
        if needs_secrets and permissions.get("environments") != "write":
            missing.append("GitHub App repository permission: Environments (write)")
        if needs_variable and permissions.get("variables") != "write":
            missing.append("GitHub App repository permission: Variables (write)")
        if missing:
            raise GitHubPermissionError(
                operation="verify GitHub App installation permissions",
                missing_permissions=missing,
            )

        installation_id = installation.get("id")
        if not isinstance(installation_id, int):
            raise GitHubExecutionError(operation="read GitHub App installation id")
        token_response = self._request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            token=jwt,
            operation="create repository installation token",
            expected={201},
            payload={"repositories": [self.config.repository]},
            permission_failure=["GitHub App installation access to the target repository"],
        )
        token_body = token_response.json()
        installation_token = token_body.get("token") if isinstance(token_body, dict) else None
        if not isinstance(installation_token, str) or not installation_token:
            raise GitHubExecutionError(operation="read repository installation token")
        return installation_token, installation

    def configure(self, values: StripeAppProductionValues) -> dict[str, Any]:
        submitted_secrets = values.secret_values()
        submitted_live_url = values.live_authorize_url()
        token, installation = self._installation_token(
            needs_secrets=bool(submitted_secrets),
            needs_variable=submitted_live_url is not None,
        )
        owner = quote(self.config.owner)
        repository = quote(self.config.repository)
        environment = quote(self.config.environment, safe="")
        environment_base = f"/repos/{owner}/{repository}/environments/{environment}/secrets"

        if submitted_secrets:
            public_key_response = self._request(
                "GET",
                environment_base + "/public-key",
                token=token,
                operation="read production environment public key",
                expected={200},
                permission_failure=["GitHub App repository permission: Environments (write)"],
            )
            public_key_body = public_key_response.json()
            key_id = public_key_body.get("key_id") if isinstance(public_key_body, dict) else None
            public_key = public_key_body.get("key") if isinstance(public_key_body, dict) else None
            if not isinstance(key_id, str) or not isinstance(public_key, str):
                raise GitHubExecutionError(operation="read production environment public key")

            for name, secret in submitted_secrets.items():
                self._request(
                    "PUT",
                    environment_base + "/" + quote(name),
                    token=token,
                    operation=f"write environment secret {name}",
                    expected={201, 204},
                    payload={
                        "encrypted_value": encrypt_github_secret(public_key, secret),
                        "key_id": key_id,
                    },
                    permission_failure=["GitHub App repository permission: Environments (write)"],
                )

        variable_path = f"/repos/{owner}/{repository}/actions/variables/{quote(VARIABLE_NAME)}"
        if submitted_live_url is not None:
            variable_response = self._request(
                "GET",
                variable_path,
                token=token,
                operation="read repository variable",
                expected={200, 404},
                permission_failure=["GitHub App repository permission: Variables (write)"],
            )
            if variable_response.status_code == 404:
                self._request(
                    "POST",
                    f"/repos/{owner}/{repository}/actions/variables",
                    token=token,
                    operation="create repository variable",
                    expected={201},
                    payload={"name": VARIABLE_NAME, "value": submitted_live_url},
                    permission_failure=["GitHub App repository permission: Variables (write)"],
                )
            else:
                self._request(
                    "PATCH",
                    variable_path,
                    token=token,
                    operation="update repository variable",
                    expected={204},
                    payload={"name": VARIABLE_NAME, "value": submitted_live_url},
                    permission_failure=["GitHub App repository permission: Variables (write)"],
                )

        secret_evidence: list[dict[str, Any]] = []
        for name in submitted_secrets:
            response = self._request(
                "GET",
                environment_base + "/" + quote(name),
                token=token,
                operation=f"read back environment secret {name}",
                expected={200},
                permission_failure=["GitHub App repository permission: Environments (read)"],
            )
            metadata = response.json()
            secret_evidence.append(
                {
                    "name": metadata.get("name"),
                    "created_at": metadata.get("created_at"),
                    "updated_at": metadata.get("updated_at"),
                    "value_exposed": False,
                }
            )

        variable_evidence: dict[str, Any] | None = None
        if submitted_live_url is not None:
            variable_readback = self._request(
                "GET",
                variable_path,
                token=token,
                operation="read back repository variable",
                expected={200},
                permission_failure=["GitHub App repository permission: Variables (read)"],
            ).json()
            readback_value = (
                variable_readback.get("value")
                if isinstance(variable_readback, dict)
                else None
            )
            if readback_value != submitted_live_url:
                raise GitHubExecutionError(operation="verify repository variable read-back")
            variable_evidence = {
                "name": variable_readback.get("name"),
                "created_at": variable_readback.get("created_at"),
                "updated_at": variable_readback.get("updated_at"),
                "value_matches_submitted": True,
                "value_sha256": sha256(submitted_live_url.encode()).hexdigest(),
            }

        return {
            "source": "github-rest-read-back",
            "repository": self.config.full_repository,
            "environment": self.config.environment,
            "installation": {
                "id": installation.get("id"),
                "app_slug": installation.get("app_slug"),
            },
            "configured_value_names": sorted(
                [*submitted_secrets, *([VARIABLE_NAME] if submitted_live_url is not None else [])]
            ),
            "environment_secrets": secret_evidence,
            "repository_variable": variable_evidence,
            "secret_values_exposed": False,
            "read_back_at": utc_now(),
        }


_configurator_factory: Callable[[], GitHubActionsConfigurator] = (
    GitHubActionsConfigurator.from_environment
)


def _action(*, status: str = "succeeded", started_at: str | None = None) -> ObservedAction:
    return ObservedAction(
        action=ACTION,
        target=TARGET,
        step_id=STEP_ID,
        parameters={},
        status=status,
        started_at=started_at,
        finished_at=utc_now() if started_at else None,
    )


def _waiting(
    *,
    request: ConfigureStripeAppRequest,
    control: dict[str, Any],
    error: GitHubPermissionError,
) -> dict[str, Any]:
    return {
        "decision": "WAITING_PERMISSION",
        "executed": False,
        "action": ACTION,
        "target": TARGET,
        "plan_id": request.plan_id,
        "control": control,
        "capability": {
            "name": CAPABILITY,
            "operation": error.operation,
            "missing": error.missing_permissions,
            "github_status": error.status_code,
        },
        "next_step": (
            "Configure the listed GitHub App inputs or repository permissions, "
            "then retry the same approved plan."
        ),
        "secret_values_exposed": False,
        "evaluated_at": utc_now(),
    }


def execute_configure_stripe_app(
    request: ConfigureStripeAppRequest,
    *,
    api_key: Optional[str],
) -> tuple[int, dict[str, Any]]:
    try:
        request.values.validate_for_execution()
    except StripeAppValueError as exc:
        return 422, {
            "error": "INVALID_STRIPE_APP_VALUE",
            "field": exc.field,
            "message": exc.message,
            "executed": False,
            "secret_values_exposed": False,
        }
    # Bind the request to a real tenant before any GitHub authentication or write.
    tenant_for(api_key)
    started_at = utc_now()
    required = [CapabilityRequirement(capability=CAPABILITY)]
    action = _action()
    control = evaluate_unified_preflight(
        UnifiedPreflightRequest(
            plan_id=request.plan_id,
            agent_identity=request.agent_identity,
            action=action,
            required_capabilities=required,
            channel="api",
            trace_id=request.trace_id,
        )
    )

    if control["decision"] != "ALLOW":
        return 200, {
            "decision": control["decision"],
            "executed": False,
            "action": ACTION,
            "target": TARGET,
            "plan_id": request.plan_id,
            "control": control,
            "next_step": control["next_step"],
            "secret_values_exposed": False,
            "evaluated_at": utc_now(),
        }

    try:
        configurator = _configurator_factory()
        github_evidence = configurator.configure(request.values)
    except GitHubPermissionError as exc:
        return 200, _waiting(request=request, control=control, error=exc)
    except GitHubExecutionError as exc:
        return 502, {
            "decision": "ERROR",
            "executed": False,
            "action": ACTION,
            "target": TARGET,
            "plan_id": request.plan_id,
            "control": control,
            "upstream": {
                "provider": "github",
                "operation": exc.operation,
                "status": exc.status_code,
            },
            "next_step": "Retry the same approved plan after GitHub API connectivity recovers.",
            "secret_values_exposed": False,
            "evaluated_at": utc_now(),
        }

    audit: dict[str, Any]
    try:
        audit_status, audit_body = execute_guarded_mutation(
            GuardedMutationRequest(
                plan_id=request.plan_id,
                agent_identity=request.agent_identity,
                idempotency_key=request.idempotency_key,
                action=_action(status="succeeded", started_at=started_at),
                required_capabilities=required,
                channel="api",
                trace_id=request.trace_id,
                outputs={
                    "repository": github_evidence["repository"],
                    "environment": github_evidence["environment"],
                    "environment_secret_count": len(github_evidence["environment_secrets"]),
                    "repository_variable": (
                        VARIABLE_NAME
                        if github_evidence["repository_variable"] is not None
                        else "not_submitted"
                    ),
                    "github_read_back": "confirmed",
                },
            ),
            api_key=api_key,
        )
        audit = {
            "recorded": bool(audit_body.get("executed")),
            "http_status": audit_status,
            "evidence_id": audit_body.get("evidence_id"),
            "storage": audit_body.get("storage"),
            "integrity": audit_body.get("integrity"),
        }
    except ApiError as exc:
        # GitHub already confirmed the write.  Do not erase that external fact
        # merely because the optional DSG evidence store was unavailable.
        audit = {
            "recorded": False,
            "error": exc.code,
            "next_step": exc.payload().get("remediation", {}).get("next_step"),
        }

    return 200, {
        "decision": "ALLOW",
        "executed": True,
        "action": ACTION,
        "target": TARGET,
        "plan_id": request.plan_id,
        "plan_hash": control["plan_hash"],
        "control": control,
        "evidence": github_evidence,
        "audit": audit,
        "next_step": (
            "Run the production deployment workflow and verify the Stripe Marketplace "
            "status endpoint on the resulting Azure revision."
        ),
        "secret_values_exposed": False,
        "completed_at": utc_now(),
    }


@router.post("/configure-stripe-app")
async def configure_stripe_app(
    request: ConfigureStripeAppRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    status_code, body = execute_configure_stripe_app(
        request,
        api_key=(x_dsg_api_key or "").strip() or None,
    )
    if status_code >= 400:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=status_code, content=body)
    return body


def install(app) -> None:
    app.include_router(router)


__all__ = [
    "ACTION",
    "CAPABILITY",
    "ConfigureStripeAppRequest",
    "GitHubActionsConfigurator",
    "GitHubAppConfig",
    "GitHubExecutionError",
    "GitHubPermissionError",
    "SECRET_NAMES",
    "STEP_ID",
    "StripeAppProductionValues",
    "TARGET",
    "VARIABLE_NAME",
    "encrypt_github_secret",
    "execute_configure_stripe_app",
    "github_app_jwt",
    "install",
    "router",
]
