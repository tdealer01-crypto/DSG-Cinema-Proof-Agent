from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import AuditChainProof

ZERO_HASH = "0" * 64


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class AuditStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def initialize(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    proof_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def append(self, payload: dict[str, Any], proof_hash: str) -> AuditChainProof:
        payload_json = canonical_json(payload)
        with sqlite3.connect(self.db_path, isolation_level=None) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT sequence, event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = row[1] if row else ZERO_HASH
            event_hash = hashlib.sha256(
                f"{previous_hash}:{proof_hash}:{payload_json}".encode("utf-8")
            ).hexdigest()
            cursor = connection.execute(
                """
                INSERT INTO audit_events(previous_hash, event_hash, proof_hash, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (previous_hash, event_hash, proof_hash, payload_json),
            )
            sequence = int(cursor.lastrowid)
            connection.commit()
        return AuditChainProof(
            sequence=sequence,
            previous_hash=previous_hash,
            event_hash=event_hash,
        )

    def get(self, event_hash: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT sequence, created_at, previous_hash, event_hash, proof_hash, payload_json
                FROM audit_events WHERE event_hash = ?
                """,
                (event_hash,),
            ).fetchone()
        if row is None:
            return None
        return {
            "sequence": row[0],
            "created_at": row[1],
            "previous_hash": row[2],
            "event_hash": row[3],
            "proof_hash": row[4],
            "payload": json.loads(row[5]),
        }


def create_audit_store(
    backend: str,
    db_path: str,
    firestore_collection: str,
    google_cloud_project: str | None = None,
    supabase_url: str | None = None,
    supabase_service_role_key: str | None = None,
):
    """Create the configured audit store without silently falling back on errors."""
    if backend == "sqlite":
        return AuditStore(db_path)
    if backend == "firestore":
        from .audit_firestore import FirestoreAuditStore

        return FirestoreAuditStore(firestore_collection, project=google_cloud_project)
    if backend == "supabase":
        from .audit_supabase import SupabaseAuditStore

        return SupabaseAuditStore(supabase_url, supabase_service_role_key)
    raise ValueError(f"Unsupported AUDIT_BACKEND: {backend}")
