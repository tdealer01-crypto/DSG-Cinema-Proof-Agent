from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api_v1 import azure_local_browser, browserbase_executor


class FakeMouse:
    def __init__(self):
        self.calls = []

    async def click(self, x, y):
        self.calls.append(("click", x, y))

    async def wheel(self, x, y):
        self.calls.append(("wheel", x, y))

    async def move(self, x, y, **kwargs):
        self.calls.append(("move", x, y, kwargs))

    async def down(self):
        self.calls.append(("down",))

    async def up(self):
        self.calls.append(("up",))


class FakeKeyboard:
    def __init__(self):
        self.calls = []

    async def type(self, text):
        self.calls.append(("type", text))

    async def press(self, key):
        self.calls.append(("press", key))


class FakePage:
    def __init__(self, url="about:blank", title=""):
        self.url = url
        self._title = title
        self.mouse = FakeMouse()
        self.keyboard = FakeKeyboard()
        self.goto_calls = []
        self.waits = []

    async def title(self):
        return self._title

    async def goto(self, url, **kwargs):
        self.goto_calls.append((url, kwargs))
        self.url = url
        self._title = "Example Domain" if "example.com" in url else "Page"

    async def wait_for_timeout(self, ms):
        self.waits.append(ms)

    async def go_back(self, **kwargs):
        self.url = "https://example.com/back"

    async def go_forward(self, **kwargs):
        self.url = "https://example.com/forward"

    async def reload(self, **kwargs):
        self.url = self.url

    async def screenshot(self, **kwargs):
        return b"fake-png"


class FakeContext:
    def __init__(self, pages=None):
        self.pages = list(pages or [])
        self.storage_calls = 0

    async def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page

    async def storage_state(self):
        self.storage_calls += 1
        return {"cookies": [{"name": "sid", "value": "secret-cookie"}], "origins": []}


class FakeBrowser:
    def __init__(self, context):
        self.context = context
        self.kwargs = []
        self.connected = True

    def is_connected(self):
        return self.connected

    async def new_context(self, **kwargs):
        self.kwargs.append(kwargs)
        return self.context


@pytest.fixture(autouse=True)
def reset_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "store"))
    monkeypatch.setenv("DSG_BROWSER_PROVIDER", "azure_local")
    azure_local_browser._PLAYWRIGHT = None
    azure_local_browser._BROWSER = None
    azure_local_browser._CONTEXTS.clear()
    azure_local_browser._LOCKS.clear()
    yield
    azure_local_browser._PLAYWRIGHT = None
    azure_local_browser._BROWSER = None
    azure_local_browser._CONTEXTS.clear()
    azure_local_browser._LOCKS.clear()


def test_safe_url_and_provider_configuration(monkeypatch: pytest.MonkeyPatch):
    assert azure_local_browser.configured() is True
    for value in ("azure", "self_hosted"):
        monkeypatch.setenv("DSG_BROWSER_PROVIDER", value)
        assert azure_local_browser.configured() is True
    monkeypatch.setenv("DSG_BROWSER_PROVIDER", "browserbase")
    assert azure_local_browser.configured() is False
    assert azure_local_browser._safe_url("https://EXAMPLE.com:443/a?secret=1#x") == "https://example.com/a"
    assert azure_local_browser._safe_url("http://example.com:8080/a?q=1") == "http://example.com:8080/a"
    assert azure_local_browser._safe_url("about:blank") is None
    assert azure_local_browser._safe_url("https://[") is None


