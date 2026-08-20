"""Customer accounts, API keys, and entitlement state.

An API key is `dsg_<mode>_<key_id>_<secret>`. Only the SHA-256 of the secret is
stored, so a leaked store cannot be replayed against the API. The plaintext key
is returned exactly once, at issue time.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .pricing import DEFAULT_PLAN, get_plan

KEY_PATTERN = re.compile(r"^dsg_(live|test)_([0-9a-f]{16})_([0-9a-f]{48})$")

STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"
STATUS_CLOSED = "closed"

_VALID_STATUSES = {STATUS_ACTIVE, STATUS_SUSPENDED, STATUS_CLOSED}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


@dataclass
class Account:
    account_id: str
    display_name: str
    plan: str = DEFAULT_PLAN
    status: str = STATUS_ACTIVE
    channel: str = "api"
    key_id: str = ""
    secret_hash: str = ""
    mode: str = "live"
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    payment_linked: bool = False
    unit_price_micros: Optional[int] = None
    hard_cap_units: Optional[int] = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return asdict(self)

    def public_view(self) -> dict:
        """Account fields that are safe to return to the account holder."""
        return {
            "account_id": self.account_id,
            "display_name": self.display_name,
            "plan": self.plan,
            "status": self.status,
            "channel": self.channel,
            "mode": self.mode,
            "payment_linked": self.payment_linked,
            "unit_price_micros": self.unit_price_micros,
            "hard_cap_units": self.hard_cap_units,
            "created_at": self.created_at,
        }


class AccountStore:
    """Account registry with an optional JSON file mirror."""

    def __init__(self, path: Optional[str] = None) -> None:
        self._lock = threading.Lock()
        self._accounts: dict[str, Account] = {}
        self._by_key_id: dict[str, str] = {}
        self._path = Path(path) if path else None
        if self._path and self._path.exists():
            self._load()

    def _load(self) -> None:
        assert self._path is not None
        raw = json.loads(self._path.read_text(encoding="utf-8") or "[]")
        for item in raw:
            account = Account(**item)
            self._accounts[account.account_id] = account
            if account.key_id:
                self._by_key_id[account.key_id] = account.account_id

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps([a.to_dict() for a in self._accounts.values()], indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self._path)

    # ---------------------------------------------------------------- lookups
    def get(self, account_id: str) -> Optional[Account]:
        with self._lock:
            return self._accounts.get(account_id)

    def all(self) -> list[Account]:
        with self._lock:
            return list(self._accounts.values())

    def find_by_stripe_customer(self, customer_id: str) -> Optional[Account]:
        with self._lock:
            for account in self._accounts.values():
                if account.stripe_customer_id == customer_id:
                    return account
        return None

    def authenticate(self, api_key: str) -> Optional[Account]:
        """Return the account for a presented key, or None.

        The secret comparison is constant time and the key format is validated
        before any lookup, so malformed input cannot probe the registry.
        """
        if not api_key:
            return None
        match = KEY_PATTERN.match(api_key.strip())
        if not match:
            return None
        mode, key_id, secret = match.groups()

        with self._lock:
            account_id = self._by_key_id.get(key_id)
            account = self._accounts.get(account_id) if account_id else None

        if account is None or account.mode != mode:
            return None
        if not hmac.compare_digest(account.secret_hash, hash_secret(secret)):
            return None
        return account

    # ----------------------------------------------------------------- writes
    def issue(
        self,
        *,
        display_name: str,
        plan: str = DEFAULT_PLAN,
        channel: str = "api",
        mode: str = "live",
        stripe_customer_id: Optional[str] = None,
        unit_price_micros: Optional[int] = None,
        hard_cap_units: Optional[int] = None,
    ) -> tuple[Account, str]:
        """Create an account and return it with its one-time plaintext key."""
        get_plan(plan)
        if mode not in {"live", "test"}:
            raise ValueError("mode must be live or test")

        key_id = secrets.token_hex(8)
        secret = secrets.token_hex(24)
        api_key = f"dsg_{mode}_{key_id}_{secret}"
        account = Account(
            account_id=f"acct_dsg_{secrets.token_hex(8)}",
            display_name=display_name,
            plan=plan,
            channel=channel,
            key_id=key_id,
            secret_hash=hash_secret(secret),
            mode=mode,
            stripe_customer_id=stripe_customer_id,
            unit_price_micros=unit_price_micros,
            hard_cap_units=hard_cap_units,
        )

        with self._lock:
            self._accounts[account.account_id] = account
            self._by_key_id[key_id] = account.account_id
            self._persist()
        return account, api_key

    def update(self, account_id: str, **changes) -> Account:
        allowed = {
            "plan",
            "status",
            "stripe_customer_id",
            "stripe_subscription_id",
            "payment_linked",
            "unit_price_micros",
            "hard_cap_units",
            "display_name",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"cannot update fields: {sorted(unknown)}")
        if "plan" in changes:
            get_plan(changes["plan"])
        if "status" in changes and changes["status"] not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {changes['status']}")

        with self._lock:
            account = self._accounts.get(account_id)
            if account is None:
                raise KeyError(account_id)
            updated = replace(account, **changes, updated_at=utc_now())
            self._accounts[account_id] = updated
            if updated.key_id:
                self._by_key_id[updated.key_id] = account_id
            self._persist()
            return updated

    def import_account(self, account: Account) -> Account:
        """Register a pre-built account (bootstrap from configuration)."""
        get_plan(account.plan)
        if account.status not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {account.status}")
        with self._lock:
            self._accounts[account.account_id] = account
            if account.key_id:
                self._by_key_id[account.key_id] = account.account_id
            self._persist()
            return account


def accounts_from_env(value: str) -> list[Account]:
    """Build bootstrap accounts from a JSON array in an environment variable.

    Each item must carry `account_id`, `display_name`, `key_id`, and
    `secret_hash`. Plaintext secrets are never accepted here.
    """
    items = json.loads(value)
    if not isinstance(items, list):
        raise ValueError("DSG_REVENUE_ACCOUNTS must be a JSON array")

    accounts: list[Account] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each bootstrap account must be a JSON object")
        if "api_key" in item or "secret" in item:
            raise ValueError("bootstrap accounts must carry secret_hash, not a secret")
        missing = {"account_id", "display_name", "key_id", "secret_hash"} - set(item)
        if missing:
            raise ValueError(f"bootstrap account is missing {sorted(missing)}")
        accounts.append(Account(**item))
    return accounts
