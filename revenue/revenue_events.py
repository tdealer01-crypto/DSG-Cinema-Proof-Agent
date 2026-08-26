"""Deterministic, idempotent revenue-event ledger.

The ledger stores only structural event metadata and a canonical payload digest.
It intentionally does not persist the raw payload so marketing/customer PII is not
copied into the revenue evidence store.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import fcntl
import json
import os
from pathlib import Path
from threading import RLock
import tempfile
from typing import Any, Mapping


class RevenueEventError(RuntimeError):
    """Base revenue event ledger error."""


class EventConflictError(RevenueEventError):
    """Raised when an idempotency key is replayed with different content."""


class EventNotFoundError(RevenueEventError):
    """Raised when processing state is changed for an unknown event."""


class EventStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_payload_hash(payload: Mapping[str, Any] | None) -> str:
    """Return a stable SHA-256 digest for a JSON-compatible payload."""

    encoded = json.dumps(
        dict(payload or {}),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def deterministic_event_id(*, source: str, source_event_id: str, payload_hash: str) -> str:
    material = f"{source}\x00{source_event_id}\x00{payload_hash}".encode("utf-8")
    return f"rev_{sha256(material).hexdigest()[:32]}"


@dataclass(frozen=True)
class RevenueEvent:
    event_id: str
    account_id: str
    event_type: str
    source: str
    source_event_id: str
    payload_hash: str
    occurred_at: str
    received_at: str
    status: EventStatus = EventStatus.RECEIVED
    processed_at: str | None = None
    evidence_ref: str | None = None
    failure_reason: str | None = None

    def public_view(self) -> dict[str, Any]:
        """Safe structural view; raw payload/PII is never present."""

        data = asdict(self)
        data["status"] = self.status.value
        return data


class RevenueEventStore:
    """Idempotent event store keyed by ``(source, source_event_id)``.

    ``path=None`` keeps the store in memory. With a path, every read-modify-write
    section is serialized across threads and processes, reloads the authoritative
    snapshot, and persists using fsync + atomic replace.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None):
        self._path = Path(path) if path else None
        self._lock = RLock()
        self._events: dict[tuple[str, str], RevenueEvent] = {}
        if self._path and self._path.exists():
            self._load()

    def _load(self) -> None:
        assert self._path is not None
        raw = json.loads(self._path.read_text(encoding="utf-8") or "[]")
        if not isinstance(raw, list):
            raise RevenueEventError("revenue event store must contain a JSON array")
        loaded: dict[tuple[str, str], RevenueEvent] = {}
        for item in raw:
            event = RevenueEvent(
                event_id=str(item["event_id"]),
                account_id=str(item["account_id"]),
                event_type=str(item["event_type"]),
                source=str(item["source"]),
                source_event_id=str(item["source_event_id"]),
                payload_hash=str(item["payload_hash"]),
                occurred_at=str(item["occurred_at"]),
                received_at=str(item["received_at"]),
                status=EventStatus(str(item["status"])),
                processed_at=item.get("processed_at"),
                evidence_ref=item.get("evidence_ref"),
                failure_reason=item.get("failure_reason"),
            )
            key = (event.source, event.source_event_id)
            if key in loaded:
                raise RevenueEventError(f"duplicate idempotency key in store: {key!r}")
            loaded[key] = event
        self._events = loaded

    def _reload_if_changed(self) -> None:
        """Reload authoritative state after acquiring the process lock."""

        if self._path is None or not self._path.exists():
            return
        self._load()

    @contextmanager
    def _file_lock(self):
        """Cross-process sidecar lock safe across atomic data-file replacement."""

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
        """Serialize threads/processes and refresh before any authoritative read."""

        with self._lock:
            with self._file_lock():
                self._reload_if_changed()
                yield

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            event.public_view()
            for _, event in sorted(self._events.items(), key=lambda pair: pair[0])
        ]
        payload = json.dumps(rows, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        fd, temporary_name = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
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

    def record(
        self,
        *,
        account_id: str,
        event_type: str,
        source: str,
        source_event_id: str,
        payload: Mapping[str, Any] | None = None,
        occurred_at: str | None = None,
    ) -> RevenueEvent:
        account_id = account_id.strip()
        event_type = event_type.strip()
        source = source.strip()
        source_event_id = source_event_id.strip()
        if not all((account_id, event_type, source, source_event_id)):
            raise ValueError("account_id, event_type, source and source_event_id are required")

        payload_hash = canonical_payload_hash(payload)
        key = (source, source_event_id)
        with self._critical_section():
            existing = self._events.get(key)
            if existing is not None:
                if (
                    existing.account_id != account_id
                    or existing.event_type != event_type
                    or existing.payload_hash != payload_hash
                    or (occurred_at is not None and existing.occurred_at != occurred_at)
                ):
                    raise EventConflictError(
                        "idempotency key replayed with different revenue event content"
                    )
                return existing

            now = _utc_now()
            event = RevenueEvent(
                event_id=deterministic_event_id(
                    source=source,
                    source_event_id=source_event_id,
                    payload_hash=payload_hash,
                ),
                account_id=account_id,
                event_type=event_type,
                source=source,
                source_event_id=source_event_id,
                payload_hash=payload_hash,
                occurred_at=occurred_at or now,
                received_at=now,
            )
            self._events[key] = event
            self._persist()
            return event

    def get(self, *, source: str, source_event_id: str) -> RevenueEvent | None:
        with self._critical_section():
            return self._events.get((source, source_event_id))

    def mark_processed(
        self, *, source: str, source_event_id: str, evidence_ref: str
    ) -> RevenueEvent:
        evidence_ref = evidence_ref.strip()
        if not evidence_ref:
            raise ValueError("evidence_ref is required to mark an event processed")
        return self._set_terminal(
            source=source,
            source_event_id=source_event_id,
            status=EventStatus.PROCESSED,
            evidence_ref=evidence_ref,
            failure_reason=None,
        )

    def mark_failed(
        self, *, source: str, source_event_id: str, failure_reason: str
    ) -> RevenueEvent:
        failure_reason = failure_reason.strip()
        if not failure_reason:
            raise ValueError("failure_reason is required to mark an event failed")
        return self._set_terminal(
            source=source,
            source_event_id=source_event_id,
            status=EventStatus.FAILED,
            evidence_ref=None,
            failure_reason=failure_reason,
        )

    def _set_terminal(
        self,
        *,
        source: str,
        source_event_id: str,
        status: EventStatus,
        evidence_ref: str | None,
        failure_reason: str | None,
    ) -> RevenueEvent:
        key = (source, source_event_id)
        with self._critical_section():
            event = self._events.get(key)
            if event is None:
                raise EventNotFoundError(f"unknown revenue event: {key!r}")
            if event.status != EventStatus.RECEIVED:
                if (
                    event.status == status
                    and event.evidence_ref == evidence_ref
                    and event.failure_reason == failure_reason
                ):
                    return event
                raise EventConflictError("terminal revenue event status cannot be rewritten")
            updated = replace(
                event,
                status=status,
                processed_at=_utc_now(),
                evidence_ref=evidence_ref,
                failure_reason=failure_reason,
            )
            self._events[key] = updated
            self._persist()
            return updated

    def list_events(self) -> list[RevenueEvent]:
        with self._critical_section():
            return [self._events[key] for key in sorted(self._events)]
