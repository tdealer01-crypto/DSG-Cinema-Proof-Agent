from __future__ import annotations

import importlib.util
import json
import stat
from argparse import Namespace
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dsg_browser.py"
SPEC = importlib.util.spec_from_file_location("dsg_browser_cli", SCRIPT)
assert SPEC and SPEC.loader
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


def _clear_auth(monkeypatch):
    for name in ("DSG_API_KEY", "DSG_PAIRING_TOKEN", "DSG_BROWSER_CONFIG"):
        monkeypatch.delenv(name, raising=False)


def test_pairing_token_is_preferred_for_agent_actions(monkeypatch, tmp_path):
    _clear_auth(monkeypatch)
    monkeypatch.setenv("DSG_PAIRING_TOKEN", "dsg_pair_test")
    monkeypatch.setenv("DSG_API_KEY", "api_test")
    headers = CLI._auth_headers()
    assert headers == {"Authorization": "Bearer dsg_pair_test"}


def test_view_requires_account_api_key(monkeypatch):
    _clear_auth(monkeypatch)
    monkeypatch.setenv("DSG_PAIRING_TOKEN", "dsg_pair_test")
    with pytest.raises(CLI.BrowserCliError, match="DSG_API_KEY"):
        CLI._auth_headers(require_api_key=True)


def test_session_file_is_private(monkeypatch, tmp_path):
    session = tmp_path / "session.json"
    monkeypatch.setenv("DSG_BROWSER_SESSION_FILE", str(session))
    CLI._save_session({"session_token": "secret", "plan_id": "plan_1"})
    assert stat.S_IMODE(session.stat().st_mode) == 0o600
    assert json.loads(session.read_text())["session_token"] == "secret"


def test_connect_never_prints_session_token(monkeypatch, tmp_path, capsys):
    session = tmp_path / "session.json"
    monkeypatch.setenv("DSG_BROWSER_SESSION_FILE", str(session))
    monkeypatch.setenv("DSG_API_KEY", "api_test")
    monkeypatch.setattr(CLI, "_request", lambda *a, **k: {
        "session_token": "rbs_secret",
        "provider": "azure_container_apps",
        "continuity": "ACCOUNT_SCOPED_PERSISTENT_CONTEXT",
    })
    CLI.cmd_connect(Namespace(plan_id="plan_1", step_id="step_1", agent_identity="agent", ttl=900))
    output = capsys.readouterr().out
    assert "rbs_secret" not in output
    assert "azure_container_apps" in output
    assert json.loads(session.read_text())["session_token"] == "rbs_secret"


def test_upload_requires_artifact_reference(monkeypatch):
    with pytest.raises(CLI.BrowserCliError, match="artifact://"):
        CLI.cmd_upload(Namespace(selector="input[type=file]", file_ref="/tmp/file.txt"))


def test_parser_exposes_product_commands():
    help_text = CLI.parser().format_help()
    for command in ("status", "view", "connect", "extract", "click", "type", "select", "upload", "download", "disconnect"):
        assert command in help_text
