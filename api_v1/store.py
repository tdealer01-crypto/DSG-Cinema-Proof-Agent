"""Record store for plans, executions, evidence, and proofs.

Truth boundary, stated plainly: with `DSG_V1_STORE_PATH` set this is a
single-file JSON store guarded by an advisory file lock — correct for one
replica and durable across restarts. Without it the store is process memory,
which loses records on restart. `/api/v1/status` reports which mode is live, so
a UI never has to guess whether a proof it was shown will still exist tomorrow.
Multi-replica deployments need a transactional store; see REVENUE_AUTOMATION.md.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

COLLECTIONS = ("plans", "executions", "proofs")


class RecordStore:
    def __init__(self, path: Optional[str] = None) -> None:
        raw = (path if path is not None else os.getenv("DSG_V1_STORE_PATH", "")).strip()
        self.path: Optional[Path] = Path(raw) if raw else None
        self._lock = threading.RLock()
        self._data: dict[str, dict[str, Any]] = {name: {} for name in COLLECTIONS}
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self.path.write_text(json.dumps(self._data), encoding="utf-8")
            self._load()

    # ------------------------------------------------------------------ state
    @property
    def durable(self) -> bool:
        return self.path is not None

    @property
    def mode(self) -> str:
        return "file" if self.durable else "memory"

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            loaded = {}
        for name in COLLECTIONS:
            value = loaded.get(name)
            self._data[name] = value if isinstance(value, dict) else {}

    def _persist(self) -> None:
        if self.path is None:
            return
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self._data, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)

    @contextmanager
    def _critical_section(self) -> Iterator[None]:
        with self._lock:
            if self.path is None:
                yield
                return
            lock_path = self.path.with_suffix(self.path.suffix + ".lock")
            with open(lock_path, "a+") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    self._load()
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    # ------------------------------------------------------------- operations
    def put(self, collection: str, key: str, value: dict[str, Any]) -> dict[str, Any]:
        with self._critical_section():
            self._data[collection][key] = value
            self._persist()
        return value

    def get(self, collection: str, key: str) -> Optional[dict[str, Any]]:
        with self._critical_section():
            record = self._data[collection].get(key)
            return json.loads(json.dumps(record)) if record is not None else None

    def mutate(
        self,
        collection: str,
        key: str,
        change: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        """Read-modify-write one record while holding the lock."""
        with self._critical_section():
            record = self._data[collection].get(key)
            if record is None:
                return None
            updated = change(json.loads(json.dumps(record)))
            self._data[collection][key] = updated
            self._persist()
            return updated

    def count(self, collection: str) -> int:
        with self._critical_section():
            return len(self._data[collection])

    def counts(self) -> dict[str, int]:
        with self._critical_section():
            return {name: len(self._data[name]) for name in COLLECTIONS}


_store: Optional[RecordStore] = None
_store_lock = threading.Lock()


def get_store() -> RecordStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = RecordStore()
    return _store


def reset_store(store: Optional[RecordStore] = None) -> RecordStore:
    """Replace the process store. Used by tests and explicit reconfiguration."""
    global _store
    _store = store if store is not None else RecordStore()
    return _store
