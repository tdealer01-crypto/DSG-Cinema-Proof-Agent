"""Authenticated relay boundary for managed shared-browser execution.

The managed Browserbase executor is public HTTPS because Cinema relays through
its own public origin. Authentication therefore cannot rely on a bearer secret
inside the URL: request paths are routinely present in reverse-proxy/access
logs. Instead, Cinema signs each canonical remote-action envelope with the
server-side remote-action key and sends the signature only in HTTP headers.

Signatures are timestamped, nonce-bound, body-bound, and replay-protected on the
durable remote-action volume. The browser executor route is mounted only
through this module in production; the implementation module itself remains a
pure executor and testable unit.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException

from . import browserbase_executor, remote_browser

router = APIRouter(tags=["remote-browser"])
SIGNATURE_VERSION = "dsg.managed-relay.v1"
MAX_CLOCK_SKEW_SECONDS = 60


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _signing_key() -> bytes:
    return hmac.new(
        remote_browser._token_secret(),
        b"dsg-managed-browser-relay-signing-key-v1",
        hashlib.sha256,
    ).digest()


def _signature_material(timestamp: str, nonce: str, body_sha256: str) -> bytes:
    return f"{SIGNATURE_VERSION}\n{timestamp}\n{nonce}\n{body_sha256}".encode("utf-8")


def signed_headers_for_payload(payload: dict[str, Any]) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = os.urandom(16).hex()
    body_sha256 = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    signature = hmac.new(
        _signing_key(),
        _signature_material(timestamp, nonce, body_sha256),
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-DSG-Remote-Timestamp": timestamp,
        "X-DSG-Remote-Nonce": nonce,
        "X-DSG-Remote-Body-SHA256": body_sha256,
        "X-DSG-Remote-Signature": signature,
    }


def _nonce_root() -> Path:
    root = browserbase_executor._root() / "relay-nonces"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _consume_nonce(nonce: str, timestamp: int) -> None:
    if len(nonce) != 32:
        raise HTTPException(status_code=401, detail="invalid managed relay nonce")
    try:
        int(nonce, 16)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid managed relay nonce") from exc

    now = int(time.time())
    root = _nonce_root()
    # Bounded opportunistic cleanup. Nonces are not secrets; they only provide
    # one-shot replay semantics inside the accepted clock window.
    cleaned = 0
    for path in root.glob("*.nonce"):
        if cleaned >= 64:
            break
        try:
            if path.stat().st_mtime < now - (MAX_CLOCK_SKEW_SECONDS * 3):
                path.unlink()
                cleaned += 1
        except OSError:
            continue

    digest = hashlib.sha256(nonce.encode("ascii")).hexdigest()
    path = root / f"{digest}.nonce"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "REMOTE_RELAY_REPLAY_BLOCKED", "message": "Managed relay nonce was already consumed."},
        ) from exc
    try:
        os.write(fd, str(timestamp).encode("ascii"))
    finally:
        os.close(fd)


def _verify_signature(
    payload: dict[str, Any],
    *,
    timestamp: Optional[str],
    nonce: Optional[str],
    body_sha256: Optional[str],
    signature: Optional[str],
) -> None:
    if not timestamp or not nonce or not body_sha256 or not signature:
        raise HTTPException(status_code=401, detail="managed relay signature headers are required")
    try:
        timestamp_int = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid managed relay timestamp") from exc
    now = int(time.time())
    if abs(now - timestamp_int) > MAX_CLOCK_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="managed relay signature expired")

    actual_body_sha256 = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    if not hmac.compare_digest(actual_body_sha256, body_sha256):
        raise HTTPException(status_code=401, detail="managed relay body hash mismatch")

    expected = hmac.new(
        _signing_key(),
        _signature_material(timestamp, nonce, body_sha256),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="invalid managed relay signature")

    _consume_nonce(nonce, timestamp_int)


async def _signed_relay(
    endpoint: str,
    payload: dict[str, Any],
) -> tuple[int, str | dict[str, Any], str]:
    chunks: list[bytes] = []
    total = 0
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        **signed_headers_for_payload(payload),
    }
    try:
        async with httpx.AsyncClient(
            timeout=remote_browser.DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            async with client.stream(
                "POST",
                endpoint,
                headers=headers,
                json=payload,
            ) as response:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > remote_browser.MAX_RESPONSE_BYTES:
                        raise HTTPException(
                            status_code=502,
                            detail="remote endpoint response exceeded 1 MiB",
                        )
                    chunks.append(chunk)
                raw = b"".join(chunks)
                response_sha256 = hashlib.sha256(raw).hexdigest()
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    try:
                        body: str | dict[str, Any] = json.loads(raw or b"{}")
                    except ValueError:
                        body = raw.decode("utf-8", errors="replace")
                else:
                    body = raw.decode("utf-8", errors="replace")
                return response.status_code, body, response_sha256
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="remote browser endpoint request failed") from exc


@router.post("/remote-browser/browserbase/action/{capability_id}")
async def authenticated_browserbase_action(
    capability_id: str,
    payload: dict[str, Any],
    x_dsg_remote_timestamp: Optional[str] = Header(default=None, alias="X-DSG-Remote-Timestamp"),
    x_dsg_remote_nonce: Optional[str] = Header(default=None, alias="X-DSG-Remote-Nonce"),
    x_dsg_remote_body_sha256: Optional[str] = Header(default=None, alias="X-DSG-Remote-Body-SHA256"),
    x_dsg_remote_signature: Optional[str] = Header(default=None, alias="X-DSG-Remote-Signature"),
) -> dict[str, Any]:
    _verify_signature(
        payload,
        timestamp=x_dsg_remote_timestamp,
        nonce=x_dsg_remote_nonce,
        body_sha256=x_dsg_remote_body_sha256,
        signature=x_dsg_remote_signature,
    )
    return await browserbase_executor.browserbase_action(capability_id, payload)


@router.get("/remote-browser/browserbase/live-view")
async def authenticated_live_view(
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    return await browserbase_executor.live_view(x_dsg_api_key=x_dsg_api_key)


def install(app) -> None:
    # Install this wrapper exactly once. It signs all relayed remote-action
    # requests. External executors may ignore the extra headers; the managed
    # Browserbase route requires and verifies them.
    if remote_browser._relay is not _signed_relay:
        remote_browser._relay = _signed_relay
    app.include_router(router)


__all__ = [
    "SIGNATURE_VERSION",
    "authenticated_browserbase_action",
    "install",
    "router",
    "signed_headers_for_payload",
]
