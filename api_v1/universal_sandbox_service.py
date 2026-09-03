"""Isolated execution service for DSG Universal Runtime production.

Cinema verifies the stored approved plan. This service accepts only HMAC-signed,
plan-bound execution envelopes from Cinema and runs them in an account-scoped
workspace. Python/shell subprocesses receive a minimal environment and, when the
container runs as root, are dropped to uid/gid 65534 before user code starts.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(title="DSG Universal Sandbox", version="1.0")
_LOCK = threading.RLock()
_SEEN: dict[str, float] = {}
_MAX_OUTPUT = 20_000
_TIMEOUT_SECONDS = 45
_ALLOWED_COMMANDS = {"git", "ls", "pwd", "cat", "pytest", "python", "python3", Path(sys.executable).name}
_ALLOWED_GIT_SUBCOMMANDS = {"status", "diff", "log", "show", "branch", "rev-parse", "init", "add", "commit"}
_SUPPORTED_ACTIONS = {"fs.list", "fs.read", "fs.write", "python.run", "shell.exec"}


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_id: str = Field(min_length=1, max_length=64)
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    step_id: str = Field(min_length=1, max_length=64)
    action: str
    target: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    timestamp: int
    nonce: str = Field(min_length=16, max_length=128)


def _secret() -> bytes:
    value = (os.getenv("DSG_UNIVERSAL_EXECUTOR_SECRET") or "").strip()
    if len(value) < 32:
        raise HTTPException(status_code=503, detail={"error": "EXECUTOR_SECRET_NOT_CONFIGURED"})
    return value.encode("utf-8")


def _root() -> Path:
    path = Path(os.getenv("DSG_UNIVERSAL_WORKSPACE_ROOT") or "/workspace").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _workspace(account_hash: str) -> Path:
    root = _root()
    path = (root / account_hash).resolve()
    if root not in path.parents:
        raise HTTPException(status_code=403, detail={"error": "WORKSPACE_ESCAPE_BLOCKED"})
    path.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        try:
            os.chown(path, 65534, 65534)
        except OSError:
            pass
    return path


def _safe_path(workspace: Path, raw: str) -> Path:
    root = workspace.resolve()
    candidate = (root / raw).resolve()
    if candidate != root and root not in candidate.parents:
        raise HTTPException(status_code=403, detail={"error": "WORKSPACE_ESCAPE_BLOCKED"})
    return candidate


def _clip(value: str) -> str:
    return value if len(value) <= _MAX_OUTPUT else value[:_MAX_OUTPUT] + "\n...[truncated]"


def _minimal_env(workspace: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(workspace),
        "TMPDIR": str(workspace / ".tmp"),
        "PYTHONUNBUFFERED": "1",
        "LANG": "C.UTF-8",
    }


def _drop_privileges():
    if os.geteuid() != 0:
        return None

    def drop() -> None:
        os.setgroups([])
        os.setgid(65534)
        os.setuid(65534)

    return drop


def _run_process(command: list[str], workspace: Path) -> dict[str, Any]:
    temp = workspace / ".tmp"
    temp.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        try:
            os.chown(temp, 65534, 65534)
        except OSError:
            pass
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            env=_minimal_env(workspace),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
            preexec_fn=_drop_privileges(),
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail={"error": "SANDBOX_TIMEOUT"}) from exc
    return {"returncode": completed.returncode, "stdout": _clip(completed.stdout or ""), "stderr": _clip(completed.stderr or "")}


def _execute(env: Envelope) -> dict[str, Any]:
    if env.action not in _SUPPORTED_ACTIONS:
        raise HTTPException(status_code=409, detail={"error": "UNIVERSAL_ACTION_NOT_SUPPORTED"})
    workspace = _workspace(env.account_hash)
    params = dict(env.parameters)
    if env.action == "fs.list":
        path = _safe_path(workspace, str(params.get("path") or env.target or "."))
        if not path.is_dir():
            raise HTTPException(status_code=404, detail={"error": "WORKSPACE_DIRECTORY_NOT_FOUND"})
        return {"path": str(path.relative_to(workspace)), "entries": sorted(item.name for item in path.iterdir())[:500]}
    if env.action == "fs.read":
        path = _safe_path(workspace, str(params.get("path") or env.target))
        if not path.is_file():
            raise HTTPException(status_code=404, detail={"error": "WORKSPACE_FILE_NOT_FOUND"})
        content = path.read_text(encoding="utf-8")
        return {"path": str(path.relative_to(workspace)), "content": _clip(content), "sha256": hashlib.sha256(content.encode()).hexdigest()}
    if env.action == "fs.write":
        path = _safe_path(workspace, str(params.get("path") or env.target))
        content = params.get("content")
        if not isinstance(content, str):
            raise HTTPException(status_code=400, detail={"error": "FS_WRITE_CONTENT_REQUIRED"})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if os.geteuid() == 0:
            try:
                os.chown(path, 65534, 65534)
            except OSError:
                pass
        return {"path": str(path.relative_to(workspace)), "bytes": len(content.encode()), "sha256": hashlib.sha256(content.encode()).hexdigest()}
    if env.action == "python.run":
        code = params.get("code")
        if not isinstance(code, str) or not code.strip():
            raise HTTPException(status_code=400, detail={"error": "PYTHON_CODE_REQUIRED"})
        return _run_process([sys.executable, "-I", "-c", code], workspace)
    raw = params.get("command")
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=400, detail={"error": "SHELL_COMMAND_REQUIRED"})
    try:
        command = shlex.split(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": "INVALID_SHELL_COMMAND"}) from exc
    executable = Path(command[0]).name if command else ""
    if executable not in _ALLOWED_COMMANDS:
        raise HTTPException(status_code=403, detail={"error": "SHELL_COMMAND_NOT_ALLOWED"})
    if executable == "git" and (len(command) < 2 or command[1] not in _ALLOWED_GIT_SUBCOMMANDS):
        raise HTTPException(status_code=403, detail={"error": "GIT_SUBCOMMAND_NOT_ALLOWED"})
    return _run_process(command, workspace)


def _verify_signature(body: bytes, signature: str | None, timestamp: str | None, nonce: str | None) -> None:
    if not signature or not timestamp or not nonce:
        raise HTTPException(status_code=401, detail={"error": "EXECUTOR_AUTH_REQUIRED"})
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail={"error": "EXECUTOR_TIMESTAMP_INVALID"}) from exc
    now = int(time.time())
    if abs(now - ts) > 90:
        raise HTTPException(status_code=401, detail={"error": "EXECUTOR_TIMESTAMP_EXPIRED"})
    expected = hmac.new(_secret(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail={"error": "EXECUTOR_SIGNATURE_INVALID"})
    with _LOCK:
        for key, seen_at in list(_SEEN.items()):
            if now - seen_at > 180:
                _SEEN.pop(key, None)
        if nonce in _SEEN:
            raise HTTPException(status_code=409, detail={"error": "EXECUTOR_REPLAY_BLOCKED"})
        _SEEN[nonce] = float(now)


@app.get("/health")
def health() -> dict[str, Any]:
    configured = len((os.getenv("DSG_UNIVERSAL_EXECUTOR_SECRET") or "").strip()) >= 32
    return {"status": "ready" if configured else "not_ready", "executor": "isolated", "actions": sorted(_SUPPORTED_ACTIONS)}


@app.post("/execute")
async def execute(
    request: Request,
    x_dsg_signature: str | None = Header(default=None, alias="X-DSG-Signature"),
    x_dsg_timestamp: str | None = Header(default=None, alias="X-DSG-Timestamp"),
    x_dsg_nonce: str | None = Header(default=None, alias="X-DSG-Nonce"),
) -> dict[str, Any]:
    body = await request.body()
    _verify_signature(body, x_dsg_signature, x_dsg_timestamp, x_dsg_nonce)
    try:
        payload = Envelope.model_validate_json(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": "EXECUTOR_ENVELOPE_INVALID"}) from exc
    if str(payload.timestamp) != str(x_dsg_timestamp) or payload.nonce != x_dsg_nonce:
        raise HTTPException(status_code=401, detail={"error": "EXECUTOR_ENVELOPE_BINDING_MISMATCH"})
    return {"ok": True, "output": _execute(payload)}
