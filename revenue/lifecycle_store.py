"""Durable evidence store for deterministic revenue lifecycle state.

The lifecycle gate in ``revenue.lifecycle`` remains side-effect free. This module
persists only its approved structural transition output: account/state, evidence
references, payment source identifiers, and SHA-256 reason digests. Raw reason
text and marketing/customer PII are never copied into the lifecycle evidence
store.

Persistence is a second trust boundary. A ``LifecycleTransition`` dataclass can
be instantiated directly by Python callers, so CUSTOMER persistence revalidates
the authoritative ``PaymentProof`` instead of trusting copied source/id fields.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import fcntl
import json
import os
from pathlib import Path
from threading import RLock
import tempfile
from typing import Any

from .lifecycle import (
    LifecycleTransition,
    PaymentProof,
    RevenueState,
    allowed_next_states,
)


ZERO_HASH = "0" * 64


class LifecycleStoreError(RuntimeError):
    """Base lifecycle persistence error."""


class LifecycleNotFoundError(LifecycleStoreError):
    """Raised when a transition targets an account with no initialized state."""


class LifecycleConflictError(LifecycleStoreError):
    """Raised when immutable lifecycle evidence conflicts with stored truth."""


class StaleLifecycleTransitionError(LifecycleStoreError):
    """Raised when transition.from_state no longer matches current state."""


@dataclass(frozen=True)
class LifecycleRecord:
    account_id: str
    state: RevenueState
    version: int
    head_hash: str
    initialized_at: str
    updated_at: str

    def public_view(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


@dataclass(frozen=True)
class LifecycleEvidence:
    entry_id: str
    account_id: str
    kind: str
    from_state: RevenueState | None
    to_state: RevenueState
    version: int
    evidence_ref: str
    reason_hash: str
    payment_source: str | None
    payment_source_id: str | None
    previous_hash: str
    entry_hash: str
    recorded_at: str

    def public_view(self) -> dict[str, Any]:
        data = asdict(self)
        data["from_state"] = self.from_state.value if self.from_state else None
        data["to_state"] = self.to_state.value
        return data


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _entry_hash(entry: LifecycleEvidence) -> str:
    body = entry.public_view()
    body.pop("entry_hash", None)
    return _canonical_hash(body)


def _initialize_entry_id(account_id: str, evidence_ref: str) -> str:
    return "life_" + _canonical_hash(
        {"kind": "INITIALIZE", "account_id": account_id, "evidence_ref": evidence_ref}
    )[:32]


def _transition_entry_id(transition: LifecycleTransition) -> str:
    return "life_" + _canonical_hash(
        {
            "kind": "TRANSITION",
            "account_id": transition.account_id,
            "from_state": transition.from_state.value,
            "to_state": transition.to_state.value,
            "reason_hash": _digest(transition.reason),
            "evidence_ref": transition.evidence_ref,
            "payment_source": transition.payment_source,
            "payment_source_id": transition.payment_source_id,
        }
    )[:32]


class LifecycleStateStore:
    """Compare-and-apply lifecycle store with per-account evidence hash chains."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self._path = Path(path) if path else None
        self._lock = RLock()
        self._records: dict[str, LifecycleRecord] = {}
        self._history: dict[str, list[LifecycleEvidence]] = {}
        if self._path and self._path.exists():
            self._load()

    @property
    def path(self) -> str | None:
        return str(self._path) if self._path else None

    def _load(self) -> None:
        assert self._path is not None
        raw = json.loads(self._path.read_text(encoding="utf-8") or "{}")
        if not isinstance(raw, dict):
            raise LifecycleStoreError("lifecycle store must contain a JSON object")
        records = raw.get("records", [])
        history = raw.get("history", [])
        if not isinstance(records, list) or not isinstance(history, list):
            raise LifecycleStoreError("lifecycle store records/history must be arrays")

        loaded_records: dict[str, LifecycleRecord] = {}
        for item in records:
            record = LifecycleRecord(
                account_id=str(item["account_id"]),
                state=RevenueState(str(item["state"])),
                version=int(item["version"]),
                head_hash=str(item["head_hash"]),
                initialized_at=str(item["initialized_at"]),
                updated_at=str(item["updated_at"]),
            )
            if record.account_id in loaded_records:
                raise LifecycleStoreError("duplicate lifecycle account record")
            loaded_records[record.account_id] = record

        loaded_history: dict[str, list[LifecycleEvidence]] = {}
        seen_ids: set[str] = set()
        for item in history:
            entry = LifecycleEvidence(
                entry_id=str(item["entry_id"]),
                account_id=str(item["account_id"]),
                kind=str(item["kind"]),
                from_state=(
                    RevenueState(str(item["from_state"]))
                    if item.get("from_state") is not None
                    else None
                ),
                to_state=RevenueState(str(item["to_state"])),
                version=int(item["version"]),
                evidence_ref=str(item["evidence_ref"]),
                reason_hash=str(item["reason_hash"]),
                payment_source=item.get("payment_source"),
                payment_source_id=item.get("payment_source_id"),
                previous_hash=str(item["previous_hash"]),
                entry_hash=str(item["entry_hash"]),
                recorded_at=str(item["recorded_at"]),
            )
            if entry.entry_id in seen_ids:
                raise LifecycleStoreError("duplicate lifecycle evidence id")
            seen_ids.add(entry.entry_id)
            loaded_history.setdefault(entry.account_id, []).append(entry)

        for entries in loaded_history.values():
            entries.sort(key=lambda item: item.version)
        self._records = loaded_records
        self._history = loaded_history

    def _reload(self) -> None:
        if self._path is not None and self._path.exists():
            self._load()

    @contextmanager
    def _file_lock(self):
        if self._path is None:
            yield
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        with open(lock_path, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _critical_section(self):
        with self._lock:
            with self._file_lock():
                self._reload()
                yield

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "records": [
                self._records[key].public_view() for key in sorted(self._records)
            ],
            "history": [
                entry.public_view()
                for account_id in sorted(self._history)
                for entry in sorted(self._history[account_id], key=lambda item: item.version)
            ],
        }
        serialized = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        fd, temp_name = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        finally:
            temporary.unlink(missing_ok=True)
        try:
            directory_fd = os.open(self._path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except AttributeError:
            pass

    def _find_entry(self, entry_id: str) -> LifecycleEvidence | None:
        for entries in self._history.values():
            for entry in entries:
                if entry.entry_id == entry_id:
                    return entry
        return None

    def initialize(
        self,
        *,
        account_id: str,
        evidence_ref: str,
        state: RevenueState = RevenueState.LEAD,
    ) -> tuple[LifecycleRecord, bool]:
        """Initialize an account exactly once, and only at LEAD."""

        account_id = account_id.strip()
        evidence_ref = evidence_ref.strip()
        if not account_id:
            raise ValueError("account_id is required")
        if not evidence_ref:
            raise ValueError("evidence_ref is required")
        if state != RevenueState.LEAD:
            raise LifecycleConflictError("new lifecycle accounts may initialize only at LEAD")

        entry_id = _initialize_entry_id(account_id, evidence_ref)
        with self._critical_section():
            replay = self._find_entry(entry_id)
            if replay is not None:
                record = self._records.get(account_id)
                if record is None or replay.account_id != account_id or replay.kind != "INITIALIZE":
                    raise LifecycleConflictError("initialization evidence conflicts with stored truth")
                return record, False
            if account_id in self._records:
                raise LifecycleConflictError("lifecycle account is already initialized")

            now = _utc_now()
            entry = LifecycleEvidence(
                entry_id=entry_id,
                account_id=account_id,
                kind="INITIALIZE",
                from_state=None,
                to_state=RevenueState.LEAD,
                version=0,
                evidence_ref=evidence_ref,
                reason_hash=_digest("INITIALIZE"),
                payment_source=None,
                payment_source_id=None,
                previous_hash=ZERO_HASH,
                entry_hash="",
                recorded_at=now,
            )
            entry = replace(entry, entry_hash=_entry_hash(entry))
            record = LifecycleRecord(
                account_id=account_id,
                state=RevenueState.LEAD,
                version=0,
                head_hash=entry.entry_hash,
                initialized_at=now,
                updated_at=now,
            )
            self._records[account_id] = record
            self._history[account_id] = [entry]
            self._persist()
            return record, True

    def apply(
        self,
        transition: LifecycleTransition,
        *,
        payment_proof: PaymentProof | None = None,
    ) -> tuple[LifecycleRecord, bool]:
        """Compare current state and persist one transition after trust revalidation.

        For CUSTOMER, callers must supply the same authoritative PaymentProof that
        authorized the lifecycle transition. This prevents a manually constructed
        LifecycleTransition from smuggling unverified payment source fields across
        the persistence boundary.
        """

        entry_id = _transition_entry_id(transition)
        with self._critical_section():
            replay = self._find_entry(entry_id)
            if replay is not None:
                record = self._records.get(transition.account_id)
                if record is None or replay.account_id != transition.account_id:
                    raise LifecycleConflictError("transition replay conflicts with stored truth")
                return record, False

            record = self._records.get(transition.account_id)
            if record is None:
                raise LifecycleNotFoundError("lifecycle account is not initialized")
            if record.state != transition.from_state:
                raise StaleLifecycleTransitionError(
                    f"stale lifecycle transition: current={record.state.value}, "
                    f"requested_from={transition.from_state.value}"
                )
            if transition.to_state not in allowed_next_states(record.state):
                raise LifecycleConflictError(
                    f"illegal persisted lifecycle edge: {record.state.value} -> "
                    f"{transition.to_state.value}"
                )

            if transition.to_state == RevenueState.CUSTOMER:
                if payment_proof is None or not payment_proof.is_authoritative_for(
                    transition.account_id
                ):
                    raise LifecycleConflictError(
                        "CUSTOMER persistence requires authoritative payment proof"
                    )
                if (
                    transition.payment_source != payment_proof.source
                    or transition.payment_source_id != payment_proof.source_id
                ):
                    raise LifecycleConflictError(
                        "CUSTOMER transition payment fields do not match payment proof"
                    )
            elif (
                payment_proof is not None
                or transition.payment_source is not None
                or transition.payment_source_id is not None
            ):
                raise LifecycleConflictError(
                    "payment evidence is valid only for CUSTOMER transitions"
                )

            now = _utc_now()
            entry = LifecycleEvidence(
                entry_id=entry_id,
                account_id=transition.account_id,
                kind="TRANSITION",
                from_state=transition.from_state,
                to_state=transition.to_state,
                version=record.version + 1,
                evidence_ref=transition.evidence_ref,
                reason_hash=_digest(transition.reason),
                payment_source=transition.payment_source,
                payment_source_id=transition.payment_source_id,
                previous_hash=record.head_hash,
                entry_hash="",
                recorded_at=now,
            )
            entry = replace(entry, entry_hash=_entry_hash(entry))
            updated = LifecycleRecord(
                account_id=record.account_id,
                state=transition.to_state,
                version=entry.version,
                head_hash=entry.entry_hash,
                initialized_at=record.initialized_at,
                updated_at=now,
            )
            self._history.setdefault(record.account_id, []).append(entry)
            self._records[record.account_id] = updated
            self._persist()
            return updated, True

    def get(self, account_id: str) -> LifecycleRecord | None:
        with self._critical_section():
            return self._records.get(account_id)

    def history(self, account_id: str) -> tuple[LifecycleEvidence, ...]:
        with self._critical_section():
            return tuple(self._history.get(account_id, ()))

    def verify_chain(self, account_id: str | None = None) -> bool:
        """Recompute stored per-account evidence chains and record heads."""

        with self._critical_section():
            account_ids = [account_id] if account_id is not None else sorted(self._records)
            for selected in account_ids:
                record = self._records.get(selected)
                entries = self._history.get(selected, [])
                if record is None or not entries:
                    return False
                previous = ZERO_HASH
                expected_version = 0
                current_state: RevenueState | None = None
                for entry in entries:
                    if entry.version != expected_version:
                        return False
                    if entry.previous_hash != previous:
                        return False
                    if entry.entry_hash != _entry_hash(entry):
                        return False
                    if expected_version == 0:
                        if entry.kind != "INITIALIZE" or entry.from_state is not None:
                            return False
                        if entry.to_state != RevenueState.LEAD:
                            return False
                    else:
                        if entry.kind != "TRANSITION" or entry.from_state != current_state:
                            return False
                    current_state = entry.to_state
                    previous = entry.entry_hash
                    expected_version += 1
                if record.version != entries[-1].version:
                    return False
                if record.state != current_state:
                    return False
                if record.head_hash != previous:
                    return False
            return True


__all__ = [
    "LifecycleConflictError",
    "LifecycleEvidence",
    "LifecycleNotFoundError",
    "LifecycleRecord",
    "LifecycleStateStore",
    "LifecycleStoreError",
    "StaleLifecycleTransitionError",
]
