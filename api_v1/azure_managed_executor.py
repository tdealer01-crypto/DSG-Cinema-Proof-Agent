"""Plan-bound executor for Cinema's Azure-native shared Chromium browser.

Capability allocation and signed relay semantics deliberately reuse the proven
managed-browser primitives from ``browserbase_executor``. Only the browser
transport changes: actions operate on the account's in-process Playwright page
instead of a Browserbase CDP session.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import Header, HTTPException

from . import azure_local_browser, browserbase_executor

allocate_capability = browserbase_executor.allocate_capability
finalize_capability = browserbase_executor.finalize_capability
revoke_capability = browserbase_executor.revoke_capability


async def ensure_browser_session(
    cinema_session_id: str,
    *,
    plan_hash: str,
    browser_policy: dict[str, Any],
) -> dict[str, Any]:
    del plan_hash, browser_policy
    return await azure_local_browser.metadata_for_session(cinema_session_id)


async def _perform_action(cinema_session_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    action = payload.get("action") or {}
    context = payload.get("context") or {}
    kind = str(action.get("kind") or "")
    params = action.get("parameters") or {}
    page = await azure_local_browser.page_for_session(cinema_session_id)

    mutation = kind not in browserbase_executor._READ_ONLY_ACTIONS
    if kind != "browser.navigate":
        browserbase_executor._assert_current_origin(page.url, context, mutation=mutation)

    if kind in browserbase_executor._UNSUPPORTED_ACTIONS:
        raise HTTPException(
            status_code=501,
            detail={
                "error": "BROWSER_ACTION_NOT_IMPLEMENTED",
                "message": f"{kind} is not implemented by the Azure Chromium executor.",
            },
        )

    if kind == "browser.navigate":
        url = params.get("url")
        if not isinstance(url, str) or not url:
            raise HTTPException(status_code=400, detail="browser.navigate requires parameters.url")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return 200, {"ok": True, "url": page.url, "title": await page.title()}

    if kind == "browser.extract":
        return 200, {"ok": True, **(await browserbase_executor._extract(page))}

    if kind == "browser.screenshot":
        raw = await page.screenshot(full_page=bool(params.get("full_page") is True))
        digest = hashlib.sha256(raw).hexdigest()
        evidence_dir = azure_local_browser._root() / "evidence" / hashlib.sha256(cinema_session_id.encode()).hexdigest()
        evidence_dir.mkdir(parents=True, exist_ok=True)
        path = evidence_dir / f"{int(time.time() * 1000)}-{digest[:16]}.png"
        path.write_bytes(raw)
        return 200, {
            "ok": True,
            "url": page.url,
            "screenshot_sha256": digest,
            "evidence_ref": f"azure-browser://evidence/{digest}",
        }

    if kind == "browser.click":
        locator = await browserbase_executor._resolve_locator(page, params)
        await locator.click(timeout=15000)
        return 200, {"ok": True, "url": page.url}

    if kind == "browser.type":
        locator = await browserbase_executor._resolve_locator(page, params)
        if await browserbase_executor._sensitive_control(locator):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "DELEGATED_IDENTITY_INPUT_REQUIRED",
                    "message": "Sensitive controls must be completed by the user in the shared browser.",
                },
            )
        value = params.get("value")
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail="browser.type requires parameters.value")
        await locator.fill(value, timeout=15000)
        return 200, {"ok": True, "url": page.url}

    if kind == "browser.select":
        locator = await browserbase_executor._resolve_locator(page, params)
        value = params.get("value")
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail="browser.select requires parameters.value")
        await locator.select_option(label=value, timeout=15000)
        return 200, {"ok": True, "url": page.url}

    if kind == "browser.scroll":
        await page.mouse.wheel(float(params.get("delta_x", 0)), float(params.get("delta_y", params.get("amount", 600))))
        return 200, {"ok": True, "url": page.url}

    if kind == "browser.upload":
        locator = await browserbase_executor._resolve_locator(page, params)
        ref = params.get("file_ref")
        if not isinstance(ref, str) or not ref.startswith("artifact://"):
            raise HTTPException(status_code=400, detail="browser.upload requires an artifact:// file_ref")
        relative = ref[len("artifact://") :].lstrip("/")
        candidate = (Path("/app") / relative).resolve()
        root = Path("/app").resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise HTTPException(status_code=404, detail="approved upload artifact was not found")
        await locator.set_input_files(str(candidate))
        return 200, {
            "ok": True,
            "url": page.url,
            "artifact_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        }

    if kind == "pointer.move":
        await page.mouse.move(float(params.get("x", 0)), float(params.get("y", 0)))
        return 200, {"ok": True, "url": page.url}

    if kind == "pointer.click":
        await page.mouse.click(float(params.get("x", 0)), float(params.get("y", 0)))
        return 200, {"ok": True, "url": page.url}

    if kind == "pointer.drag":
        sx, sy = float(params.get("start_x", 0)), float(params.get("start_y", 0))
        ex, ey = float(params.get("end_x", 0)), float(params.get("end_y", 0))
        await page.mouse.move(sx, sy)
        await page.mouse.down()
        await page.mouse.move(ex, ey, steps=10)
        await page.mouse.up()
        return 200, {"ok": True, "url": page.url}

    if kind == "keyboard.type":
        text = params.get("text")
        if not isinstance(text, str):
            raise HTTPException(status_code=400, detail="keyboard.type requires parameters.text")
        await page.keyboard.type(text)
        return 200, {"ok": True, "url": page.url}

    if kind == "keyboard.press":
        key = params.get("key")
        if not isinstance(key, str) or not key:
            raise HTTPException(status_code=400, detail="keyboard.press requires parameters.key")
        await page.keyboard.press(key)
        return 200, {"ok": True, "url": page.url}

    if kind == "identity.confirmation.click":
        locator = await browserbase_executor._resolve_locator(page, params)
        await locator.click(timeout=15000)
        return 200, {"ok": True, "url": page.url, "confirmed": True}

    if kind in {"identity.secret.inject", "identity.otp.submit"}:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "USER_SHARED_BROWSER_INPUT_REQUIRED",
                "message": (
                    "Automatic secret/OTP injection is not enabled. The user can enter the value "
                    "directly in the shared Cinema browser without exposing it to the agent."
                ),
            },
        )

    raise HTTPException(
        status_code=400,
        detail={"error": "UNKNOWN_BROWSER_ACTION", "message": f"Unsupported action {kind}"},
    )


async def azure_action(capability_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    capability = browserbase_executor._load_capability(capability_token)
    cinema_session_id = browserbase_executor._validate_envelope(capability, payload)
    await ensure_browser_session(
        cinema_session_id,
        plan_hash=str(capability["plan_hash"]),
        browser_policy=dict(capability.get("browser_policy") or {}),
    )

    kind = str((payload.get("action") or {}).get("kind") or "")
    if kind in browserbase_executor._READ_ONLY_ACTIONS:
        status, body = await _perform_action(cinema_session_id, payload)
    else:
        lock = browserbase_executor._MUTATION_LOCKS.setdefault(cinema_session_id, asyncio.Lock())
        async with lock:
            status, body = await _perform_action(cinema_session_id, payload)
    await azure_local_browser.save_session(cinema_session_id)
    body["remote_status"] = status
    body["provider"] = azure_local_browser.PROVIDER
    return body


async def live_view(x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key")) -> dict[str, Any]:
    from . import remote_pairing

    key = remote_pairing._api_key(x_dsg_api_key)
    account_id = remote_pairing._account_id(key)
    return {"ok": True, **(await azure_local_browser.current_shared_browser(account_id, create=False))}


__all__ = [
    "allocate_capability",
    "azure_action",
    "ensure_browser_session",
    "finalize_capability",
    "live_view",
    "revoke_capability",
]
