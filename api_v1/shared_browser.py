"""Provider-neutral account shared-browser facade."""

from __future__ import annotations

from typing import Any

from . import azure_local_browser, browserbase_shared_profile


def provider() -> str:
    if azure_local_browser.configured():
        return azure_local_browser.PROVIDER
    return "browserbase"


def configured() -> bool:
    return azure_local_browser.configured() or browserbase_shared_profile.configured()


async def ensure_shared_browser(account_id: str) -> dict[str, Any]:
    if azure_local_browser.configured():
        return await azure_local_browser.ensure_shared_browser(account_id)
    return await browserbase_shared_profile.ensure_shared_browser(account_id)


async def current_shared_browser(account_id: str, *, create: bool = False) -> dict[str, Any]:
    if azure_local_browser.configured():
        return await azure_local_browser.current_shared_browser(account_id, create=create)
    return await browserbase_shared_profile.current_shared_browser(account_id, create=create)


async def bind_cinema_session(account_id: str, cinema_session_id: str, *, plan_hash: str) -> dict[str, Any]:
    if azure_local_browser.configured():
        return await azure_local_browser.bind_cinema_session(
            account_id,
            cinema_session_id,
            plan_hash=plan_hash,
        )
    return await browserbase_shared_profile.bind_cinema_session(
        account_id,
        cinema_session_id,
        plan_hash=plan_hash,
    )


__all__ = [
    "bind_cinema_session",
    "configured",
    "current_shared_browser",
    "ensure_shared_browser",
    "provider",
]
