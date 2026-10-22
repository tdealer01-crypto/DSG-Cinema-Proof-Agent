"""Security regressions for an owner-bound, existing Free Cinema account.

All identity credentials in these tests are locally generated; no real user
token, account key or live OAuth session is required or serialized.
"""
import base64
import json
import secrets
import time
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
from fastapi import HTTPException
from starlette.requests import Request

from api_v1 import oauth_cinema_link as link


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def signed(header, claims, private, algorithm):
    segments = [b64(json.dumps(obj, separators=(",", ":"), sort_keys=True).encode())
                for obj in (header, claims)]
    signing_input = ".".join(segments).encode("ascii")
    if algorithm == "RS256":
        sig = private.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    else:
        sig = private.sign(signing_input)
    return signing_input.decode() + "." + b64(sig)


@pytest.fixture
def actors(monkeypatch, tmp_path):
    now = int(time.time())
    rsa_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_pub = rsa_priv.public_key().public_numbers()
    ed_priv = ed25519.Ed25519PrivateKey.generate()
    ed_pub = ed_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    monkeypatch.setenv("DSG_CINEMA_SITE_ASSERTION_PUBLIC_KEY_B64",
                       base64.b64encode(ed_pub).decode())
    monkeypatch.setenv("DSG_CINEMA_OAUTH_LINK_STORE",
                       str(tmp_path / "auth0-links.json"))
    monkeypatch.setattr(link, "_fetch_issuer_jwks", async_jwks({
        "keys": [{
            "kty": "RSA", "alg": "RS256", "use": "sig", "kid": "test-issuer-key",
            "e": b64(rsa_pub.e.to_bytes((rsa_pub.e.bit_length()+7)//8, "big")),
            "n": b64(rsa_pub.n.to_bytes((rsa_pub.n.bit_length()+7)//8, "big")),
        }]
    }))

    def auth(sub="google-oauth2|12345678901", **overrides):
        claims = {"iss": link.AUTH0_ISSUER, "aud": link.AUTH0_AUDIENCE,
                  "azp": link.AUTH0_USER_CLIENT, "sub": sub, "iat": now,
                  "exp": now+120, "scope": "openid dsg.use"}
        claims.update(overrides)
        return signed({"alg": "RS256", "kid": "test-issuer-key"}, claims, rsa_priv, "RS256")

    def site(sub="google-oauth2|12345678901", **overrides):
        claims = {"iss": link.SITE_ISSUER, "aud": link.SITE_AUDIENCE,
                  "route_id": link.SITE_ROUTE, "sub": sub,
                  "auth0_iss": link.AUTH0_ISSUER,
                  "auth0_client_id": link.AUTH0_USER_CLIENT,
                  "actor_id": "actor_0123456789", "workspace_id": "workspace_01234567",
                  "membership_verified": True, "role": "OWNER",
                  "jti": secrets.token_urlsafe(24), "iat": now,
                  "nbf": now, "exp": now+35}
        claims.update(overrides)
        return signed({"alg": "EdDSA"}, claims, ed_priv, "EdDSA")
    return auth, site


def async_jwks(value):
    async def getter():
        return value
    return getter


@pytest.mark.asyncio
async def test_only_trusted_auth0_rs256_jwks_user_scope(actors):
    auth, site = actors
    sub = await link._auth0_subject("Bearer " + auth())
    assert sub == "google-oauth2|12345678901"
    assert link._site_actor(site(), sub)["actor_id"] == "actor_0123456789"


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    {"aud": "https://evil.example"},
    {"iss": "https://evil.example/"},
    {"azp": "jI1uiKcQu7mqORsaCrogKTQVsAcZuQSt"},  # approver is not user client
    {"scope": "openid profile"},
    {"exp": 1},
    {"iat": 1, "exp": 11},
    {"sub": ""},
])
async def test_invalid_jwt_never_identifies_user(actors, overrides):
    auth, _ = actors
    with pytest.raises(HTTPException):
        await link._auth0_subject("Bearer " + auth(**overrides))


@pytest.mark.asyncio
async def test_jwt_none_untrusted_header_and_tamper_block(actors):
    auth, _ = actors
    token = auth()
    with pytest.raises(HTTPException):
        await link._auth0_subject(token)
    parts = token.split(".")
    parts[1] = b64(b'{"sub":"changed"}')
    with pytest.raises(HTTPException):
        await link._auth0_subject("Bearer " + ".".join(parts))


@pytest.mark.parametrize("changes", [
    {"sub": "google-oauth2|wrong"},
    {"aud": "urn:other"},
    {"route_id": "cinema.admin.grant"},
    {"exp": 1},
    {"actor_id": "../../bad"},
    {"workspace_id": "a"},
    {"auth0_client_id": "approver"},
    {"membership_verified": False},
    {"role": "VIEWER"},
])
def test_mismatched_website_actor_or_membership_assertion_blocks(actors, changes):
    _, site = actors
    with pytest.raises(HTTPException):
        link._site_actor(site(**changes), "google-oauth2|12345678901")


def test_missing_site_public_key_fails_closed(actors, monkeypatch):
    _, site = actors
    monkeypatch.delenv("DSG_CINEMA_SITE_ASSERTION_PUBLIC_KEY_B64")
    with pytest.raises(HTTPException) as error:
        link._site_actor(site(), "google-oauth2|12345678901")
    assert error.value.status_code == 503


def test_binding_unique_per_user_and_per_free_account_and_replay(actors):
    _, site = actors
    first = link._site_actor(site(), "google-oauth2|12345678901")
    binding = link._bind("google-oauth2|12345678901", first, "acct_dsg_a1b2c3d4")
    assert binding["account_id"] == "acct_dsg_a1b2c3d4"
    assert "google-oauth2|12345678901" not in json.dumps(binding)
    with pytest.raises(HTTPException) as replay:
        link._bind("google-oauth2|12345678901", first, "acct_dsg_a1b2c3d4")
    assert replay.value.status_code == 409
    second = link._site_actor(site(), "google-oauth2|12345678901")
    assert link._bind("google-oauth2|12345678901", second, "acct_dsg_a1b2c3d4") == binding
    with pytest.raises(HTTPException) as substitution:
        link._bind("google-oauth2|12345678901",
                   link._site_actor(site(), "google-oauth2|12345678901"),
                   "acct_dsg_ffffffff")
    assert substitution.value.status_code == 409
    with pytest.raises(HTTPException) as takeover:
        link._bind("google-oauth2|other",
                   link._site_actor(site(sub="google-oauth2|other"), "google-oauth2|other"),
                   "acct_dsg_a1b2c3d4")
    assert takeover.value.status_code == 409


@pytest.mark.asyncio
async def test_old_free_key_must_be_proven_and_never_returned(actors, monkeypatch):
    auth, site = actors
    account = SimpleNamespace(
        account_id="acct_dsg_test0001", plan="free", mode="live", status="active",
        public_view=lambda: {"account_id": "acct_dsg_test0001", "plan": "free"},
    )
    monkeypatch.setattr(link.billing, "authorize_request",
                        lambda presented, sku: SimpleNamespace(account=account) if presented == "verified-existing-key" else None)
    req = Request({"type": "http", "method": "POST",
                   "headers": [(b"origin", b"https://aws.dsg.pics")]})
    with pytest.raises(HTTPException) as missing:
        await link.link_existing_free_account(req, authorization="Bearer "+auth(),
                                              x_dsg_site_assertion=site(), x_dsg_api_key=None)
    assert missing.value.status_code == 401
    accepted = await link.link_existing_free_account(
        req, authorization="Bearer "+auth(), x_dsg_site_assertion=site(),
        x_dsg_api_key="verified-existing-key",
    )
    assert accepted["linked"] and accepted["agent_paired"] is False
    assert "verified-existing-key" not in json.dumps(accepted)
    unauthorized = Request({"type": "http", "method": "POST",
                            "headers": [(b"origin", b"https://evil.example")]})
    with pytest.raises(HTTPException):
        await link.link_existing_free_account(
            unauthorized, authorization="Bearer "+auth(),
            x_dsg_site_assertion=site(), x_dsg_api_key="verified-existing-key",
        )
