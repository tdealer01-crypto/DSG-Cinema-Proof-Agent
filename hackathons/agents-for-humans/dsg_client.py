from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_VERIFY_URL = "https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io"
VALID_DECISIONS = {"ALLOW", "REVIEW", "BLOCK"}


class VerificationError(RuntimeError):
    """Raised when DSG does not return a valid verified proof receipt."""


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value)


def validate_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("verified") is not True:
        raise VerificationError("DSG did not return verified=true")
    if payload.get("verification") != "VERIFIED_GLOBAL_OPTIMUM":
        raise VerificationError("DSG did not return VERIFIED_GLOBAL_OPTIMUM")
    if payload.get("decision") not in VALID_DECISIONS:
        raise VerificationError("DSG returned an invalid decision")
    for field in ("proof_hash", "request_hash", "context_hash"):
        if not _is_sha256(payload.get(field)):
            raise VerificationError(f"DSG returned an invalid {field}")
    return payload


def verify_execution(request_payload: dict[str, Any], *, timeout_seconds: float = 15.0) -> dict[str, Any]:
    base_url = os.getenv("DSG_VERIFY_URL", DEFAULT_VERIFY_URL).rstrip("/")
    api_key = os.getenv("DSG_API_KEY", "").strip()

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["X-DSG-API-Key"] = api_key

    body = json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/verify/evaluate",
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise VerificationError(f"DSG verification refused with HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise VerificationError(f"DSG verification unavailable: {exc.reason}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VerificationError("DSG returned non-JSON output") from exc
    if not isinstance(payload, dict):
        raise VerificationError("DSG returned a non-object response")
    return validate_receipt(payload)
