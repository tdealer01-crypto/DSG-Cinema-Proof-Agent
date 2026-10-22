"""Fail-closed, verified Auth0 + DSG site identity link to an EXISTING Cinema Free account.

A Auth0 user is NOT a Cinema account. This route requires:
  1) verified Auth0 RS256 JWT scoped to the existing DSG ONE user SPA;
  2) independently signed, fresh website actor+membership proof;
  3) possession of that exact Cinema Free account's API credential.

No OAuth access tokens, master keys, subject emails or signed proofs are stored.
No new accounts, capabilities, browser sessions, or approvals are created here.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
from fastapi import APIRouter, Header, HTTPException, Request

from revenue import api as billing
from . import service

router = APIRouter(prefix="/remote-browser/oauth", tags=["oauth-cinema-account"])
AUTH0_ISSUER = "https://dev-kcddqmnusbxxo25s.us.auth0.com/"
AUTH0_AUDIENCE = "https://aws.dsg.pics"
AUTH0_USER_CLIENT = "mLIAcMEAhuVDaUvzXn8Qo54zj2llFp3X"
SITE_ISSUER = "urn:dsg:one:verified-site-actor"
SITE_AUDIENCE = "urn:dsg:cinema:free-account-link"
SITE_ROUTE = "cinema.account.link"
JWKS_URL = AUTH0_ISSUER + ".well-known/jwks.json"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{12,7000}\.[A-Za-z0-9_-]{12,7000}\.[A-Za-z0-9_-]{12,7000}$")


def _deny(code: str, status: int = 401) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": code})


def _parse_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    if not isinstance(token, str) or len(token) > 15000 or not TOKEN_RE.fullmatch(token):
        raise _deny("OAUTH_JWT_INVALID")
    first, second, third = token.split(".")

    def strict_json(value: str) -> dict[str, Any]:
        try:
            raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
            # Duplicate JSON claims/headers may not silently replace trusted values.
            def unique(pairs):
                result = {}
                for key, item in pairs:
                    if key in result:
                        raise ValueError("duplicate key")
                    result[key] = item
                return result
            obj = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
            if not isinstance(obj, dict):
                raise ValueError("not an object")
            return obj
        except Exception:
            raise _deny("OAUTH_JWT_INVALID")
    header, claims = strict_json(first), strict_json(second)
    try:
        signature = base64.urlsafe_b64decode(third + "=" * (-len(third) % 4))
    except Exception:
        raise _deny("OAUTH_JWT_INVALID")
    if any(k in header for k in ("jwk", "jku", "x5u", "crit")):
        raise _deny("OAUTH_JWT_UNTRUSTED_HEADER")
    return header, claims, (first + "." + second).encode("ascii"), signature


def _check_times(claims: dict[str, Any], max_age: int) -> None:
    now = int(time.time())
    iat, exp = claims.get("iat"), claims.get("exp")
    nbf = claims.get("nbf", iat)
    if any(type(x) is not int for x in (iat, exp, nbf)):
        raise _deny("OAUTH_JWT_TIMES_INVALID")
    if not (now - max_age <= iat <= now + 5 and iat <= nbf <= now + 5
            and nbf < exp and now < exp <= iat + max_age):
        raise _deny("OAUTH_JWT_EXPIRED_OR_STALE")


async def _fetch_issuer_jwks() -> dict[str, Any]:
    """Fetch ONLY the fixed Auth0 issuer JWKS; no redirects or untrusted jku."""
    async with httpx.AsyncClient(timeout=4.0, follow_redirects=False, trust_env=False) as client:
        response = await client.get(JWKS_URL)
        response.raise_for_status()
        if len(response.content) > 100_000:
            raise ValueError("JWKS oversized")
        return response.json()


async def _auth0_subject(bearer: str) -> str:
    token = bearer.removeprefix("Bearer ").strip() if bearer.startswith("Bearer ") else ""
    header, claims, signed, signature = _parse_jwt(token)
    kid = header.get("kid")
    if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid or len(kid) > 150:
        raise _deny("OAUTH_ALGORITHM_OR_KID_DENIED")
    try:
        jwks = await _fetch_issuer_jwks()
        keys = [k for k in jwks["keys"]
                if isinstance(k, dict) and k.get("kid") == kid
                and k.get("kty") == "RSA" and k.get("use", "sig") == "sig"
                and k.get("alg", "RS256") == "RS256"]
        if len(keys) != 1:
            raise ValueError("no unique pinned issuer key")
        key = keys[0]
        def integer(value: Any) -> int:
            if not isinstance(value, str) or len(value) > 2048:
                raise ValueError("invalid JWK exponent/modulus")
            return int.from_bytes(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)), "big")
        exponent, modulus = integer(key["e"]), integer(key["n"])
        if exponent < 3 or modulus.bit_length() < 2048:
            raise ValueError("weak RSA key")
        public = rsa.RSAPublicNumbers(exponent, modulus).public_key()
        public.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    except HTTPException:
        raise
    except Exception:
        raise _deny("AUTH0_SIGNATURE_NOT_VERIFIED")
    if (claims.get("iss") != AUTH0_ISSUER or claims.get("aud") != AUTH0_AUDIENCE
            or claims.get("azp") != AUTH0_USER_CLIENT):
        raise _deny("AUTH0_ISSUER_AUDIENCE_CLIENT_DENIED", 403)
    if "dsg.use" not in str(claims.get("scope") or "").split():
        raise _deny("AUTH0_USER_SCOPE_REQUIRED", 403)
    _check_times(claims, 86400)
    subject = claims.get("sub")
    if not isinstance(subject, str) or not 1 <= len(subject) <= 256:
        raise _deny("AUTH0_SUBJECT_INVALID")
    return subject


def _site_actor(assertion: str, subject: str) -> dict[str, Any]:
    raw_key = os.getenv("DSG_CINEMA_SITE_ASSERTION_PUBLIC_KEY_B64", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9+/]{43}=", raw_key):
        raise _deny("SITE_ASSERTION_PUBLIC_KEY_NOT_CONFIGURED", 503)
    try:
        public_bytes = base64.b64decode(raw_key, validate=True)
        if len(public_bytes) != 32:
            raise ValueError("bad Ed25519 key length")
        header, payload, signed, signature = _parse_jwt(assertion)
        if header.get("alg") != "EdDSA":
            raise ValueError("wrong signature algorithm")
        ed25519.Ed25519PublicKey.from_public_bytes(public_bytes).verify(signature, signed)
    except HTTPException:
        raise
    except Exception:
        raise _deny("SITE_IDENTITY_ASSERTION_INVALID")
    if (payload.get("iss") != SITE_ISSUER or payload.get("aud") != SITE_AUDIENCE
            or payload.get("route_id") != SITE_ROUTE or payload.get("sub") != subject
            or payload.get("auth0_iss") != AUTH0_ISSUER
            or payload.get("auth0_client_id") != AUTH0_USER_CLIENT):
        raise _deny("SITE_IDENTITY_CONTEXT_MISMATCH", 403)
    _check_times(payload, 60)
    if payload.get("membership_verified") is not True or payload.get("role") not in ("OWNER", "ADMIN", "OPERATOR"):
        raise _deny("SITE_WORKSPACE_CONTROL_PERMISSION_REQUIRED", 403)
    actor, workspace, jti = payload.get("actor_id"), payload.get("workspace_id"), payload.get("jti")
    if not (isinstance(actor, str) and re.fullmatch(r"[a-zA-Z0-9_-]{8,128}", actor)
            and isinstance(workspace, str) and re.fullmatch(
                r"[a-zA-Z0-9_-]{8,128}|[0-9a-fA-F-]{36}", workspace)
            and isinstance(jti, str) and re.fullmatch(r"[A-Za-z0-9_-]{16,128}", jti)):
        raise _deny("SITE_ACTOR_WORKSPACE_OR_NONCE_INVALID", 403)
    return payload


def _store_path() -> Path:
    value = os.getenv("DSG_CINEMA_OAUTH_LINK_STORE", "/revenue/auth0-cinema-free-links.json")
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.parent.is_dir():
        raise _deny("OAUTH_LINK_DURABLE_STORE_UNAVAILABLE", 503)
    return path


@contextmanager
def _locked_store() -> Iterator[tuple[Path, dict[str, Any]]]:
    path = _store_path()
    lock = path.with_suffix(path.suffix + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"links": {}, "receipts": {}}
                if not isinstance(state, dict) or not isinstance(state.get("links"), dict) or not isinstance(state.get("receipts"), dict):
                    raise ValueError("invalid durable link state")
                yield path, state
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
    except HTTPException:
        raise
    except Exception:
        raise _deny("OAUTH_LINK_DURABLE_STORE_UNAVAILABLE", 503)


def _commit(path: Path, state: dict[str, Any]) -> None:
    fd = None
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".cinema-oauth-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            fd = None
            json.dump(state, out, sort_keys=True, separators=(",", ":"))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        temporary = None
        dirfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except Exception:
        raise _deny("OAUTH_LINK_DURABLE_COMMIT_FAILED", 503)
    finally:
        if fd is not None:
            os.close(fd)
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def _subject_digest(subject: str) -> str:
    return hashlib.sha256((AUTH0_ISSUER + "\0" + subject).encode()).hexdigest()


def _bind(subject: str, actor: dict[str, Any], account_id: str) -> dict[str, Any]:
    key = _subject_digest(subject)
    receipt = hashlib.sha256((SITE_ISSUER + "\0" + actor["jti"]).encode()).hexdigest()
    now = int(time.time())
    with _locked_store() as (path, data):
        links, receipts = data["links"], data["receipts"]
        data["receipts"] = {k: t for k, t in receipts.items()
                            if type(t) is int and t > now}
        if receipt in data["receipts"]:
            raise _deny("OAUTH_LINK_ASSERTION_REPLAYED", 409)
        owner = links.get(key)
        for digest, existing in links.items():
            if digest != key and isinstance(existing, dict) and existing.get("account_id") == account_id:
                raise _deny("CINEMA_ACCOUNT_ALREADY_BOUND_TO_ANOTHER_USER", 409)
        link = {"account_id": account_id, "actor_id": actor["actor_id"],
                "workspace_id": actor["workspace_id"], "subject_sha256": key}
        if owner is not None and owner != link:
            raise _deny("AUTH0_USER_ALREADY_BOUND_TO_DIFFERENT_CINEMA_ACCOUNT", 409)
        links[key] = link
        data["receipts"][receipt] = int(actor["exp"])
        _commit(path, data)
    return link


async def _authorized_subject(
    authorization: str | None, assertion: str | None
) -> tuple[str, dict[str, Any]]:
    sub = await _auth0_subject(authorization or "")
    return sub, _site_actor(assertion or "", sub)


def _origin(request: Request) -> None:
    # Requests originate only from the two first-party DSG web surfaces.
    # Browser-side credentialed cookies do NOT authorize this route.
    if request.headers.get("origin") not in {"https://aws.dsg.pics", "https://dsg.pics"}:
        raise _deny("OAUTH_LINK_ORIGIN_DENIED", 403)


@router.post("/link")
async def link_existing_free_account(
    request: Request,
    authorization: str | None = Header(default=None),
    x_dsg_site_assertion: str | None = Header(default=None, alias="X-DSG-Site-Assertion"),
    x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    """Account migration, NOT agent pairing. No implicit new account or permissions."""
    _origin(request)
    subject, actor = await _authorized_subject(authorization, x_dsg_site_assertion)
    if not x_dsg_api_key:
        raise _deny("CINEMA_ACCOUNT_POSSESSION_PROOF_REQUIRED", 401)
    auth = billing.authorize_request(x_dsg_api_key, service.VERIFIED_EXECUTION_SKU)
    account = auth.account if auth else None
    if not account or account.plan != "free" or account.mode != "live" or account.status != "active":
        raise _deny("EXISTING_ACTIVE_FREE_CINEMA_ACCOUNT_REQUIRED", 403)
    link = _bind(subject, actor, account.account_id)
    return {"ok": True, "linked": True, "account": account.public_view(),
            "workspace_bound": bool(link["workspace_id"]),
            "agent_paired": False, "shared_browser_active": False,
            "no_production_key_exported": True}


@router.get("/status")
async def linked_account_status(
    authorization: str | None = Header(default=None),
    x_dsg_site_assertion: str | None = Header(default=None, alias="X-DSG-Site-Assertion"),
) -> dict[str, Any]:
    subject, actor = await _authorized_subject(authorization, x_dsg_site_assertion)
    key = _subject_digest(subject)
    with _locked_store() as (_, data):
        link = data["links"].get(key)
    if not isinstance(link, dict) or (link.get("actor_id") != actor["actor_id"] or
                                      link.get("workspace_id") != actor["workspace_id"]):
        raise _deny("CINEMA_FREE_ACCOUNT_NOT_LINKED", 403)
    authorized = billing.authorize_account(link["account_id"], service.VERIFIED_EXECUTION_SKU)
    account = authorized.account
    if account is None or account.plan != "free" or account.mode != "live":
        raise _deny("CINEMA_FREE_ENTITLEMENT_NOT_ACTIVE", 403)
    return {"ok": True, "linked": True, "account": account.public_view(),
            "agent_paired": False, "shared_browser_active": False}


def install(app) -> None:
    app.include_router(router)
