"""Durable, privacy-minimized operational memory for Cinema shared browsers.

Browser state (cookies/localStorage) remains in the browser profile store. This
module stores only sanitized operational context: where work happened, what
approved step/action was involved, and provenance needed to retrieve that context
later. Raw form values, credentials, cookies, OTPs and authorization headers are
never accepted as memory payloads.

The store can grow beyond a model's prompt window. Retrieval is deliberately
bounded by ``token_budget`` so 1M+ stored logical-context tokens never imply that
1M tokens are injected into every model request.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from .canonical import canonical_hash, utc_now

SCHEMA_VERSION = 1
DEFAULT_ACTIVE_TOKEN_BUDGET = 32_000
MAX_ACTIVE_TOKEN_BUDGET = 200_000
DEFAULT_MEMORY_TTL_DAYS = 365
_ALLOWED_SOURCES = {
    "USER_OBSERVED",
    "AGENT_OBSERVED",
    "SYSTEM_OBSERVED",
    "AGENT_INFERRED",
    "USER_CONFIRMED",
}
_SENSITIVE_KEYS = {
    "password", "passwd", "otp", "token", "access_token", "refresh_token",
    "authorization", "cookie", "set-cookie", "secret", "api_key", "apikey",
    "card_number", "cardnumber", "cvc", "cvv", "passkey", "captcha",
}
_SECRET_TEXT = re.compile(
    r"(?i)(?:authorization\s*:\s*bearer\s+\S+|bearer\s+[A-Za-z0-9._~+/=-]{20,}|"
    r"(?:password|passwd|otp|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*\S+|"
    r"sk-(?:live|test|proj)-[A-Za-z0-9_-]{12,})"
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dsg_browser_memory_schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dsg_browser_profiles (
    profile_id TEXT PRIMARY KEY,
    account_hash TEXT UNIQUE NOT NULL,
    provider TEXT NOT NULL,
    logical_browser_id TEXT NOT NULL,
    project_id TEXT,
    current_origin TEXT,
    last_url TEXT,
    last_title TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS dsg_browser_memory (
    memory_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES dsg_browser_profiles(profile_id),
    account_hash TEXT NOT NULL,
    project_id TEXT,
    origin TEXT,
    memory_type TEXT NOT NULL,
    memory_key TEXT NOT NULL,
    content_json JSONB NOT NULL,
    content_text TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    importance INTEGER NOT NULL CHECK (importance >= 0 AND importance <= 100),
    token_estimate INTEGER NOT NULL CHECK (token_estimate >= 0),
    memory_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    UNIQUE(profile_id, memory_hash)
);
CREATE INDEX IF NOT EXISTS dsg_browser_memory_scope_idx
    ON dsg_browser_memory (account_hash, project_id, origin, memory_type, updated_at DESC);
CREATE INDEX IF NOT EXISTS dsg_browser_memory_recent_idx
    ON dsg_browser_memory (account_hash, updated_at DESC)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS dsg_browser_memory_fts_idx
    ON dsg_browser_memory USING GIN (to_tsvector('simple', content_text));

CREATE TABLE IF NOT EXISTS dsg_browser_memory_events (
    event_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL REFERENCES dsg_browser_memory(memory_id),
    account_hash TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    plan_id TEXT,
    step_id TEXT,
    source_evidence_hash TEXT,
    event_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS dsg_browser_memory_events_memory_idx
    ON dsg_browser_memory_events (memory_id, created_at DESC);
CREATE INDEX IF NOT EXISTS dsg_browser_memory_events_account_idx
    ON dsg_browser_memory_events (account_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS dsg_browser_memory_summaries (
    summary_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES dsg_browser_profiles(profile_id),
    account_hash TEXT NOT NULL,
    project_id TEXT,
    scope TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    source_memory_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    token_estimate INTEGER NOT NULL CHECK (token_estimate >= 0),
    summary_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE(profile_id, project_id, scope)
);
""".strip()


def database_url() -> Optional[str]:
    value = (
        os.getenv("DSG_BROWSER_MEMORY_DATABASE_URL")
        or os.getenv("DSG_REVENUE_DATABASE_URL")
        or ""
    ).strip()
    return value or None


def configured() -> bool:
    return database_url() is not None


def _connect():
    url = database_url()
    if not url:
        raise RuntimeError("browser memory PostgreSQL is not configured")
    from revenue.postgres import connect

    return connect(url)


