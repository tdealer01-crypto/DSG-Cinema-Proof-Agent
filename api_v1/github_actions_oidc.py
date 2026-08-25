"""GitHub Actions OIDC verification for private-lane evidence intake.

The verifier authenticates the workflow identity without requiring Cinema or the
Control Plane to hold a PAT for the private repository. It validates the GitHub
OIDC signature and pins issuer, audience, repository id/name, visibility, ref,
and workflow path. Caller-provided ``sub`` is never used as the sole trust
boundary because GitHub can use immutable subject formats.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import BaseModel, ConfigDict

GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
GITHUB_OIDC_DISCOVERY = f"{GITHUB_OIDC_ISSUER}/.well-known/openid-configuration"
AGENTIC_IMPROVEMENT_AUDIENCE = "dsg-cinema:agentic-improvement"


class OidcVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class GitHubOidcTrustPolicy:
    audience: str = AGENTIC_IMPROVEMENT_AUDIENCE
    repository: str = "tdealer01-crypto/dsg-agi-simulation"
    repository_id: str = "1263153975"
    repository_visibility: str = "private"
    workflow_path: str = ".github/workflows/governed-self-evolution.yml"
    allowed_refs: tuple[str, ...] = (
        "refs/heads/master",
        "refs/heads/feat/governed-candidate-envelope",
    )
    issuer: str = GITHUB_OIDC_ISSUER
    clock_skew_seconds: int = 60
    max_token_age_seconds: int = 900


class GitHubActionsIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str
    repositoryId: str
    repositoryVisibility: str
    ref: str
    sha: str
    workflowRef: str
    runId: str
    runAttempt: str
    eventName: str
    actor: str | None = None


def _b64url_decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:  # pragma: no cover - normalized to stable error
        raise OidcVerificationError("OIDC_BASE64_INVALID") from exc


def _json_segment(value: str, code: str) -> dict[str, Any]:
    try:
        parsed = json.loads(_b64url_decode(value))
    except (UnicodeDecodeError, json.JSONDecodeError, OidcVerificationError) as exc:
        raise OidcVerificationError(code) from exc
    if not isinstance(parsed, dict):
        raise OidcVerificationError(code)
    return parsed


def _audience_matches(claim: Any, expected: str) -> bool:
    if isinstance(claim, str):
        return claim == expected
    if isinstance(claim, list):
        return expected in claim
    return False


def _numeric_claim(claims: dict[str, Any], name: str) -> float:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OidcVerificationError(f"OIDC_{name.upper()}_INVALID")
    return float(value)


def _rsa_public_key(jwk: dict[str, Any]):
    if jwk.get("kty") != "RSA":
        raise OidcVerificationError("OIDC_JWK_KTY_INVALID")
    try:
        modulus = int.from_bytes(_b64url_decode(str(jwk["n"])), "big")
        exponent = int.from_bytes(_b64url_decode(str(jwk["e"])), "big")
        return rsa.RSAPublicNumbers(exponent, modulus).public_key()
    except (KeyError, ValueError, TypeError) as exc:
        raise OidcVerificationError("OIDC_JWK_INVALID") from exc


def verify_github_actions_oidc(
    token: str,
    jwks: dict[str, Any],
    *,
    policy: GitHubOidcTrustPolicy = GitHubOidcTrustPolicy(),
    now: float | None = None,
) -> GitHubActionsIdentity:
    parts = token.split(".")
    if len(parts) != 3:
        raise OidcVerificationError("OIDC_JWT_FORMAT_INVALID")

    header = _json_segment(parts[0], "OIDC_HEADER_INVALID")
    claims = _json_segment(parts[1], "OIDC_CLAIMS_INVALID")
    if header.get("alg") != "RS256" or header.get("typ") not in {None, "JWT"}:
        raise OidcVerificationError("OIDC_ALGORITHM_INVALID")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise OidcVerificationError("OIDC_KID_MISSING")

    keys = jwks.get("keys")
    if not isinstance(keys, list):
        raise OidcVerificationError("OIDC_JWKS_INVALID")
    jwk = next((item for item in keys if isinstance(item, dict) and item.get("kid") == kid), None)
    if jwk is None:
        raise OidcVerificationError("OIDC_KID_UNKNOWN")
    if jwk.get("alg") not in {None, "RS256"}:
        raise OidcVerificationError("OIDC_JWK_ALGORITHM_INVALID")

    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    signature = _b64url_decode(parts[2])
    try:
        _rsa_public_key(jwk).verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as exc:
        raise OidcVerificationError("OIDC_SIGNATURE_INVALID") from exc

    current = time.time() if now is None else now
    skew = policy.clock_skew_seconds
    exp = _numeric_claim(claims, "exp")
    iat = _numeric_claim(claims, "iat")
    nbf = _numeric_claim(claims, "nbf")
    if current > exp + skew:
        raise OidcVerificationError("OIDC_TOKEN_EXPIRED")
    if current + skew < nbf:
        raise OidcVerificationError("OIDC_TOKEN_NOT_YET_VALID")
    if iat > current + skew:
        raise OidcVerificationError("OIDC_IAT_IN_FUTURE")
    if current - iat > policy.max_token_age_seconds + skew:
        raise OidcVerificationError("OIDC_TOKEN_TOO_OLD")

    if claims.get("iss") != policy.issuer:
        raise OidcVerificationError("OIDC_ISSUER_MISMATCH")
    if not _audience_matches(claims.get("aud"), policy.audience):
        raise OidcVerificationError("OIDC_AUDIENCE_MISMATCH")
    if claims.get("repository") != policy.repository:
        raise OidcVerificationError("OIDC_REPOSITORY_MISMATCH")
    if str(claims.get("repository_id", "")) != policy.repository_id:
        raise OidcVerificationError("OIDC_REPOSITORY_ID_MISMATCH")
    if claims.get("repository_visibility") != policy.repository_visibility:
        raise OidcVerificationError("OIDC_REPOSITORY_VISIBILITY_MISMATCH")

    ref = claims.get("ref")
    if not isinstance(ref, str) or ref not in policy.allowed_refs:
        raise OidcVerificationError("OIDC_REF_NOT_ALLOWED")
    expected_workflow_ref = f"{policy.repository}/{policy.workflow_path}@{ref}"
    workflow_ref = claims.get("workflow_ref")
    if workflow_ref != expected_workflow_ref:
        raise OidcVerificationError("OIDC_WORKFLOW_REF_MISMATCH")

    required_string_claims = ("sha", "run_id", "run_attempt", "event_name")
    for name in required_string_claims:
        value = claims.get(name)
        if value is None or not str(value).strip():
            raise OidcVerificationError(f"OIDC_{name.upper()}_MISSING")

    actor = claims.get("actor")
    return GitHubActionsIdentity(
        repository=policy.repository,
        repositoryId=policy.repository_id,
        repositoryVisibility=policy.repository_visibility,
        ref=ref,
        sha=str(claims["sha"]),
        workflowRef=expected_workflow_ref,
        runId=str(claims["run_id"]),
        runAttempt=str(claims["run_attempt"]),
        eventName=str(claims["event_name"]),
        actor=str(actor) if actor is not None else None,
    )


async def fetch_github_actions_jwks() -> dict[str, Any]:
    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        discovery_response = await client.get(GITHUB_OIDC_DISCOVERY, headers={"Accept": "application/json"})
        discovery_response.raise_for_status()
        discovery = discovery_response.json()
        if not isinstance(discovery, dict) or discovery.get("issuer") != GITHUB_OIDC_ISSUER:
            raise OidcVerificationError("OIDC_DISCOVERY_ISSUER_INVALID")
        jwks_uri = discovery.get("jwks_uri")
        if not isinstance(jwks_uri, str):
            raise OidcVerificationError("OIDC_DISCOVERY_JWKS_URI_MISSING")
        parsed = urlparse(jwks_uri)
        if parsed.scheme != "https" or parsed.hostname != "token.actions.githubusercontent.com":
            raise OidcVerificationError("OIDC_DISCOVERY_JWKS_URI_UNTRUSTED")
        jwks_response = await client.get(jwks_uri, headers={"Accept": "application/json"})
        jwks_response.raise_for_status()
        jwks = jwks_response.json()
        if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
            raise OidcVerificationError("OIDC_JWKS_INVALID")
        return jwks
