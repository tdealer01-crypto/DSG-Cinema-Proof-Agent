from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api_v1 import azure_local_browser, azure_managed_executor, browserbase_executor


class Locator:
    def __init__(self):
        self.calls = []

    async def click(self, **kwargs):
        self.calls.append(("click", kwargs))

    async def fill(self, value, **kwargs):
        self.calls.append(("fill", value, kwargs))

    async def select_option(self, **kwargs):
        self.calls.append(("select", kwargs))

    async def set_input_files(self, value):
        self.calls.append(("upload", value))


class Mouse:
    def __init__(self):
        self.calls = []

    async def wheel(self, x, y):
        self.calls.append(("wheel", x, y))

    async def move(self, x, y, **kwargs):
        self.calls.append(("move", x, y, kwargs))

    async def click(self, x, y):
        self.calls.append(("click", x, y))

    async def down(self):
        self.calls.append(("down",))

    async def up(self):
        self.calls.append(("up",))


class Keyboard:
    def __init__(self):
        self.calls = []

    async def type(self, text):
        self.calls.append(("type", text))

    async def press(self, key):
        self.calls.append(("press", key))


class Page:
    def __init__(self):
        self.url = "https://example.com/start"
        self.mouse = Mouse()
        self.keyboard = Keyboard()
        self.goto_calls = []
        self._title = "Start"

    async def goto(self, url, **kwargs):
        self.goto_calls.append((url, kwargs))
        self.url = url
        self._title = "Example"

    async def title(self):
        return self._title

    async def screenshot(self, **kwargs):
        return b"azure-shot"


@pytest.fixture()
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "m" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "store"))
    page = Page()
    locator = Locator()

    async def fake_page(_session_id):
        return page

    async def fake_locator(_page, _params):
        return locator

    monkeypatch.setattr(azure_local_browser, "page_for_session", fake_page)
    monkeypatch.setattr(browserbase_executor, "_resolve_locator", fake_locator)
    monkeypatch.setattr(browserbase_executor, "_assert_current_origin", lambda *_a, **_k: None)
    monkeypatch.setattr(browserbase_executor, "_extract", lambda _page: _async_value({"url": page.url, "text": "Example"}))
    monkeypatch.setattr(browserbase_executor, "_sensitive_control", lambda _locator: _async_value(False))
    return page, locator, tmp_path


async def _async_value(value):
    return value


def payload(kind: str, parameters=None):
    return {
        "context": {"browser_policy": {"allowed_origins": ["https://example.com"]}},
        "action": {"kind": kind, "parameters": parameters or {}},
    }


@pytest.mark.asyncio
async def test_navigation_extract_screenshot(runtime):
    page, _locator, _tmp = runtime
    status, body = await azure_managed_executor._perform_action(
        "rbs", payload("browser.navigate", {"url": "https://example.com/next"})
    )
    assert status == 200 and body["url"].endswith("/next")

    status, body = await azure_managed_executor._perform_action("rbs", payload("browser.extract"))
    assert status == 200 and body["text"] == "Example"

    status, body = await azure_managed_executor._perform_action(
        "rbs", payload("browser.screenshot", {"full_page": True})
    )
    assert status == 200
    assert len(body["screenshot_sha256"]) == 64
    assert body["evidence_ref"].startswith("azure-browser://evidence/")


@pytest.mark.asyncio
async def test_locator_mouse_keyboard_and_confirmation_actions(runtime, tmp_path: Path):
    page, locator, _ = runtime
    actions = [
        ("browser.click", {"selector": "#go"}),
        ("browser.type", {"selector": "#name", "value": "Alice"}),
        ("browser.select", {"selector": "#role", "value": "Admin"}),
        ("browser.scroll", {"delta_x": 1, "delta_y": 2}),
        ("pointer.move", {"x": 3, "y": 4}),
        ("pointer.click", {"x": 5, "y": 6}),
        ("pointer.drag", {"start_x": 1, "start_y": 2, "end_x": 7, "end_y": 8}),
        ("keyboard.type", {"text": "hello"}),
        ("keyboard.press", {"key": "Enter"}),
        ("identity.confirmation.click", {"selector": "#confirm"}),
    ]
    for kind, params in actions:
        status, body = await azure_managed_executor._perform_action("rbs", payload(kind, params))
        assert status == 200 and body["ok"] is True

    assert any(call[0] == "fill" for call in locator.calls)
    assert any(call[0] == "select" for call in locator.calls)
    assert ("wheel", 1.0, 2.0) in page.mouse.calls
    assert ("type", "hello") in page.keyboard.calls
    assert ("press", "Enter") in page.keyboard.calls


