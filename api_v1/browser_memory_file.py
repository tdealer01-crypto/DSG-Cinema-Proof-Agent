"""Azure Files backend for Browser Operational Memory.

The production Cinema container already mounts /revenue on Azure Files. This
backend reuses that durable mount instead of requiring a new paid database.
Each deduplicated memory and each provenance event is an individual atomic JSON
record, avoiding SQLite/network-filesystem locking semantics.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from . import browser_memory as schema
from .canonical import canonical_hash, utc_now


def root() -> Path:
    explicit = (os.getenv("DSG_BROWSER_MEMORY_STORE") or "").strip()
    if explicit:
        return Path(explicit)
    remote = (os.getenv("DSG_REMOTE_ACTION_STORE") or "").strip()
    if remote:
        return Path(remote) / "browser-memory"
    return Path("/revenue/remote-action/browser-memory")


def _ensure_root() -> Path:
    value = root()
    value.mkdir(parents=True, exist_ok=True)
    return value


def _account_dir(kind: str, account_hash: str) -> Path:
    path = _ensure_root() / kind / account_hash
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temp, path)


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _expired(raw: Any) -> bool:
    if not isinstance(raw, str) or not raw:
        return False
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed <= datetime.now(timezone.utc)


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
    if source not in schema._ALLOWED_SOURCES:
        raise ValueError("unknown browser memory source")
    safe_url = schema._safe_url(url)
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
    schema._assert_safe(content)
    origin = schema._origin(safe_url)
    now = utc_now()
    profile_id = schema._profile_id(account_hash)
    memory_key = f"{memory_type}:{origin or 'unknown'}:{urlsplit(safe_url).path or '/'}:{action}"
    body_for_hash = {
        "profile_id": profile_id,
        "project_id": project_id,
        "origin": origin,
        "memory_type": memory_type,
        "memory_key": memory_key,
        "content": content,
        "source": source,
    }
    memory_hash = canonical_hash(body_for_hash)
    memory_id = f"bmf_{memory_hash[:32]}"
    text = " ".join(
        part for part in (clean_title, safe_url, str(action), str(step_id or "")) if part
    )
    importance = max(0, min(int(importance), 100))
    confidence = 1.0 if source in {"USER_OBSERVED", "SYSTEM_OBSERVED"} else 0.9

    profile = {
        "profile_id": profile_id,
        "account_hash": account_hash,
        "provider": provider,
        "logical_browser_id": logical_browser_id,
        "project_id": project_id,
        "current_origin": origin,
        "last_url": safe_url,
        "last_title": clean_title,
        "updated_at": now,
    }
    profile_path = _ensure_root() / "profiles" / f"{account_hash}.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    existing_profile = _read_json(profile_path)
    profile["created_at"] = (
        existing_profile.get("created_at") if existing_profile else now
    )
    _atomic_json(profile_path, profile)

    memory_path = _account_dir("memories", account_hash) / f"{memory_hash}.json"
    existing = _read_json(memory_path)
    memory = {
        "memory_id": memory_id,
        "profile_id": profile_id,
        "account_hash": account_hash,
        "project_id": project_id,
        "origin": origin,
        "memory_type": memory_type,
        "memory_key": memory_key,
        "content": content,
        "content_text": text,
        "source": source,
        "confidence": confidence,
        "importance": max(importance, int(existing.get("importance", 0))) if existing else importance,
        "token_estimate": schema._token_estimate(text),
        "memory_hash": memory_hash,
        "created_at": existing.get("created_at") if existing else now,
        "updated_at": now,
        "expires_at": existing.get("expires_at") if existing else schema._expires_at(),
    }
    _atomic_json(memory_path, memory)

    event_id = f"bmef_{uuid.uuid4().hex}"
    event_body = {
        "event_id": event_id,
        "memory_id": memory_id,
        "account_hash": account_hash,
        "action": str(action)[:100],
        "actor": str(actor)[:100],
        "plan_id": str(plan_id)[:100] if plan_id else None,
        "step_id": str(step_id)[:100] if step_id else None,
        "source_evidence_hash": source_evidence_hash,
        "created_at": now,
    }
    event_body["event_hash"] = canonical_hash(event_body)
    _atomic_json(_account_dir("events", account_hash) / f"{event_id}.json", event_body)
    return memory_id


def _matches_query(record: dict[str, Any], query: str) -> bool:
    terms = [term for term in query.lower().split() if term]
    if not terms:
        return True
    haystack = f"{record.get('content_text', '')} {record.get('memory_key', '')}".lower()
    return all(term in haystack for term in terms)


def search_context(
    *,
    account_hash: str,
    query: str = "",
    project_id: Optional[str] = None,
    origin: Optional[str] = None,
    token_budget: int = schema.DEFAULT_ACTIVE_TOKEN_BUDGET,
    limit: int = 100,
) -> dict[str, Any]:
    budget = max(1_000, min(int(token_budget), schema.MAX_ACTIVE_TOKEN_BUDGET))
    row_limit = max(1, min(int(limit), 500))
    safe_origin = schema._origin(origin) if origin else None
    directory = root() / "memories" / account_hash
    rows: list[dict[str, Any]] = []
    if directory.is_dir():
        for path in directory.glob("*.json"):
            record = _read_json(path)
            if not record or _expired(record.get("expires_at")):
                continue
            if project_id is not None and record.get("project_id") != project_id:
                continue
            if safe_origin is not None and record.get("origin") != safe_origin:
                continue
            if not _matches_query(record, query.strip()):
                continue
            rows.append(record)

    stored_rows: list[dict[str, Any]] = []
    if directory.is_dir():
        for path in directory.glob("*.json"):
            record = _read_json(path)
            if record and not _expired(record.get("expires_at")):
                stored_rows.append(record)
    stored_tokens = sum(max(0, int(row.get("token_estimate", 0))) for row in stored_rows)

    rows.sort(
        key=lambda row: (int(row.get("importance", 0)), str(row.get("updated_at", ""))),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    selected_tokens = 0
    for record in rows[:row_limit]:
        estimated = max(0, int(record.get("token_estimate", 0)))
        if selected_tokens + estimated > budget:
            continue
        selected.append({
            "memory_id": record.get("memory_id"),
            "project_id": record.get("project_id"),
            "origin": record.get("origin"),
            "memory_type": record.get("memory_type"),
            "memory_key": record.get("memory_key"),
            "content": record.get("content") or {},
            "source": record.get("source"),
            "confidence": float(record.get("confidence", 0.0)),
            "importance": int(record.get("importance", 0)),
            "token_estimate": estimated,
            "memory_hash": record.get("memory_hash"),
            "updated_at": record.get("updated_at"),
            "requires_live_verification": record.get("memory_type")
            in {"authorization", "payment", "security", "deployment_state"},
        })
        selected_tokens += estimated
        if selected_tokens >= budget:
            break

    return {
        "available": True,
        "backend": "azure_files",
        "logical_context": "unbounded durable memory with bounded active retrieval",
        "stored_memory_count": len(stored_rows),
        "stored_token_estimate": stored_tokens,
        "selected_token_estimate": selected_tokens,
        "token_budget": budget,
        "memories": selected,
        "truth_boundary": "memory is context, not current authorization or proof; high-impact state must be re-verified live",
    }


__all__ = ["record_observation", "root", "search_context"]