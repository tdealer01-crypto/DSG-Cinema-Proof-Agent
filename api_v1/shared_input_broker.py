"""One in-process, account-scoped input arbiter for Cinema's existing Chromium.

This is deliberately NOT another browser, authorization path or persisted secret.
Every human viewer mutation and plan-authorized agent mutation must use it.
Human input has priority at the boundary between indivisible Playwright actions.
"""
from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator

from fastapi import HTTPException

_HUMAN_GRACE_SECONDS = 1.25
_AGENT_WAIT_SECONDS = 30.0
_POLL_SECONDS = 0.05
_ACCOUNT_HASH = re.compile(r"[0-9a-f]{64}\Z")


@dataclass
class _AccountInput:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    human_waiters: int = 0
    human_until: float = 0.0


_ACCOUNTS: dict[str, _AccountInput] = {}


def _state(account_hash: str) -> _AccountInput:
    if not isinstance(account_hash, str) or not _ACCOUNT_HASH.fullmatch(account_hash):
        raise HTTPException(status_code=409, detail={"error": "SHARED_BROWSER_ACCOUNT_BINDING_INVALID"})
    return _ACCOUNTS.setdefault(account_hash, _AccountInput())


@asynccontextmanager
async def human_input(account_hash: str) -> AsyncIterator[None]:
    """Prioritize a real viewer's pending action, never record input values."""
    state = _state(account_hash)
    state.human_waiters += 1
    try:
        async with state.lock:
            try:
                yield
            finally:
                state.human_until = time.monotonic() + _HUMAN_GRACE_SECONDS
    finally:
        state.human_waiters -= 1


@asynccontextmanager
async def agent_input(account_hash: str) -> AsyncIterator[None]:
    """Bounded automatic handoff; never preempt a partially applied browser action."""
    state = _state(account_hash)
    deadline = time.monotonic() + _AGENT_WAIT_SECONDS
    while True:
        if time.monotonic() >= deadline:
            raise HTTPException(
                status_code=409,
                detail={"error": "SHARED_BROWSER_USER_ACTIVE", "retryable": True},
            )
        if state.human_waiters or time.monotonic() < state.human_until:
            await asyncio.sleep(_POLL_SECONDS)
            continue
        async with state.lock:
            # Re-check after acquiring the mutex: human requests may have arrived
            # during the await for an earlier agent operation.
            if state.human_waiters or time.monotonic() < state.human_until:
                continue
            yield
            return
