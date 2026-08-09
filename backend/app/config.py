from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def derive_aimo_cinema_token(root_key: str) -> str:
    digest = hmac.new(
        root_key.encode("utf-8"),
        b"dsg-aimo-v1:cinema",
        hashlib.sha256,
    ).hexdigest()
    return f"dsg_aimo_{digest}"


def _api_key() -> str | None:
    service_key = _optional("DSG_API_KEY")
    if service_key:
        return service_key
    root_key = _optional("DSG_AIMO_ROOT_KEY")
    return derive_aimo_cinema_token(root_key) if root_key else None


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    proof_signing_secret: str | None
    audit_db_path: str
    audit_backend: str
    firestore_collection: str
    supabase_url: str | None
    supabase_service_role_key: str | None
    gemini_model: str
    google_cloud_project: str | None
    google_cloud_location: str
    use_vertex_ai: bool
    grafana_mcp_url: str | None
    grafana_cloud_stack_url: str | None
    grafana_mcp_access_token: str | None
    grafana_mcp_audience: str | None


def load_settings() -> Settings:
    return Settings(
        api_key=_api_key(),
        proof_signing_secret=_optional("PROOF_SIGNING_SECRET"),
        audit_db_path=os.getenv("AUDIT_DB_PATH", "./.data/dsg_audit.sqlite3"),
        audit_backend=os.getenv("AUDIT_BACKEND", "sqlite").strip().lower(),
        firestore_collection=os.getenv("FIRESTORE_AUDIT_COLLECTION", "dsg_cinema_audit"),
        supabase_url=_optional("SUPABASE_URL"),
        supabase_service_role_key=_optional("SUPABASE_SERVICE_ROLE_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
        google_cloud_project=_optional("GOOGLE_CLOUD_PROJECT"),
        google_cloud_location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        use_vertex_ai=_bool("GOOGLE_GENAI_USE_VERTEXAI", default=True),
        grafana_mcp_url=_optional("GRAFANA_MCP_URL"),
        grafana_cloud_stack_url=_optional("GRAFANA_CLOUD_STACK_URL"),
        grafana_mcp_access_token=_optional("GRAFANA_MCP_ACCESS_TOKEN"),
        grafana_mcp_audience=_optional("GRAFANA_MCP_AUDIENCE"),
    )
