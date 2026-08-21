"""Canonical encoding, hashing, and identifier helpers for the DSG ONE v1 API.

Every hash the API publishes is computed here from the *raw* record DSG stored,
never from a value an agent supplied. Canonical JSON is sorted, separator-tight
and ASCII-escaped so an independent implementation can reproduce byte-for-byte.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any

import json

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford base32, lowercase


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical_hash(payload: Any) -> str:
    """SHA-256 over the canonical JSON encoding of `payload`."""
    return sha256_hex(canonical_json(payload))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    """A sortable-enough, collision-resistant public identifier."""
    stamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    body = ""
    for _ in range(10):
        body = _ALPHABET[stamp % 32] + body
        stamp //= 32
    tail = "".join(secrets.choice(_ALPHABET) for _ in range(12))
    return f"{prefix}_{body}{tail}"
