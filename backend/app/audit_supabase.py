from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .audit import canonical_json
from .models import AuditChainProof


class SupabaseAuditStore:
    """Tamper-evident audit chain backed by service-role-only Supabase RPCs.

    The database transaction owns the chain head lock so concurrent backend instances
    cannot independently advance the same head. The service-role key must remain on the
    server and must never be shipped to Android or browser clients.
    """

    def __init__(self, base_url: str | None, service_role_key: str | None):
        if not base_url:
            raise RuntimeError("SUPABASE_URL is required when AUDIT_BACKEND=supabase")
        if not service_role_key:
            raise RuntimeError(
                "SUPABASE_SERVICE_ROLE_KEY is required when AUDIT_BACKEND=supabase"
            )
        self.base_url = base_url.rstrip("/")
        self.service_role_key = service_role_key

    def _rpc(self, function_name: str, payload: dict[str, Any]) -> Any:
        request = Request(
            f"{self.base_url}/rest/v1/rpc/{function_name}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "apikey": self.service_role_key,
                "Authorization": f"Bearer {self.service_role_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Supabase RPC {function_name} failed with HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"Supabase RPC {function_name} is unreachable: {exc.reason}") from exc

        if not body:
            return None
        return json.loads(body)

    def initialize(self) -> None:
        # A read-only RPC proves that the configured project, key, and migration are usable.
        self._rpc("dsg_get_audit_event", {"p_event_hash": "0" * 64})

    def append(self, payload: dict[str, Any], proof_hash: str) -> AuditChainProof:
        result = self._rpc(
            "dsg_append_audit_event",
            {
                "p_proof_hash": proof_hash,
                "p_payload_json": canonical_json(payload),
            },
        )
        if not isinstance(result, dict):
            raise RuntimeError("Supabase dsg_append_audit_event returned an invalid response")
        return AuditChainProof(
            sequence=int(result["sequence"]),
            previous_hash=str(result["previous_hash"]),
            event_hash=str(result["event_hash"]),
        )

    def get(self, event_hash: str) -> dict[str, Any] | None:
        result = self._rpc("dsg_get_audit_event", {"p_event_hash": event_hash})
        return result if isinstance(result, dict) else None