def test_metadata_roundtrip_and_invalid_files():
    account_hash = azure_local_browser.account_digest("acct")
    fresh = azure_local_browser._read_metadata(account_hash)
    assert fresh["browser_session_id"].startswith("azure-")
    azure_local_browser._atomic_json(azure_local_browser._metadata_path(account_hash), fresh)
    assert azure_local_browser._read_metadata(account_hash)["browser_session_id"] == fresh["browser_session_id"]

    azure_local_browser._metadata_path(account_hash).write_text("not-json", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        azure_local_browser._read_metadata(account_hash)
    assert exc.value.status_code == 503

    azure_local_browser._metadata_path(account_hash).write_text("[]", encoding="utf-8")
    with pytest.raises(HTTPException):
        azure_local_browser._read_metadata(account_hash)


@pytest.mark.asyncio
async def test_context_creation_restore_checkpoint_observe_and_current(monkeypatch: pytest.MonkeyPatch):
    account_hash = azure_local_browser.account_digest("acct")
    page = FakePage("https://example.com/path?q=secret#frag", "Example")
    context = FakeContext([page])
    browser = FakeBrowser(context)

    async def fake_engine():
        return browser

    monkeypatch.setattr(azure_local_browser, "_ensure_engine", fake_engine)
    created = await azure_local_browser._context(account_hash)
    assert created is context
    assert await azure_local_browser._context(account_hash) is context
    assert (await azure_local_browser._page_for_hash(account_hash)) is page

    await azure_local_browser._checkpoint(account_hash)
    state = json.loads(azure_local_browser._storage_state_path(account_hash).read_text(encoding="utf-8"))
    assert state["cookies"][0]["name"] == "sid"

    observed = await azure_local_browser._observe(account_hash)
    assert observed["last_pages"] == [{"url": "https://example.com/path", "title": "Example"}]
    observed_again = await azure_local_browser._observe(account_hash)
    assert len(observed_again["history"]) == 1

    current = await azure_local_browser.current_shared_browser("acct", create=False)
    assert current["provider"] == "azure_container_apps"
    assert current["connected"] is True
    assert current["context_persistent"] is True
    assert current["continuity"]["privacy"].startswith("URL/title only")

    azure_local_browser._CONTEXTS.clear()
    restored_context = FakeContext([FakePage()])
    restored_browser = FakeBrowser(restored_context)

    async def restored_engine():
        return restored_browser

    monkeypatch.setattr(azure_local_browser, "_ensure_engine", restored_engine)
    await azure_local_browser._context(account_hash)
    assert restored_browser.kwargs[0]["storage_state"] == str(azure_local_browser._storage_state_path(account_hash))


@pytest.mark.asyncio
async def test_context_creates_page_and_high_level_binding(monkeypatch: pytest.MonkeyPatch):
    account_hash = azure_local_browser.account_digest("acct-bind")
    context = FakeContext([])
    browser = FakeBrowser(context)

    async def fake_engine():
        return browser

    monkeypatch.setattr(azure_local_browser, "_ensure_engine", fake_engine)
    shared = await azure_local_browser.ensure_shared_browser("acct-bind")
    assert shared["connected"] is True
    assert len(context.pages) == 1

    bound = await azure_local_browser.bind_cinema_session("acct-bind", "rbs_bind", plan_hash="f" * 64)
    assert bound["browser_session_id"] == shared["browser_session_id"]
    binding = browserbase_executor._read_binding("rbs_bind")
    assert binding["provider"] == "azure_local"
    assert binding["plan_hash"] == "f" * 64
    assert await azure_local_browser.page_for_session("rbs_bind") is context.pages[-1]
    metadata = await azure_local_browser.metadata_for_session("rbs_bind")
    assert metadata["connected"] is True
    await azure_local_browser.save_session("rbs_bind")
    assert context.storage_calls >= 1

    with pytest.raises(HTTPException):
        await azure_local_browser.page_for_session("missing")
    with pytest.raises(HTTPException):
        await azure_local_browser.metadata_for_session("missing")
    await azure_local_browser.save_session("missing")


@pytest.mark.asyncio
async def test_current_without_context_does_not_launch_browser():
    result = await azure_local_browser.current_shared_browser("acct-off", create=False)
    assert result["connected"] is False
    assert result["browser_session_id"].startswith("azure-")


@pytest.mark.asyncio
async def test_snapshot_and_direct_user_actions(monkeypatch: pytest.MonkeyPatch):
    account_hash = azure_local_browser.account_digest("acct-user")
    page = FakePage("https://example.com", "Example")
    azure_local_browser._CONTEXTS[account_hash] = FakeContext([page])

    assert await azure_local_browser.snapshot(account_hash) == b"fake-png"

    result = await azure_local_browser.user_action(account_hash, {"kind": "navigate", "parameters": {"url": "https://example.com/a?x=1"}})
    assert result["ok"] is True
    assert page.url.startswith("https://example.com/a")
    await azure_local_browser.user_action(account_hash, {"kind": "click", "parameters": {"x": 10, "y": 20}})
    await azure_local_browser.user_action(account_hash, {"kind": "scroll", "parameters": {"delta_x": 1, "delta_y": 2}})
    await azure_local_browser.user_action(account_hash, {"kind": "type", "parameters": {"text": "hello"}})
    await azure_local_browser.user_action(account_hash, {"kind": "press", "parameters": {"key": "Enter"}})
    await azure_local_browser.user_action(account_hash, {"kind": "back", "parameters": {}})
    await azure_local_browser.user_action(account_hash, {"kind": "forward", "parameters": {}})
    await azure_local_browser.user_action(account_hash, {"kind": "reload", "parameters": {}})
    assert ("click", 10.0, 20.0) in page.mouse.calls
    assert ("wheel", 1.0, 2.0) in page.mouse.calls
    assert ("type", "hello") in page.keyboard.calls
    assert ("press", "Enter") in page.keyboard.calls

    for action in (
        {"kind": "navigate", "parameters": {"url": "file:///etc/passwd"}},
        {"kind": "type", "parameters": {"text": "x" * 5000}},
        {"kind": "press", "parameters": {"key": ""}},
        {"kind": "unknown", "parameters": {}},
    ):
        with pytest.raises(HTTPException) as exc:
            await azure_local_browser.user_action(account_hash, action)
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_engine_reuses_connected_browser_and_reports_launch_failure(monkeypatch: pytest.MonkeyPatch):
    connected = SimpleNamespace(is_connected=lambda: True)
    azure_local_browser._BROWSER = connected
    assert await azure_local_browser._ensure_engine() is connected

    class FailingChromium:
        async def launch(self, **kwargs):
            raise RuntimeError("boom")

    class FakePW:
        chromium = FailingChromium()

    azure_local_browser._BROWSER = None
    azure_local_browser._PLAYWRIGHT = FakePW()
    with pytest.raises(HTTPException) as exc:
        await azure_local_browser._ensure_engine()
    assert exc.value.status_code == 503
    assert exc.value.detail["error"] == "AZURE_CHROMIUM_UNAVAILABLE"
