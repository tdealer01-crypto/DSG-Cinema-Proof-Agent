from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_v1 import browser_memory, browser_memory_runtime, remote_mcp


class FakeCursor:
    def __init__(self, *, search_rows=None):
        self.executed: list[tuple[str, tuple | None]] = []
        self._one = None
        self._rows = list(search_rows or [])

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=None):
        text = str(query)
        self.executed.append((text, params))
        if "MAX(version)" in text:
            self._one = (0,)
        elif "RETURNING memory_id" in text:
            self._one = ("bm_existing",)
        elif "SUM(token_estimate)" in text:
            self._one = (1_250_000, 42_000)
        else:
            self._one = None

    def fetchone(self):
        assert self._one is not None
        return self._one

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self, *, search_rows=None):
        self.cursor_obj = FakeCursor(search_rows=search_rows)
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1


def test_database_url_prefers_memory_database_and_falls_back(monkeypatch):
    monkeypatch.delenv("DSG_BROWSER_MEMORY_DATABASE_URL", raising=False)
    monkeypatch.delenv("DSG_REVENUE_DATABASE_URL", raising=False)
    assert browser_memory.database_url() is None
    assert browser_memory.configured() is False

    monkeypatch.setenv("DSG_REVENUE_DATABASE_URL", "postgresql://revenue")
    assert browser_memory.database_url() == "postgresql://revenue"
    monkeypatch.setenv("DSG_BROWSER_MEMORY_DATABASE_URL", "postgresql://memory")
    assert browser_memory.database_url() == "postgresql://memory"


