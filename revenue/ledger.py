"""Append-only, hash-chained usage ledger.

Every billable unit is recorded as one entry whose `entry_hash` commits to the
previous entry. The chain is the revenue evidence: it can be replayed and
verified independently, exactly like the Z3 proof hashes it references.

Storage note (truth boundary): the bundled stores are process-memory and
single-file JSON. They are correct for one Cinema replica. Multi-replica or
high-durability deployments require a transactional store; see
REVENUE_AUTOMATION.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

GENESIS_HASH = "0" * 64


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def billing_period(timestamp: Optional[str] = None) -> str:
    """Return the UTC billing period (YYYY-MM) for a timestamp."""
    if timestamp is None:
        return datetime.now(timezone.utc).strftime("%Y-%m")
    return timestamp[:7]


def canonical_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LedgerEntry:
    sequence: int
    period: str
    account_id: str
    channel: str
    sku: str
    quantity: int
    units_before: int
    unit_price_micros: int
    amount_micros: int
    proof_hash: str
    context_hash: str
    idempotency_key: str
    recorded_at: str
    prev_hash: str
    entry_hash: str

    def to_dict(self) -> dict:
        return asdict(self)

    def commitment(self) -> dict:
        body = self.to_dict()
        body.pop("entry_hash")
        return body


def compute_entry_hash(body: dict) -> str:
    payload = dict(body)
    payload.pop("entry_hash", None)
    return canonical_hash(payload)


class LedgerStore:
    """In-memory ledger with an optional JSON file mirror."""

    def __init__(self, path: Optional[str] = None) -> None:
        self._lock = threading.Lock()
        self._entries: list[LedgerEntry] = []
        self._by_idempotency: dict[str, LedgerEntry] = {}
        self._path = Path(path) if path else None
        if self._path and self._path.exists():
            self._load()

    # ---------------------------------------------------------------- loading
    def _load(self) -> None:
        assert self._path is not None
        raw = json.loads(self._path.read_text(encoding="utf-8") or "[]")
        entries = [LedgerEntry(**item) for item in raw]
        verify_chain(entries)
        self._entries = entries
        self._by_idempotency = {entry.idempotency_key: entry for entry in entries}

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps([entry.to_dict() for entry in self._entries], indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self._path)

    # ---------------------------------------------------------------- queries
    def head_hash(self) -> str:
        with self._lock:
            return self._entries[-1].entry_hash if self._entries else GENESIS_HASH

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def entries(self) -> list[LedgerEntry]:
        with self._lock:
            return list(self._entries)

    def find_by_idempotency_key(self, key: str) -> Optional[LedgerEntry]:
        with self._lock:
            return self._by_idempotency.get(key)

    def units_used(self, account_id: str, period: str) -> int:
        with self._lock:
            return sum(
                entry.quantity
                for entry in self._entries
                if entry.account_id == account_id and entry.period == period
            )

    def period_entries(self, account_id: str, period: str) -> list[LedgerEntry]:
        with self._lock:
            return [
                entry
                for entry in self._entries
                if entry.account_id == account_id and entry.period == period
            ]

    # ---------------------------------------------------------------- appends
    def append(
        self,
        *,
        account_id: str,
        channel: str,
        sku: str,
        quantity: int,
        unit_price_micros: int,
        amount_micros: int,
        proof_hash: str,
        context_hash: str,
        idempotency_key: str,
        units_before: int,
        period: Optional[str] = None,
        recorded_at: Optional[str] = None,
    ) -> tuple[LedgerEntry, bool]:
        """Append one entry. Returns (entry, created)."""
        with self._lock:
            existing = self._by_idempotency.get(idempotency_key)
            if existing is not None:
                return existing, False

            return self._append_locked(
                account_id=account_id,
                channel=channel,
                sku=sku,
                quantity=quantity,
                unit_price_micros=unit_price_micros,
                amount_micros=amount_micros,
                proof_hash=proof_hash,
                context_hash=context_hash,
                idempotency_key=idempotency_key,
                units_before=units_before,
                period=period,
                recorded_at=recorded_at,
            )

    def append_metered(
        self,
        *,
        account_id: str,
        channel: str,
        sku: str,
        quantity: int,
        unit_price_micros: int,
        included_units: int,
        hard_cap_units: Optional[int],
        proof_hash: str,
        context_hash: str,
        idempotency_key: str,
        period: str,
        recorded_at: Optional[str] = None,
    ) -> tuple[LedgerEntry, bool]:
        """Validate quota, price, and append under one ledger lock.

        Authorization happens before solver work, but another request may
        finish while that proof is being computed.  Rechecking the cap in the
        same critical section as the append prevents two pre-authorized
        requests from crossing a hard cap or consuming the same included unit.
        Idempotent replays are returned before quota evaluation.
        """
        if quantity < 1:
            raise ValueError("quantity must be at least 1")

        with self._lock:
            existing = self._by_idempotency.get(idempotency_key)
            if existing is not None:
                return existing, False

            units_before = sum(
                entry.quantity
                for entry in self._entries
                if entry.account_id == account_id and entry.period == period
            )
            if hard_cap_units is not None and units_before + quantity > hard_cap_units:
                raise QuotaExceededError(
                    "plan quota was consumed by another request before metering"
                )

            remaining_included = max(included_units - units_before, 0)
            billable_quantity = max(quantity - remaining_included, 0)
            amount_micros = billable_quantity * unit_price_micros

            return self._append_locked(
                account_id=account_id,
                channel=channel,
                sku=sku,
                quantity=quantity,
                unit_price_micros=unit_price_micros,
                amount_micros=amount_micros,
                proof_hash=proof_hash,
                context_hash=context_hash,
                idempotency_key=idempotency_key,
                units_before=units_before,
                period=period,
                recorded_at=recorded_at,
            )

    def _append_locked(
        self,
        *,
        account_id: str,
        channel: str,
        sku: str,
        quantity: int,
        unit_price_micros: int,
        amount_micros: int,
        proof_hash: str,
        context_hash: str,
        idempotency_key: str,
        units_before: int,
        period: Optional[str],
        recorded_at: Optional[str],
    ) -> tuple[LedgerEntry, bool]:
        """Append while ``self._lock`` is held."""
        recorded = recorded_at or utc_now()
        body = {
            "sequence": len(self._entries),
            "period": period or billing_period(recorded),
            "account_id": account_id,
            "channel": channel,
            "sku": sku,
            "quantity": quantity,
            "units_before": units_before,
            "unit_price_micros": unit_price_micros,
            "amount_micros": amount_micros,
            "proof_hash": proof_hash,
            "context_hash": context_hash,
            "idempotency_key": idempotency_key,
            "recorded_at": recorded,
            "prev_hash": (
                self._entries[-1].entry_hash if self._entries else GENESIS_HASH
            ),
        }
        entry = LedgerEntry(**body, entry_hash=compute_entry_hash(body))
        self._entries.append(entry)
        self._by_idempotency[idempotency_key] = entry
        self._persist()
        return entry, True


class QuotaExceededError(ValueError):
    """Raised when an atomic ledger append would cross a hard cap."""


class ChainError(ValueError):
    """Raised when the ledger hash chain does not verify."""


def verify_chain(entries: Iterable[LedgerEntry]) -> dict:
    """Recompute the whole chain. Raises ChainError on the first mismatch."""
    previous = GENESIS_HASH
    count = 0
    total_micros = 0

    for index, entry in enumerate(entries):
        if entry.sequence != index:
            raise ChainError(f"entry {index} has sequence {entry.sequence}")
        if entry.prev_hash != previous:
            raise ChainError(f"entry {index} does not link to the previous entry")
        expected = compute_entry_hash(entry.commitment())
        if entry.entry_hash != expected:
            raise ChainError(f"entry {index} hash mismatch")
        previous = entry.entry_hash
        count += 1
        total_micros += entry.amount_micros

    return {
        "verified": True,
        "entries": count,
        "head_hash": previous,
        "total_amount_micros": total_micros,
    }
