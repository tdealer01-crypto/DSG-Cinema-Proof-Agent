from __future__ import annotations

import os
from pathlib import Path

import pytest

from revenue.ledger import LedgerStore


def _append(store: LedgerStore, key: str) -> None:
    store.append(
        account_id="acct",
        channel="api",
        sku="verified_execution",
        quantity=1,
        unit_price_micros=0,
        amount_micros=0,
        proof_hash="a" * 64,
        context_hash=(key + "b" * 64)[:64],
        idempotency_key=key,
        units_before=0,
    )


def test_snapshot_sync_order_is_file_then_replace_then_directory(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    store = LedgerStore(str(path))
    events: list[str] = []

    original_fsync = os.fsync
    original_replace = os.replace

    def traced_fsync(fd: int) -> None:
        events.append("fsync")
        original_fsync(fd)

    def traced_replace(src, dst) -> None:
        events.append("replace")
        original_replace(src, dst)

    monkeypatch.setattr(os, "fsync", traced_fsync)
    monkeypatch.setattr(os, "replace", traced_replace)

    _append(store, "order")

    assert events[:3] == ["fsync", "replace", "fsync"]


def test_snapshot_temp_files_are_unique_and_owner_only(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    store = LedgerStore(str(path))
    temporary_paths: list[Path] = []
    modes: list[int] = []

    original_replace = os.replace

    def inspected_replace(src, dst) -> None:
        temporary = Path(src)
        temporary_paths.append(temporary)
        modes.append(temporary.stat().st_mode & 0o777)
        original_replace(src, dst)

    monkeypatch.setattr(os, "replace", inspected_replace)

    _append(store, "first")
    _append(store, "second")

    assert len(temporary_paths) == 2
    assert temporary_paths[0] != temporary_paths[1]
    assert all(path.name.endswith(".tmp") for path in temporary_paths)
    assert modes == [0o600, 0o600]


def test_directory_fsync_failure_is_not_silently_swallowed(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    store = LedgerStore(str(path))
    original_fsync = os.fsync
    calls = 0

    def fail_directory_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            original_fsync(fd)
            return
        raise OSError("directory fsync failed")

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)

    with pytest.raises(OSError, match="directory fsync failed"):
        _append(store, "dir-fsync-error")

    assert path.exists(), "atomic replace happened before the directory fsync failure"
