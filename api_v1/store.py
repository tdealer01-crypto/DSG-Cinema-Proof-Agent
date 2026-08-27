"""Record store for plans, executions, evidence, and proofs.

Truth boundary, stated plainly:

- `DSG_V1_STORE_PATH` is the explicit v1 persistence path.
- When it is unset but Cinema already has the durable revenue Azure Files mount,
  v1 automatically stores `v1-records.json` beside the revenue ledger/account
  files. This closes the gap where billing survived a revision but plan/proof
  records silently stayed in process memory.
- With no durable path at all, the store remains process memory and
  `/api/v1/status` reports `durable: false`.

The JSON-file backend is intended for one writer. Production therefore pairs it
with a single-replica deployment guard. A future multi-replica deployment should
move these records to a transactional store rather than weakening this boundary.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional

COLLECTIONS = ("plans", "executions", "proofs")
_REVENUE_STORE_VARS = ("DSG_REVENUE_LEDGER_STORE", "DSG_REVENUE_ACCOUNT_STORE")


def resolve_store_path(
    path: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> tuple[Optional[Path], str]:
    """Resolve v1 persistence without inventing a second production volume.

    Precedence is explicit v1 path -> existing durable revenue mount -> memory.
    `source` is deliberately non-secret so status/debugging can say why a record
    is persistent without exposing the filesystem path.
    """
    source = env if env is not None else os.environ
    if path is not None:
        raw = path.strip()
        return (Path(raw), "explicit") if raw else (None, "memory")

    explicit = (source.get("DSG_V1_STORE_PATH") or "").strip()
    if explicit:
        return Path(explicit), "explicit"

    for name in _REVENUE_STORE_VARS:
        revenue_path = (source.get(name) or "").strip()
        if revenue_path:
            return Path(revenue_path).parent / "v1-records.json", "revenue_mount"

    return None, "memory"


class RecordStore:
    def __init__(
        self,
        path: Optional[str] = None,
        *,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.path, self.source = resolve_store_path(path, env)
        self._env = env if env is not None else os.environ
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

    @property
    def single_writer_attested(self) -> bool:
        if not self.durable:
            return False
        value = (
            self._env.get("DSG_V1_SINGLE_WRITER")
            or self._env.get("DSG_REVENUE_SINGLE_WRITER")
            or ""
        )
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @property
    def production_safe(self) -> bool:
        """File persistence is safe only when deployment attests one writer."""
        return self.durable and self.single_writer_attested

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