def test_safe_url_origin_and_secret_rejection():
    assert browser_memory._safe_url("https://User:Pass@GitHub.COM:443/acme/repo?q=secret#frag") == "https://github.com/acme/repo"
    assert browser_memory._origin("https://GitHub.com/a?x=1") == "https://github.com"
    assert browser_memory._safe_url("file:///etc/passwd") is None
    assert browser_memory._safe_url("not a url") is None

    browser_memory._assert_safe({"title": "GitHub Actions", "nested": ["safe"]})
    with pytest.raises(ValueError, match="sensitive field"):
        browser_memory._assert_safe({"password": "never"})
    with pytest.raises(ValueError, match="secret-like text"):
        browser_memory._assert_safe({"note": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz"})
    with pytest.raises(ValueError, match="secret-like text"):
        browser_memory._assert_safe("api_key=abcdefghijklmnop")


def test_token_estimate_and_ttl(monkeypatch):
    assert browser_memory._token_estimate("") == 1
    assert browser_memory._token_estimate("abcdefgh") == 2
    monkeypatch.setenv("DSG_BROWSER_MEMORY_TTL_DAYS", "0")
    assert browser_memory._expires_at() is None
    monkeypatch.setenv("DSG_BROWSER_MEMORY_TTL_DAYS", "not-a-number")
    assert browser_memory._expires_at() is not None
    monkeypatch.setenv("DSG_BROWSER_MEMORY_TTL_DAYS", "99999")
    expiry = browser_memory._expires_at()
    assert expiry is not None and expiry.endswith("Z")


def test_initialize_schema_rejects_future_schema():
    connection = FakeConnection()
    original_execute = connection.cursor_obj.execute

    def execute(query, params=None):
        original_execute(query, params)
        if "MAX(version)" in str(query):
            connection.cursor_obj._one = (browser_memory.SCHEMA_VERSION + 1,)

    connection.cursor_obj.execute = execute
    with pytest.raises(RuntimeError, match="newer"):
        browser_memory.initialize_schema(connection)


def test_record_observation_is_optional_when_database_unconfigured(monkeypatch):
    monkeypatch.delenv("DSG_BROWSER_MEMORY_DATABASE_URL", raising=False)
    monkeypatch.delenv("DSG_REVENUE_DATABASE_URL", raising=False)
    assert browser_memory.record_observation(
        account_hash="a" * 64,
        provider="azure_container_apps",
        logical_browser_id="azure-a",
        url="https://example.com",
        source="USER_OBSERVED",
        actor="USER",
        action="user.navigate",
    ) is None


def test_record_observation_sanitizes_and_writes_profile_memory_event(monkeypatch):
    monkeypatch.setenv("DSG_BROWSER_MEMORY_DATABASE_URL", "postgresql://memory")
    connection = FakeConnection()
    monkeypatch.setattr(browser_memory, "_connect", lambda: connection)

    memory_id = browser_memory.record_observation(
        account_hash="a" * 64,
        provider="azure_container_apps",
        logical_browser_id="azure-user",
        url="https://Example.COM/work?q=private#secret",
        title="Work page",
        source="USER_OBSERVED",
        actor="USER",
        action="user.navigate",
        project_id="cinema",
        importance=150,
    )
    assert memory_id == "bm_existing"
    assert connection.commits >= 2
    sql = "\n".join(query for query, _ in connection.cursor_obj.executed)
    assert "dsg_browser_profiles" in sql
    assert "dsg_browser_memory" in sql
    assert "dsg_browser_memory_events" in sql
    memory_insert = next(params for query, params in connection.cursor_obj.executed if "RETURNING memory_id" in query)
    assert memory_insert is not None
    assert "https://example.com/work" in str(memory_insert)
    assert "q=private" not in str(memory_insert)
    assert 100 in memory_insert


def test_record_observation_validates_source_and_url(monkeypatch):
    monkeypatch.setenv("DSG_BROWSER_MEMORY_DATABASE_URL", "postgresql://memory")
    with pytest.raises(ValueError, match="unknown"):
        browser_memory.record_observation(
            account_hash="a" * 64,
            provider="azure_container_apps",
            logical_browser_id="azure-user",
            url="https://example.com",
            source="MODEL_GUESSED",
            actor="AGENT",
            action="browser.navigate",
        )
    assert browser_memory.record_observation(
        account_hash="a" * 64,
        provider="azure_container_apps",
        logical_browser_id="azure-user",
        url="file:///tmp/x",
        source="SYSTEM_OBSERVED",
        actor="SYSTEM",
        action="observe",
    ) is None


def test_search_context_reports_million_token_store_and_bounds_active_context(monkeypatch):
    monkeypatch.setenv("DSG_BROWSER_MEMORY_DATABASE_URL", "postgresql://memory")
    now = datetime.now(timezone.utc)
    rows = [
        ("bm1", "cinema", "https://github.com", "navigation", "nav:1", {"url": "https://github.com/a", "title": "A"}, "USER_OBSERVED", 1.0, 90, 900, "h1", now),
        ("bm2", "cinema", "https://github.com", "deployment_state", "deploy:1", '{"url":"https://github.com/b","title":"B"}', "AGENT_OBSERVED", 0.9, 80, 900, "h2", now),
        ("bm3", None, "https://example.com", "navigation", "nav:3", {"url": "https://example.com"}, "SYSTEM_OBSERVED", 1.0, 20, 900, "h3", now),
    ]
    connection = FakeConnection(search_rows=rows)
    monkeypatch.setattr(browser_memory, "_connect", lambda: connection)

    result = browser_memory.search_context(
        account_hash="a" * 64,
        query="deploy",
        project_id="cinema",
        origin="https://github.com/path?q=ignored",
        token_budget=1500,
        limit=9999,
    )
    assert result["available"] is True
    assert result["stored_token_estimate"] == 1_250_000
    assert result["stored_memory_count"] == 42_000
    assert result["token_budget"] == 1500
    assert len(result["memories"]) == 1
    assert result["memories"][0]["memory_id"] == "bm1"
    assert result["memories"][0]["requires_live_verification"] is False
    assert "context, not current authorization" in result["truth_boundary"]
    search_params = connection.cursor_obj.executed[-1][1]
    assert search_params is not None
    assert "https://github.com" in search_params
    assert 500 in search_params


def test_search_context_unconfigured_and_budget_clamps(monkeypatch):
    monkeypatch.delenv("DSG_BROWSER_MEMORY_DATABASE_URL", raising=False)
    monkeypatch.delenv("DSG_REVENUE_DATABASE_URL", raising=False)
    result = browser_memory.search_context(account_hash="a" * 64, token_budget=999_999, limit=0)
    assert result == {
        "available": False,
        "stored_token_estimate": 0,
        "selected_token_estimate": 0,
        "token_budget": browser_memory.MAX_ACTIVE_TOKEN_BUDGET,
        "memories": [],
    }


def test_user_capture_descriptor_never_copies_keyboard_input(monkeypatch):
    from api_v1 import browserbase_live_ui

    monkeypatch.setattr(
        browserbase_live_ui,
        "_load_viewer",
        lambda _token: {"provider": "azure_container_apps", "account_hash": "a" * 64},
    )
    descriptor = browser_memory_runtime._capture_descriptor(
        "/remote-browser/azure/view/viewer/action",
        {"kind": "navigate", "parameters": {"url": "https://example.com"}},
    )
    assert descriptor is not None
    assert descriptor["actor"] == "USER"
    assert descriptor["action"] == "user.navigate"
    assert browser_memory_runtime._capture_descriptor(
        "/remote-browser/azure/view/viewer/action",
        {"kind": "type", "parameters": {"text": "do-not-store-this"}},
    ) is None
    assert browser_memory_runtime._capture_descriptor("/other", {}) is None


def test_agent_descriptor_requires_live_azure_binding(monkeypatch):
    monkeypatch.setattr(
        browser_memory_runtime.remote_browser,
        "_open",
        lambda _token: {"sid": "rbs_1", "plan_id": "plan1", "step_id": "step1"},
    )
    monkeypatch.setattr(browser_memory_runtime.remote_browser, "_is_revoked", lambda _sid: False)
    monkeypatch.setattr(
        browser_memory_runtime.browserbase_executor,
        "_read_binding",
        lambda _sid: {"provider": "azure_local", "account_hash": "b" * 64},
    )
    descriptor = browser_memory_runtime._agent_descriptor(
        "sealed", {"kind": "browser.navigate", "parameters": {"url": "https://example.com"}}
    )
    assert descriptor is not None
    assert descriptor["plan_id"] == "plan1"
    assert descriptor["importance"] == 65

    monkeypatch.setattr(browser_memory_runtime.remote_browser, "_is_revoked", lambda _sid: True)
    assert browser_memory_runtime._agent_descriptor("sealed", {"kind": "browser.click"}) is None
    assert browser_memory_runtime._agent_descriptor(None, {}) is None


def test_latest_page_and_persist_descriptor(monkeypatch):
    monkeypatch.setattr(
        browser_memory_runtime.azure_local_browser,
        "_read_metadata",
        lambda _hash: {
            "browser_session_id": "azure-1",
            "last_pages": [{"url": "https://example.com/a", "title": "Example"}],
        },
    )
    observed = []
    monkeypatch.setattr(browser_memory_runtime.browser_memory, "record_observation", lambda **kwargs: observed.append(kwargs) or "bm1")
    descriptor = {
        "account_hash": "c" * 64,
        "source": "AGENT_OBSERVED",
        "actor": "AGENT_EXECUTOR",
        "action": "browser.click",
        "plan_id": "p",
        "step_id": "s",
        "project_id": None,
        "importance": 50,
    }
    browser_memory_runtime._persist_descriptor(descriptor)
    assert observed[0]["logical_browser_id"] == "azure-1"
    assert observed[0]["url"] == "https://example.com/a"

    monkeypatch.setattr(browser_memory_runtime.azure_local_browser, "_read_metadata", lambda _hash: {"last_pages": []})
    assert browser_memory_runtime._latest_page("c" * 64) is None


def test_memory_routes_and_middleware(monkeypatch):
    authorization = SimpleNamespace(account=SimpleNamespace(account_id="acct-memory"))
    monkeypatch.setattr(browser_memory_runtime.remote_pairing.billing, "authorize_request", lambda *_args, **_kwargs: authorization)
    monkeypatch.setattr(browser_memory_runtime.browser_memory, "configured", lambda: True)
    monkeypatch.setattr(
        browser_memory_runtime.browser_memory,
        "search_context",
        lambda **kwargs: {
            "available": True,
            "stored_memory_count": 12,
            "stored_token_estimate": 1_100_000,
            "selected_token_estimate": 3,
            "token_budget": kwargs.get("token_budget"),
            "memories": [],
        },
    )
    persisted = []
    monkeypatch.setattr(browser_memory_runtime, "_capture_descriptor", lambda _path, _body: {"account_hash": "a" * 64})
    monkeypatch.setattr(browser_memory_runtime, "_persist_descriptor", lambda descriptor: persisted.append(descriptor))

    app = FastAPI()
    app.add_middleware(browser_memory_runtime.BrowserMemoryCaptureMiddleware)
    app.include_router(browser_memory_runtime.router)

    @app.post("/remote-browser/actions")
    async def action():
        return {"ok": True}

    client = TestClient(app)
    headers = {"X-DSG-API-Key": "dsg_live_test"}
    status = client.get("/remote-browser/memory/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["stored_token_estimate"] == 1_100_000
    context = client.post(
        "/remote-browser/memory/context",
        headers=headers,
        json={"query": "github", "token_budget": 50000, "limit": 20},
    )
    assert context.status_code == 200
    assert context.json()["available"] is True
    acted = client.post("/remote-browser/actions", json={"session_token": "x", "action": {"kind": "browser.click"}})
    assert acted.status_code == 200
    assert persisted


def test_install_mcp_tools_is_idempotent(monkeypatch):
    old_tools = remote_mcp.TOOLS
    old_by_name = dict(remote_mcp._BY_NAME)
    try:
        remote_mcp.TOOLS = tuple(tool for tool in old_tools if tool.name not in {"browser_memory_context", "browser_memory_status"})
        remote_mcp._BY_NAME = {name: tool for name, tool in old_by_name.items() if name not in {"browser_memory_context", "browser_memory_status"}}
        browser_memory_runtime.install_mcp_tools()
        names = [tool.name for tool in remote_mcp.TOOLS]
        assert names.count("browser_memory_context") == 1
        assert names.count("browser_memory_status") == 1
        browser_memory_runtime.install_mcp_tools()
        assert [tool.name for tool in remote_mcp.TOOLS].count("browser_memory_context") == 1
    finally:
        remote_mcp.TOOLS = old_tools
        remote_mcp._BY_NAME = old_by_name
