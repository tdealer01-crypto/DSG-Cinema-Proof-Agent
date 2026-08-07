from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

from .audit import ZERO_HASH, canonical_json
from .models import AuditChainProof


class FirestoreAuditStore:
    """Transactional tamper-evident audit chain for multi-instance Cloud Run deployments."""

    def __init__(self, collection_name: str, project: str | None = None):
        self.client = firestore.Client(project=project)
        self.collection = self.client.collection(collection_name)
        self.head = self.collection.document("_chain_head")

    def initialize(self) -> None:
        transaction = self.client.transaction()

        @firestore.transactional
        def ensure_head(txn):
            snapshot = self.head.get(transaction=txn)
            if not snapshot.exists:
                txn.set(self.head, {"sequence": 0, "event_hash": ZERO_HASH})

        ensure_head(transaction)

    def append(self, payload: dict[str, Any], proof_hash: str) -> AuditChainProof:
        payload_json = canonical_json(payload)
        transaction = self.client.transaction()

        @firestore.transactional
        def append_event(txn):
            snapshot = self.head.get(transaction=txn)
            head = snapshot.to_dict() if snapshot.exists else None
            previous_hash = str((head or {}).get("event_hash", ZERO_HASH))
            sequence = int((head or {}).get("sequence", 0)) + 1
            event_hash = hashlib.sha256(
                f"{previous_hash}:{proof_hash}:{payload_json}".encode("utf-8")
            ).hexdigest()
            event_ref = self.collection.document(event_hash)
            txn.set(
                event_ref,
                {
                    "sequence": sequence,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "previous_hash": previous_hash,
                    "event_hash": event_hash,
                    "proof_hash": proof_hash,
                    "payload": payload,
                },
            )
            txn.set(self.head, {"sequence": sequence, "event_hash": event_hash})
            return AuditChainProof(
                sequence=sequence,
                previous_hash=previous_hash,
                event_hash=event_hash,
            )

        return append_event(transaction)

    def get(self, event_hash: str) -> dict[str, Any] | None:
        if event_hash == "_chain_head":
            return None
        snapshot = self.collection.document(event_hash).get()
        if not snapshot.exists:
            return None
        return snapshot.to_dict()