def initialize_schema(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", (0x44534742,))
        cursor.execute(SCHEMA_SQL)
        cursor.execute("SELECT COALESCE(MAX(version), 0) FROM dsg_browser_memory_schema_migrations")
        current = int(cursor.fetchone()[0])
        if current > SCHEMA_VERSION:
            raise RuntimeError("browser memory schema is newer than this Cinema runtime")
        cursor.execute(
            "INSERT INTO dsg_browser_memory_schema_migrations (version) VALUES (%s) "
            "ON CONFLICT (version) DO NOTHING",
            (SCHEMA_VERSION,),
        )
    connection.commit()


def _safe_url(raw: str) -> Optional[str]:
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.rstrip(".").lower()
    port = parsed.port
    default = (parsed.scheme.lower() == "https" and port in {None, 443}) or (
        parsed.scheme.lower() == "http" and port in {None, 80}
    )
    netloc = host if default else f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", "", ""))


def _origin(raw: str) -> Optional[str]:
    safe = _safe_url(raw)
    if not safe:
        return None
    parsed = urlsplit(safe)
    return f"{parsed.scheme}://{parsed.netloc}"


def _assert_safe(value: Any, *, path: str = "memory") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS or any(part in normalized for part in ("password", "secret", "cookie")):
                raise ValueError(f"sensitive field is not allowed in browser memory: {path}.{key}")
            _assert_safe(item, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_safe(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and _SECRET_TEXT.search(value):
        raise ValueError(f"secret-like text is not allowed in browser memory: {path}")


def _token_estimate(text: str) -> int:
    # Conservative provider-neutral estimate. Exact tokenizer choice belongs to
    # the model adapter, not durable memory storage.
    return max(1, (len(text.encode("utf-8")) + 3) // 4)


def _expires_at() -> Optional[str]:
    raw = (os.getenv("DSG_BROWSER_MEMORY_TTL_DAYS") or str(DEFAULT_MEMORY_TTL_DAYS)).strip()
    try:
        days = int(raw)
    except ValueError:
        days = DEFAULT_MEMORY_TTL_DAYS
    if days <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(days=min(days, 3650))).isoformat().replace("+00:00", "Z")


def _profile_id(account_hash: str) -> str:
    return f"bp_{account_hash[:40]}"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_observation(
    *,
    account_hash: str,
    provider: str,
    logical_browser_id: str,
    url: str,
    title: str = "",
    source: str,
    actor: str,
    action: str,
    project_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    step_id: Optional[str] = None,
    source_evidence_hash: Optional[str] = None,
    memory_type: str = "navigation",
    importance: int = 50,
) -> Optional[str]:
    """Persist one sanitized observation and provenance event.

    Returns ``None`` when memory storage is intentionally unconfigured. Browser
    execution must not become unavailable merely because optional long-term memory
    is disabled.
    """

    if not configured():
        return None
    if source not in _ALLOWED_SOURCES:
        raise ValueError("unknown browser memory source")
    safe_url = _safe_url(url)
    if not safe_url:
        return None
    clean_title = (title or "").strip()[:500]
    content = {
        "url": safe_url,
        "title": clean_title,
        "action": str(action)[:100],
        "plan_id": str(plan_id)[:100] if plan_id else None,
        "step_id": str(step_id)[:100] if step_id else None,
    }
    _assert_safe(content)
    now = utc_now()
    origin = _origin(safe_url)
    text = " ".join(part for part in (clean_title, safe_url, str(action), str(step_id or "")) if part)
    profile_id = _profile_id(account_hash)
    memory_key = f"{memory_type}:{origin or 'unknown'}:{urlsplit(safe_url).path or '/'}:{action}"
    memory_body = {
        "profile_id": profile_id,
        "project_id": project_id,
        "origin": origin,
        "memory_type": memory_type,
        "memory_key": memory_key,
        "content": content,
        "source": source,
    }
    memory_hash = canonical_hash(memory_body)
    proposed_id = f"bm_{uuid.uuid4().hex}"
    event_id = f"bme_{uuid.uuid4().hex}"
    confidence = 1.0 if source in {"USER_OBSERVED", "SYSTEM_OBSERVED"} else 0.9
    importance = max(0, min(int(importance), 100))

    with _connect() as connection:
        initialize_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO dsg_browser_profiles "
                "(profile_id, account_hash, provider, logical_browser_id, project_id, current_origin, last_url, last_title, created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (account_hash) DO UPDATE SET provider=EXCLUDED.provider, logical_browser_id=EXCLUDED.logical_browser_id, "
                "project_id=COALESCE(EXCLUDED.project_id,dsg_browser_profiles.project_id), current_origin=EXCLUDED.current_origin, "
                "last_url=EXCLUDED.last_url, last_title=EXCLUDED.last_title, updated_at=EXCLUDED.updated_at",
                (profile_id, account_hash, provider, logical_browser_id, project_id, origin, safe_url, clean_title, now, now),
            )
            cursor.execute(
                "INSERT INTO dsg_browser_memory "
                "(memory_id,profile_id,account_hash,project_id,origin,memory_type,memory_key,content_json,content_text,source,confidence,importance,token_estimate,memory_hash,created_at,updated_at,expires_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (profile_id,memory_hash) DO UPDATE SET updated_at=EXCLUDED.updated_at, importance=GREATEST(dsg_browser_memory.importance,EXCLUDED.importance) "
                "RETURNING memory_id",
                (proposed_id, profile_id, account_hash, project_id, origin, memory_type, memory_key, _json(content), text, source, confidence, importance, _token_estimate(text), memory_hash, now, now, _expires_at()),
            )
            memory_id = str(cursor.fetchone()[0])
            event_body = {
                "event_id": event_id,
                "memory_id": memory_id,
                "actor": actor,
                "action": action,
                "plan_id": plan_id,
                "step_id": step_id,
                "source_evidence_hash": source_evidence_hash,
                "created_at": now,
            }
            cursor.execute(
                "INSERT INTO dsg_browser_memory_events "
                "(event_id,memory_id,account_hash,action,actor,plan_id,step_id,source_evidence_hash,event_hash,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (event_id, memory_id, account_hash, str(action)[:100], str(actor)[:100], plan_id, step_id, source_evidence_hash, canonical_hash(event_body), now),
            )
        connection.commit()
    return memory_id


def search_context(
    *,
    account_hash: str,
    query: str = "",
    project_id: Optional[str] = None,
    origin: Optional[str] = None,
    token_budget: int = DEFAULT_ACTIVE_TOKEN_BUDGET,
    limit: int = 100,
) -> dict[str, Any]:
    budget = max(1_000, min(int(token_budget), MAX_ACTIVE_TOKEN_BUDGET))
    row_limit = max(1, min(int(limit), 500))
    if not configured():
        return {
            "available": False,
            "stored_token_estimate": 0,
            "selected_token_estimate": 0,
            "token_budget": budget,
            "memories": [],
        }
    safe_origin = _origin(origin) if origin else None
    with _connect() as connection:
        initialize_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(SUM(token_estimate),0), COUNT(*) FROM dsg_browser_memory "
                "WHERE account_hash=%s AND deleted_at IS NULL AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)",
                (account_hash,),
            )
            stored_tokens, stored_count = cursor.fetchone()
            cursor.execute(
                "SELECT memory_id,project_id,origin,memory_type,memory_key,content_json,source,confidence,importance,token_estimate,memory_hash,updated_at "
                "FROM dsg_browser_memory WHERE account_hash=%s AND deleted_at IS NULL "
                "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) "
                "AND (%s IS NULL OR project_id=%s) AND (%s IS NULL OR origin=%s) "
                "AND (%s='' OR to_tsvector('simple',content_text) @@ plainto_tsquery('simple',%s) OR memory_key ILIKE %s) "
                "ORDER BY importance DESC, updated_at DESC LIMIT %s",
                (account_hash, project_id, project_id, safe_origin, safe_origin, query.strip(), query.strip(), f"%{query.strip()}%", row_limit),
            )
            rows = cursor.fetchall()

    selected: list[dict[str, Any]] = []
    selected_tokens = 0
    for row in rows:
        estimated = int(row[9])
        if selected and selected_tokens + estimated > budget:
            continue
        content = row[5]
        if isinstance(content, str):
            content = json.loads(content)
        selected.append({
            "memory_id": row[0],
            "project_id": row[1],
            "origin": row[2],
            "memory_type": row[3],
            "memory_key": row[4],
            "content": content,
            "source": row[6],
            "confidence": float(row[7]),
            "importance": int(row[8]),
            "token_estimate": estimated,
            "memory_hash": row[10],
            "updated_at": row[11].isoformat() if hasattr(row[11], "isoformat") else str(row[11]),
            "requires_live_verification": row[3] in {"authorization", "payment", "security", "deployment_state"},
        })
        selected_tokens += estimated
        if selected_tokens >= budget:
            break
    return {
        "available": True,
        "logical_context": "unbounded durable memory with bounded active retrieval",
        "stored_memory_count": int(stored_count),
        "stored_token_estimate": int(stored_tokens),
        "selected_token_estimate": selected_tokens,
        "token_budget": budget,
        "memories": selected,
        "truth_boundary": "memory is context, not current authorization or proof; high-impact state must be re-verified live",
    }


__all__ = [
    "DEFAULT_ACTIVE_TOKEN_BUDGET",
    "MAX_ACTIVE_TOKEN_BUDGET",
    "SCHEMA_SQL",
    "configured",
    "database_url",
    "initialize_schema",
    "record_observation",
    "search_context",
]
