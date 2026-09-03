from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api_v1 import universal_sandbox_service as sandbox


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DSG_UNIVERSAL_EXECUTOR_SECRET", "s" * 64)
    monkeypatch.setenv("DSG_UNIVERSAL_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    sandbox._SEEN.clear()
    return TestClient(sandbox.app)


def _post(client: TestClient, action: str, *, target: str = "", parameters: dict | None = None, nonce: str | None = None):
    ts = int(time.time())
    nonce = nonce or uuid.uuid4().hex
    payload = {
        "account_hash": "a" * 64,
        "plan_id": "plan-prod-e2e",
        "plan_hash": "b" * 64,
        "step_id": action.replace(".", "-"),
        "action": action,
        "target": target,
        "parameters": parameters or {},
        "timestamp": ts,
        "nonce": nonce,
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(("s" * 64).encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/execute",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-DSG-Signature": signature,
            "X-DSG-Timestamp": str(ts),
            "X-DSG-Nonce": nonce,
        },
    )


def test_isolated_workspace_python_shell_and_replay(client: TestClient):
    assert client.get("/health").json()["status"] == "ready"

    written = _post(client, "fs.write", target="result.txt", parameters={"path": "result.txt", "content": "DSG PROD E2E"})
    assert written.status_code == 200, written.text
    assert written.json()["output"]["sha256"]

    python = _post(client, "python.run", target="python", parameters={"code": "print(6*7)"})
    assert python.status_code == 200, python.text
    assert python.json()["output"]["stdout"].strip() == "42"

    shell = _post(client, "shell.exec", target="cat result.txt", parameters={"command": "cat result.txt"})
    assert shell.status_code == 200, shell.text
    assert shell.json()["output"]["stdout"].strip() == "DSG PROD E2E"

    nonce = uuid.uuid4().hex
    first = _post(client, "fs.list", target=".", parameters={"path": "."}, nonce=nonce)
    second = _post(client, "fs.list", target=".", parameters={"path": "."}, nonce=nonce)
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["error"] == "EXECUTOR_REPLAY_BLOCKED"


def test_sandbox_rejects_bad_signature_escape_and_unapproved_command(client: TestClient):
    body = b"{}"
    bad = client.post(
        "/execute",
        content=body,
        headers={"X-DSG-Signature": "0" * 64, "X-DSG-Timestamp": str(int(time.time())), "X-DSG-Nonce": uuid.uuid4().hex},
    )
    assert bad.status_code == 401

    escape = _post(client, "fs.write", target="../escape.txt", parameters={"path": "../escape.txt", "content": "no"})
    assert escape.status_code == 403
    assert escape.json()["detail"]["error"] == "WORKSPACE_ESCAPE_BLOCKED"

    blocked = _post(client, "shell.exec", target="env", parameters={"command": "env"})
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["error"] == "SHELL_COMMAND_NOT_ALLOWED"
