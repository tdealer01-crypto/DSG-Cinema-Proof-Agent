from __future__ import annotations

import pytest
from fastapi import HTTPException

from api_v1 import (
    azure_local_browser,
    browserbase_executor,
    browserbase_live_ui,
    remote_relay_security,
)


@pytest.mark.asyncio
async def test_self_hosted_dashboard_gets_existing_authenticated_same_origin_viewer(monkeypatch):
    monkeypatch.setenv("DSG_BROWSER_PROVIDER", "self_hosted")
    assert azure_local_browser.configured()

    async def frame(*, x_dsg_api_key=None):
        assert x_dsg_api_key == "account-key"
        return {
            "ok": True,
            "connected": True,
            "provider": "self_hosted_playwright",
            "embed_url": "/remote-browser/self-hosted/view/" + "a" * 32,
            "context_persistent": True,
        }

    monkeypatch.setattr(browserbase_live_ui, "live_frame", frame)
    result = await remote_relay_security.authenticated_live_view(x_dsg_api_key="account-key")
    assert result["connected"] is True
    assert result["live_view_url"] == "https://aws.dsg.pics/remote-browser/self-hosted/view/" + "a" * 32
    assert result["context_persistent"] is True


@pytest.mark.asyncio
async def test_self_hosted_dashboard_does_not_fake_live_view_when_disconnected(monkeypatch):
    monkeypatch.setenv("DSG_BROWSER_PROVIDER", "self_hosted")

    async def frame(*, x_dsg_api_key=None):
        return {"ok": True, "connected": False, "embed_url": None}

    monkeypatch.setattr(browserbase_live_ui, "live_frame", frame)
    result = await remote_relay_security.authenticated_live_view(x_dsg_api_key="account-key")
    assert result["connected"] is False
    assert result["live_view_url"] is None


@pytest.mark.asyncio
async def test_self_hosted_dashboard_blocks_untrusted_viewer_paths(monkeypatch):
    monkeypatch.setenv("DSG_BROWSER_PROVIDER", "self_hosted")

    async def frame(*, x_dsg_api_key=None):
        return {"ok": True, "connected": True, "embed_url": "//evil.example/steal"}

    monkeypatch.setattr(browserbase_live_ui, "live_frame", frame)
    with pytest.raises(HTTPException) as exc:
        await remote_relay_security.authenticated_live_view(x_dsg_api_key="account-key")
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_self_hosted_dashboard_keeps_real_api_key_check(monkeypatch):
    monkeypatch.setenv("DSG_BROWSER_PROVIDER", "self_hosted")

    async def frame(*, x_dsg_api_key=None):
        raise HTTPException(status_code=401, detail="missing authorized account key")

    monkeypatch.setattr(browserbase_live_ui, "live_frame", frame)
    with pytest.raises(HTTPException) as exc:
        await remote_relay_security.authenticated_live_view(x_dsg_api_key=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_browserbase_deployments_keep_previous_live_view_response(monkeypatch):
    monkeypatch.setenv("DSG_BROWSER_PROVIDER", "browserbase")

    async def old_view(*, x_dsg_api_key=None):
        assert x_dsg_api_key == "account-key"
        return {
            "ok": True,
            "connected": True,
            "provider": "browserbase",
            "live_view_url": "https://browserbase.example/session/live",
        }

    monkeypatch.setattr(browserbase_executor, "live_view", old_view)
    result = await remote_relay_security.authenticated_live_view(x_dsg_api_key="account-key")
    assert result["provider"] == "browserbase"
    assert result["live_view_url"] == "https://browserbase.example/session/live"


@pytest.mark.asyncio
async def test_historical_viewer_alias_remains_valid_only_for_aws_same_origin(monkeypatch):
    monkeypatch.setenv("DSG_BROWSER_PROVIDER", "self_hosted")

    async def frame(*, x_dsg_api_key=None):
        assert x_dsg_api_key == "account-key"
        return {"ok": True, "connected": True, "embed_url": "/remote-browser/azure/view/" + "a" * 32}

    monkeypatch.setattr(browserbase_live_ui, "live_frame", frame)
    result = await remote_relay_security.authenticated_live_view(x_dsg_api_key="account-key")
    assert result["live_view_url"] == "https://aws.dsg.pics/remote-browser/azure/view/" + "a" * 32


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_path", [
    "https://evil.example/remote-browser/self-hosted/view/" + "a" * 32,
    "//evil.example/remote-browser/self-hosted/view/" + "a" * 32,
    "/remote-browser/self-hosted/view/" + "a" * 32 + "?redirect=https://evil.example",
    "/remote-browser/self-hosted/view/" + "a" * 32 + "/other",
    "/remote-browser/unknown/view/" + "a" * 32,
])
async def test_self_hosted_viewer_rejects_untrusted_capabilities(monkeypatch, bad_path):
    monkeypatch.setenv("DSG_BROWSER_PROVIDER", "self_hosted")

    async def frame(*, x_dsg_api_key=None):
        return {"ok": True, "connected": True, "embed_url": bad_path}

    monkeypatch.setattr(browserbase_live_ui, "live_frame", frame)
    with pytest.raises(HTTPException) as exc:
        await remote_relay_security.authenticated_live_view(x_dsg_api_key="account-key")
    assert exc.value.status_code == 502
