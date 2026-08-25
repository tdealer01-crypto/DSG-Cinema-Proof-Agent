"""Durable, consent-aware marketing identity keyed by DSG account id.

Marketing identity is intentionally separate from billing entitlement state.
The join key is the non-secret DSG account id, which is also copied into Stripe
metadata and ActiveCampaign custom field ``DSG Account ID``.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class MarketingProfile:
    account_id: str
    email: Optional[str] = None
    marketing_consent: bool = False
    source: str = "api"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def public_view(self) -> dict:
        # Email is deliberately not echoed by billing endpoints.
        return {
            "account_id": self.account_id,
            "marketing_consent": self.marketing_consent,
            "source": self.source,
            "has_email": bool(self.email),
        }


class MarketingProfileStore:
    def __init__(self, path: Optional[str] = None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self._profiles: dict[str, MarketingProfile] = {}
        if self._path and self._path.exists():
            self._load()

    @property
    def path(self) -> Optional[str]:
        return str(self._path) if self._path is not None else None

    def _load(self) -> None:
        assert self._path is not None
        raw = json.loads(self._path.read_text(encoding="utf-8") or "[]")
        if not isinstance(raw, list):
            raise ValueError("marketing profile store must contain a JSON array")
        profiles: dict[str, MarketingProfile] = {}
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("marketing profile entries must be objects")
            profile = MarketingProfile(**item)
            profiles[profile.account_id] = profile
        self._profiles = profiles

    @contextmanager
    def _file_lock(self):
        if self._path is None:
            yield
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        with open(lock_path, "a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _critical_section(self):
        with self._lock:
            with self._file_lock():
                if self._path is not None and self._path.exists():
                    self._load()
                yield

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [profile.to_dict() for profile in self._profiles.values()],
            indent=2,
        )
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

    def get(self, account_id: str) -> Optional[MarketingProfile]:
        with self._critical_section():
            return self._profiles.get(account_id)

    def upsert(
        self,
        *,
        account_id: str,
        email: Optional[str],
        marketing_consent: bool,
        source: str,
    ) -> MarketingProfile:
        normalized_email = (email or "").strip().lower() or None
        normalized_source = (source or "api").strip() or "api"
        now = utc_now()
        with self._critical_section():
            current = self._profiles.get(account_id)
            if current is None:
                updated = MarketingProfile(
                    account_id=account_id,
                    email=normalized_email,
                    marketing_consent=marketing_consent,
                    source=normalized_source,
                    created_at=now,
                    updated_at=now,
                )
            else:
                updated = replace(
                    current,
                    email=normalized_email if normalized_email is not None else current.email,
                    marketing_consent=marketing_consent,
                    source=normalized_source,
                    updated_at=now,
                )
            self._profiles[account_id] = updated
            self._persist()
            return updated


def store_from_env(env: Optional[dict[str, str]] = None) -> MarketingProfileStore:
    source = env if env is not None else os.environ
    path = (source.get("DSG_MARKETING_PROFILE_STORE") or "").strip() or None
    return MarketingProfileStore(path)


__all__ = ["MarketingProfile", "MarketingProfileStore", "store_from_env"]
