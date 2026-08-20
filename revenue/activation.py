"""Self-serve, channel-attributed activation.

This is the join between a sales channel and delivered value: someone who finds
the product on GitHub, Stripe, or an agent marketplace can obtain a working key
and a real proof without a human in the loop.

Three properties keep that safe:

- **Idempotent.** Activation is keyed on (channel, activation_id), so a retry
  never silently creates a second account.
- **Rate limited.** A sliding window caps activations per channel and overall,
  so one source cannot exhaust free capacity.
- **Free tier only.** Activation issues the free plan and nothing else. Paid
  plans still require Stripe, so activation can never grant billable entitlement.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

from .accounts import Account, AccountStore
from .remediation import (
    ACTIVATION_DISABLED,
    ACTIVATION_EXISTS,
    ACTIVATION_RATE_LIMITED,
    Remediation,
    remediation_for,
)

ACTIVATION_PLAN = "free"

DEFAULT_WINDOW_SECONDS = 3600
DEFAULT_PER_CHANNEL_LIMIT = 20
DEFAULT_GLOBAL_LIMIT = 100

ACTIVATED = "ACTIVATED"


def activation_ref(channel: str, activation_id: str) -> str:
    """Stable, non-reversible reference for one (channel, activation_id) pair."""
    raw = f"{channel}|{activation_id.strip().lower()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ActivationResult:
    decision: str
    account: Optional[Account]
    api_key: Optional[str]
    remediation: Remediation
    retry_after_seconds: Optional[int] = None

    @property
    def activated(self) -> bool:
        return self.decision == ACTIVATED

    @property
    def http_status(self) -> int:
        return {
            ACTIVATED: 201,
            ACTIVATION_EXISTS: 409,
            ACTIVATION_RATE_LIMITED: 429,
            ACTIVATION_DISABLED: 503,
        }.get(self.decision, 400)


class RateLimiter:
    """Sliding-window counter on a monotonic clock."""

    def __init__(
        self,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        per_channel_limit: int = DEFAULT_PER_CHANNEL_LIMIT,
        global_limit: int = DEFAULT_GLOBAL_LIMIT,
    ) -> None:
        self._lock = threading.Lock()
        self._window = window_seconds
        self._per_channel = per_channel_limit
        self._global = global_limit
        self._events: list[tuple[float, str]] = []

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        self._events = [event for event in self._events if event[0] > cutoff]

    def check(self, channel: str, now: Optional[float] = None) -> Optional[int]:
        """Return None when allowed, or the seconds to wait when limited."""
        current = time.monotonic() if now is None else now
        with self._lock:
            self._prune(current)

            channel_events = [event for event in self._events if event[1] == channel]
            if len(channel_events) >= self._per_channel:
                oldest = min(event[0] for event in channel_events)
                return max(int(self._window - (current - oldest)), 1)

            if len(self._events) >= self._global:
                oldest = min(event[0] for event in self._events)
                return max(int(self._window - (current - oldest)), 1)

            return None

    def record(self, channel: str, now: Optional[float] = None) -> None:
        current = time.monotonic() if now is None else now
        with self._lock:
            self._prune(current)
            self._events.append((current, channel))


class ActivationService:
    def __init__(
        self,
        accounts: AccountStore,
        limiter: Optional[RateLimiter] = None,
        enabled: bool = True,
    ) -> None:
        self.accounts = accounts
        self.limiter = limiter or RateLimiter()
        self.enabled = enabled

    @classmethod
    def from_env(
        cls,
        accounts: AccountStore,
        env: Optional[dict] = None,
    ) -> "ActivationService":
        source = env if env is not None else os.environ

        def integer(name: str, default: int) -> int:
            raw = (source.get(name) or "").strip()
            if not raw:
                return default
            try:
                value = int(raw)
            except ValueError:
                return default
            return value if value > 0 else default

        enabled = (source.get("DSG_ACTIVATION_ENABLED") or "1").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        limiter = RateLimiter(
            window_seconds=integer("DSG_ACTIVATION_WINDOW_SECONDS", DEFAULT_WINDOW_SECONDS),
            per_channel_limit=integer("DSG_ACTIVATION_CHANNEL_LIMIT", DEFAULT_PER_CHANNEL_LIMIT),
            global_limit=integer("DSG_ACTIVATION_GLOBAL_LIMIT", DEFAULT_GLOBAL_LIMIT),
        )
        return cls(accounts=accounts, limiter=limiter, enabled=enabled)

    def find_existing(self, channel: str, activation_id: str) -> Optional[Account]:
        reference = activation_ref(channel, activation_id)
        for account in self.accounts.all():
            if account.activation_ref == reference:
                return account
        return None

    def activate(
        self,
        *,
        channel: str,
        activation_id: str,
        display_name: str,
    ) -> ActivationResult:
        if not self.enabled:
            return ActivationResult(
                decision=ACTIVATION_DISABLED,
                account=None,
                api_key=None,
                remediation=remediation_for(ACTIVATION_DISABLED),
            )

        existing = self.find_existing(channel, activation_id)
        if existing is not None:
            return ActivationResult(
                decision=ACTIVATION_EXISTS,
                account=existing,
                api_key=None,
                remediation=remediation_for(ACTIVATION_EXISTS),
            )

        retry_after = self.limiter.check(channel)
        if retry_after is not None:
            return ActivationResult(
                decision=ACTIVATION_RATE_LIMITED,
                account=None,
                api_key=None,
                remediation=remediation_for(ACTIVATION_RATE_LIMITED),
                retry_after_seconds=retry_after,
            )

        account, api_key = self.accounts.issue(
            display_name=display_name,
            plan=ACTIVATION_PLAN,
            channel=channel,
            activation_ref=activation_ref(channel, activation_id),
        )
        self.limiter.record(channel)

        return ActivationResult(
            decision=ACTIVATED,
            account=account,
            api_key=api_key,
            remediation=remediation_for("OK"),
        )