@pytest.mark.asyncio
async def test_upload_and_validation_failures(runtime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _page, locator, _ = runtime
    artifact = Path("/app/test-azure-upload.txt")
    # Avoid depending on writable /app in CI: patch executor Path root to temp.
    class RootPath:
        def __new__(cls, value):
            if value == "/app":
                return tmp_path
            return Path(value)

    monkeypatch.setattr(azure_managed_executor, "Path", RootPath)
    candidate = tmp_path / "artifact.txt"
    candidate.write_text("hello", encoding="utf-8")
    status, body = await azure_managed_executor._perform_action(
        "rbs", payload("browser.upload", {"selector": "input", "file_ref": "artifact://artifact.txt"})
    )
    assert status == 200 and len(body["artifact_sha256"]) == 64
    assert locator.calls[-1][0] == "upload"

    cases = [
        ("browser.navigate", {}, 400),
        ("browser.type", {"selector": "#x"}, 400),
        ("browser.select", {"selector": "#x"}, 400),
        ("browser.upload", {"selector": "#x", "file_ref": "file:///tmp/x"}, 400),
        ("keyboard.type", {}, 400),
        ("keyboard.press", {}, 400),
        ("browser.workflow", {}, 501),
        ("identity.secret.inject", {}, 409),
        ("identity.otp.submit", {}, 409),
        ("unknown", {}, 400),
    ]
    for kind, params, expected in cases:
        with pytest.raises(HTTPException) as exc:
            await azure_managed_executor._perform_action("rbs", payload(kind, params))
        assert exc.value.status_code == expected


@pytest.mark.asyncio
async def test_sensitive_type_is_direct_user_only(runtime, monkeypatch: pytest.MonkeyPatch):
    async def sensitive(_locator):
        return True

    monkeypatch.setattr(browserbase_executor, "_sensitive_control", sensitive)
    with pytest.raises(HTTPException) as exc:
        await azure_managed_executor._perform_action(
            "rbs", payload("browser.type", {"selector": "input[type=password]", "value": "secret"})
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "DELEGATED_IDENTITY_INPUT_REQUIRED"


@pytest.mark.asyncio
async def test_azure_action_validates_capability_serializes_mutation_and_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "z" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "store"))
    capability = browserbase_executor.allocate_capability(
        plan_id="plan",
        step_id="step",
        agent_identity="agent",
        ttl_seconds=600,
    )
    browserbase_executor.finalize_capability(
        capability,
        session_id="rbs_action",
        plan_hash="a" * 64,
        browser_policy={"enforced": True, "allowed_origins": ["https://example.com"]},
    )
    calls = []

    async def ensure(*_a, **_k):
        calls.append("ensure")
        return {"connected": True}

    async def perform(_sid, envelope):
        calls.append(envelope["action"]["kind"])
        return 200, {"ok": True}

    async def save(_sid):
        calls.append("save")

    monkeypatch.setattr(azure_managed_executor, "ensure_browser_session", ensure)
    monkeypatch.setattr(azure_managed_executor, "_perform_action", perform)
    monkeypatch.setattr(azure_local_browser, "save_session", save)

    base = {
        "version": "dsg.remote-action.v1",
        "session_id": "rbs_action",
        "context": {
            "plan_id": "plan",
            "plan_hash": "a" * 64,
            "agent_identity": "agent",
            "step_id": "step",
            "actor": "AGENT_EXECUTOR",
            "browser_policy": {
                "enforced": True,
                "allowed_origins": ["https://example.com"],
                "enforce_current_origin": True,
            },
        },
    }
    read = await azure_managed_executor.azure_action(
        capability, {**base, "action": {"kind": "browser.extract", "controller": "agent_verifier", "parameters": {}}}
    )
    assert read["provider"] == "azure_container_apps" and read["remote_status"] == 200
    mutate = await azure_managed_executor.azure_action(
        capability, {**base, "action": {"kind": "browser.click", "controller": "agent_executor", "parameters": {}}}
    )
    assert mutate["ok"] is True
    assert calls.count("save") == 2


@pytest.mark.asyncio
async def test_live_view_resolves_account(monkeypatch: pytest.MonkeyPatch):
    from api_v1 import remote_pairing

    monkeypatch.setattr(remote_pairing, "_api_key", lambda value: "key")
    monkeypatch.setattr(remote_pairing, "_account_id", lambda value: "acct")

    async def current(account_id: str, *, create=False):
        assert account_id == "acct"
        return {"provider": "azure_container_apps", "connected": True}

    monkeypatch.setattr(azure_local_browser, "current_shared_browser", current)
    result = await azure_managed_executor.live_view(x_dsg_api_key="anything")
    assert result["ok"] is True and result["connected"] is True
