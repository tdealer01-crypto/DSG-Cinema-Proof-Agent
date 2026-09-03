"""Plan-bound universal execution tools for paired Cinema agents.

Browser work remains on the existing shared Remote Browser surface. This module
adds workspace file, Python and command execution behind the same stored Cinema
plan/approval boundary.

Execution modes:
- production: signed HTTP calls to an isolated sandbox configured through
  ``DSG_UNIVERSAL_EXECUTOR_URL`` + ``DSG_UNIVERSAL_EXECUTOR_SECRET``;
- tests/local sandbox only: in-process subprocess adapter enabled explicitly by
  ``DSG_UNIVERSAL_LOCAL_EXECUTOR=1``.

The agent supplies only plan_id + step_id. Action, target, code, command, path and
content are re-read from the already-approved stored plan before execution.
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
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import Field

from . import remote_browser, remote_pairing, service
from .canonical import canonical_hash, utc_now
from .models import PlanStep, Strict

router = APIRouter(prefix="/dashboard/api/runtime", tags=["dashboard-runtime"])
_lock = threading.RLock()
_MAX_OUTPUT = 20_000
_TIMEOUT_SECONDS = 45
_LOCAL_EXECUTOR_ENV = "DSG_UNIVERSAL_LOCAL_EXECUTOR"
_REMOTE_EXECUTOR_URL_ENV = "DSG_UNIVERSAL_EXECUTOR_URL"
_REMOTE_EXECUTOR_SECRET_ENV = "DSG_UNIVERSAL_EXECUTOR_SECRET"

_SUPPORTED_ACTIONS = {"fs.list", "fs.read", "fs.write", "python.run", "shell.exec"}
_ALLOWED_COMMANDS = {"git", "ls", "pwd", "cat", "pytest", "python", "python3", Path(sys.executable).name}
_ALLOWED_GIT_SUBCOMMANDS = {"status", "diff", "log", "show", "branch", "rev-parse", "init", "add", "commit"}


class UniversalExecuteArgs(Strict):
    plan_id: str = Field(min_length=1, max_length=64)
    step_id: str = Field(min_length=1, max_length=64)


def _enabled() -> bool:
    return (os.getenv(_LOCAL_EXECUTOR_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


def _remote_config() -> tuple[str, str] | None:
    url = (os.getenv(_REMOTE_EXECUTOR_URL_ENV) or "").strip().rstrip("/")
    secret = (os.getenv(_REMOTE_EXECUTOR_SECRET_ENV) or "").strip()
    if not url and not secret:
        return None
    if not url or len(secret) < 32 or not url.startswith("https://"):
        raise HTTPException(status_code=503, detail={"error": "UNIVERSAL_REMOTE_EXECUTOR_MISCONFIGURED"})
    return url, secret


def _account_context(api_key: Optional[str] = None) -> tuple[str, str]:
    from . import remote_mcp

    key = (api_key or remote_mcp._current_api_key() or "").strip()
    if not key:
        raise HTTPException(status_code=401, detail="an authenticated paired agent is required")
    account_id = remote_pairing._account_id(key)
    agent_name = (remote_mcp._current_agent_name() or "").strip()
    return account_id, agent_name


def _account_hash(account_id: str) -> str:
    return hashlib.sha256(account_id.encode("utf-8")).hexdigest()


def _root(account_id: str) -> Path:
    root = remote_browser._ensure_store() / "universal-runtime" / _account_hash(account_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _workspace(account_id: str) -> Path:
    path = _root(account_id) / "workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _events(account_id: str) -> Path:
    path = _root(account_id) / "events"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_path(workspace: Path, raw: str) -> Path:
    root = workspace.resolve()
    candidate = (root / raw).resolve()
    if candidate != root and root not in candidate.parents:
        raise HTTPException(status_code=403, detail={"error": "WORKSPACE_ESCAPE_BLOCKED"})
    return candidate


def _clip(value: str) -> str:
    return value if len(value) <= _MAX_OUTPUT else value[:_MAX_OUTPUT] + "\n...[truncated]"


def _resolve_step(plan_id: str, step_id: str, agent_name: str) -> tuple[dict[str, Any], PlanStep]:
    try:
        record = service.get_plan_record(plan_id)
        document = service.plan_document(record)
    except Exception as exc:
        raise HTTPException(status_code=404, detail={"error": "PLAN_NOT_FOUND", "plan_id": plan_id}) from exc
    if str(record.get("status") or "") != service.STATUS_APPROVED:
        raise HTTPException(status_code=409, detail={"error": "PLAN_NOT_APPROVED", "plan_id": plan_id})
    try:
        view = service.read_plan(plan_id)
    except Exception as exc:
        raise HTTPException(status_code=409, detail={"error": "PLAN_UNREADABLE", "plan_id": plan_id}) from exc
    if view.get("plan_hash_verified") is not True:
        raise HTTPException(status_code=409, detail={"error": "PLAN_HASH_VERIFICATION_FAILED", "plan_id": plan_id})
    if agent_name and document.agent_identity != agent_name:
        raise HTTPException(
            status_code=403,
            detail={"error": "AGENT_IDENTITY_MISMATCH", "approved_agent": document.agent_identity, "paired_agent": agent_name},
        )
    step = next((item for item in document.steps if item.step_id == step_id), None)
    if step is None:
        raise HTTPException(status_code=403, detail={"error": "STEP_NOT_IN_APPROVED_PLAN", "step_id": step_id})
    if step.action not in _SUPPORTED_ACTIONS:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "UNIVERSAL_ACTION_NOT_SUPPORTED",
                "action": step.action,
                "message": "Use remote_action for browser.* steps; this executor handles files, Python and sandbox commands.",
            },
        )
    return record, step


def _minimal_env(workspace: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(workspace),
        "TMPDIR": str(workspace / ".tmp"),
        "PYTHONUNBUFFERED": "1",
        "LANG": "C.UTF-8",
    }


def _run_process(command: list[str], workspace: Path) -> dict[str, Any]:
    if not _enabled():
        raise HTTPException(
            status_code=503,
            detail={
                "error": "UNIVERSAL_SANDBOX_EXECUTOR_REQUIRED",
                "message": (
                    "The in-process local executor is disabled. Configure an isolated sandbox executor for production; "
                    f"set {_LOCAL_EXECUTOR_ENV}=1 only in an isolated test/sandbox environment."
                ),
            },
        )
    (workspace / ".tmp").mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            env=_minimal_env(workspace),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail={"error": "SANDBOX_TIMEOUT"}) from exc
    return {"returncode": completed.returncode, "stdout": _clip(completed.stdout or ""), "stderr": _clip(completed.stderr or "")}


def _execute_local(account_id: str, step: PlanStep) -> dict[str, Any]:
    workspace = _workspace(account_id)
    params = dict(step.parameters)
    action = step.action
    if action == "fs.list":
        path = _safe_path(workspace, str(params.get("path") or step.target or "."))
        if not path.is_dir():
            raise HTTPException(status_code=404, detail={"error": "WORKSPACE_DIRECTORY_NOT_FOUND"})
        return {"path": str(path.relative_to(workspace)), "entries": sorted(item.name for item in path.iterdir())[:500]}
    if action == "fs.read":
        path = _safe_path(workspace, str(params.get("path") or step.target))
        if not path.is_file():
            raise HTTPException(status_code=404, detail={"error": "WORKSPACE_FILE_NOT_FOUND"})
        content = path.read_text(encoding="utf-8")
        return {"path": str(path.relative_to(workspace)), "content": _clip(content), "sha256": hashlib.sha256(content.encode()).hexdigest()}
    if action == "fs.write":
        path = _safe_path(workspace, str(params.get("path") or step.target))
        content = params.get("content")
        if not isinstance(content, str):
            raise HTTPException(status_code=400, detail={"error": "FS_WRITE_CONTENT_REQUIRED"})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"path": str(path.relative_to(workspace)), "bytes": len(content.encode()), "sha256": hashlib.sha256(content.encode()).hexdigest()}
    if action == "python.run":
        code = params.get("code")
        if not isinstance(code, str) or not code.strip():
            raise HTTPException(status_code=400, detail={"error": "PYTHON_CODE_REQUIRED"})
        return _run_process([sys.executable, "-I", "-c", code], workspace)
    if action == "shell.exec":
        raw = params.get("command")
        if not isinstance(raw, str) or not raw.strip():
            raise HTTPException(status_code=400, detail={"error": "SHELL_COMMAND_REQUIRED"})
        try:
            command = shlex.split(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": "INVALID_SHELL_COMMAND"}) from exc
        if not command or Path(command[0]).name not in _ALLOWED_COMMANDS:
            raise HTTPException(status_code=403, detail={"error": "SHELL_COMMAND_NOT_ALLOWED"})
        if Path(command[0]).name == "git" and (len(command) < 2 or command[1] not in _ALLOWED_GIT_SUBCOMMANDS):
            raise HTTPException(status_code=403, detail={"error": "GIT_SUBCOMMAND_NOT_ALLOWED"})
        return _run_process(command, workspace)
    raise HTTPException(status_code=409, detail={"error": "UNIVERSAL_ACTION_NOT_SUPPORTED", "action": action})


def _execute_remote(account_id: str, plan_id: str, record: dict[str, Any], step: PlanStep) -> dict[str, Any]:
    config = _remote_config()
    if config is None:
        raise HTTPException(status_code=503, detail={"error": "UNIVERSAL_SANDBOX_EXECUTOR_REQUIRED"})
    url, secret = config
    timestamp = int(time.time())
    nonce = uuid.uuid4().hex
    payload = {
        "account_hash": _account_hash(account_id),
        "plan_id": plan_id,
        "plan_hash": str(record.get("plan_hash") or ""),
        "step_id": step.step_id,
        "action": step.action,
        "target": step.target,
        "parameters": dict(step.parameters),
        "timestamp": timestamp,
        "nonce": nonce,
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    try:
        response = httpx.post(
            f"{url}/execute",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-DSG-Signature": signature,
                "X-DSG-Timestamp": str(timestamp),
                "X-DSG-Nonce": nonce,
            },
            timeout=_TIMEOUT_SECONDS + 10,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail={"error": "UNIVERSAL_SANDBOX_UNREACHABLE"}) from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail={"error": "UNIVERSAL_SANDBOX_INVALID_RESPONSE"}) from exc
    if response.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else None
        if not isinstance(detail, dict):
            detail = {"error": "UNIVERSAL_SANDBOX_REJECTED"}
        raise HTTPException(status_code=response.status_code, detail=detail)
    if not isinstance(data, dict) or data.get("ok") is not True or not isinstance(data.get("output"), dict):
        raise HTTPException(status_code=502, detail={"error": "UNIVERSAL_SANDBOX_INVALID_RESPONSE"})
    return data["output"]


def _execute(account_id: str, plan_id: str, record: dict[str, Any], step: PlanStep) -> dict[str, Any]:
    if _remote_config() is not None:
        return _execute_remote(account_id, plan_id, record, step)
    return _execute_local(account_id, step)


def _event_files(account_id: str) -> list[Path]:
    return sorted(_events(account_id).glob("*.json"))


def _ledger_tail(account_id: str) -> tuple[int, str]:
    files = _event_files(account_id)
    if not files:
        return 0, "0" * 64
    try:
        value = json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail={"error": "UNIVERSAL_EVIDENCE_UNREADABLE"}) from exc
    return int(value.get("seq") or 0), str(value.get("evidence_hash") or "0" * 64)


def _write_event(account_id: str, event: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        seq, previous = _ledger_tail(account_id)
        record = {"seq": seq + 1, "prev_hash": previous, **event}
        record["evidence_hash"] = canonical_hash(record)
        path = _events(account_id) / f"{record['seq']:012d}-{record['event_id']}.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        temp.replace(path)
        return record


def verify_evidence(account_id: str) -> dict[str, Any]:
    previous = "0" * 64
    count = 0
    for path in _event_files(account_id):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"ok": False, "records": count, "error": "event_unreadable"}
        got = str(record.pop("evidence_hash", ""))
        if record.get("prev_hash") != previous:
            return {"ok": False, "records": count, "error": "prev_hash_mismatch"}
        expected = canonical_hash(record)
        if got != expected:
            return {"ok": False, "records": count, "error": "evidence_hash_mismatch"}
        previous = got
        count += 1
    return {"ok": True, "records": count, "head": previous}


def latest_event(account_id: str) -> dict[str, Any] | None:
    files = _event_files(account_id)
    if not files:
        return None
    try:
        value = json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _executor_state() -> dict[str, Any]:
    remote = _remote_config()
    if remote is not None:
        return {"executor": "remote-isolated-sandbox", "remote_executor_configured": True, "local_executor_enabled": False}
    if _enabled():
        return {"executor": "local-sandbox", "remote_executor_configured": False, "local_executor_enabled": True}
    return {"executor": "external-sandbox-required", "remote_executor_configured": False, "local_executor_enabled": False}


async def _runtime_status(_: Any) -> dict[str, Any]:
    account_id, _ = _account_context()
    return {
        "ok": True,
        **_executor_state(),
        "workspace": "account-scoped",
        "actions": sorted(_SUPPORTED_ACTIONS),
        "browser_execution": "use remote_action on the existing shared browser",
        "evidence": verify_evidence(account_id),
    }


async def _execute_step(args: UniversalExecuteArgs) -> dict[str, Any]:
    account_id, agent_name = _account_context()
    record, step = _resolve_step(args.plan_id, args.step_id, agent_name)
    event_id = f"uevt_{uuid.uuid4().hex}"
    started_at = utc_now()
    try:
        output = _execute(account_id, args.plan_id, record, step)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        failed = _write_event(
            account_id,
            {
                "event_id": event_id,
                "state": "BLOCKED" if exc.status_code in {400, 401, 403, 409} else "FAILED",
                "plan_id": args.plan_id,
                "plan_hash": record.get("plan_hash"),
                "agent_identity": agent_name or service.plan_document(record).agent_identity,
                "step_id": args.step_id,
                "actor": "AGENT",
                "controller": "agent_executor",
                "action": {"kind": step.action, "target": step.target},
                "error": detail.get("error") or detail.get("message") or "UNIVERSAL_EXECUTION_FAILED",
                "recorded_at": started_at,
                "finished_at": utc_now(),
            },
        )
        raise HTTPException(status_code=exc.status_code, detail={**detail, "event_id": failed["event_id"], "evidence_hash": failed["evidence_hash"]}) from exc

    response_sha256 = canonical_hash(output)
    completed = _write_event(
        account_id,
        {
            "event_id": event_id,
            "state": "COMPLETED",
            "plan_id": args.plan_id,
            "plan_hash": record.get("plan_hash"),
            "agent_identity": agent_name or service.plan_document(record).agent_identity,
            "step_id": args.step_id,
            "actor": "AGENT",
            "controller": "agent_executor",
            "action": {"kind": step.action, "target": step.target},
            "response_sha256": response_sha256,
            "remote_status": 200,
            "recorded_at": started_at,
            "finished_at": utc_now(),
        },
    )
    return {
        "ok": True,
        "status": "COMPLETED",
        "plan_id": args.plan_id,
        "plan_hash": record.get("plan_hash"),
        "step_id": args.step_id,
        "action": step.action,
        "target": step.target,
        "output": output,
        "response_sha256": response_sha256,
        "event_id": completed["event_id"],
        "evidence_hash": completed["evidence_hash"],
    }


async def _verify(_: Any) -> dict[str, Any]:
    account_id, _ = _account_context()
    return verify_evidence(account_id)


def install_mcp_tools() -> None:
    from . import remote_mcp

    if "universal_runtime_status" in remote_mcp._BY_NAME:
        return
    tools = (
        remote_mcp._Tool(
            "universal_runtime_status",
            "Inspect the plan-bound universal workspace executor and its evidence-chain health. Browser work continues through remote_action on the same shared browser.",
            None,
            _runtime_status,
            read_only=True,
            idempotent=True,
            open_world=False,
        ),
        remote_mcp._Tool(
            "universal_execute_step",
            "Execute one fs.*, python.run, or shell.exec step exactly as stored in an already-approved Cinema plan. The agent cannot supply replacement code, commands, paths, or content at execution time.",
            UniversalExecuteArgs,
            _execute_step,
            read_only=False,
            idempotent=False,
            open_world=False,
        ),
        remote_mcp._Tool(
            "universal_evidence_verify",
            "Verify the account's hash-chained universal-runtime evidence ledger.",
            None,
            _verify,
            read_only=True,
            idempotent=True,
            open_world=False,
        ),
    )
    for tool in tools:
        remote_mcp.TOOLS = (*remote_mcp.TOOLS, tool)
        remote_mcp._BY_NAME[tool.name] = tool


@router.get("/status")
async def runtime_status(x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key")) -> dict[str, Any]:
    account_id, _ = _account_context(x_dsg_api_key)
    return {
        "ok": True,
        **_executor_state(),
        "actions": sorted(_SUPPORTED_ACTIONS),
        "browser_execution": "remote_action",
        "evidence": verify_evidence(account_id),
    }


def install(app) -> None:
    app.include_router(router)
    install_mcp_tools()


__all__ = ["UniversalExecuteArgs", "install", "install_mcp_tools", "latest_event", "router", "verify_evidence"]
