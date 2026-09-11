#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

DEFAULT_BASE_URL = "https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io"
DEFAULT_CONFIG = Path.home() / ".config" / "dsg-browser" / "config.json"
DEFAULT_SESSION = Path.home() / ".config" / "dsg-browser" / "session.json"


class BrowserCliError(RuntimeError):
    pass


def _json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrowserCliError(f"invalid JSON config: {path}") from exc
    if not isinstance(data, dict):
        raise BrowserCliError(f"config must be a JSON object: {path}")
    return data


def _assert_private_file(path: Path) -> None:
    if not path.exists():
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise BrowserCliError(f"secret-bearing file must be mode 600 or stricter: {path}")


def _config() -> dict[str, Any]:
    path = Path(os.environ.get("DSG_BROWSER_CONFIG", str(DEFAULT_CONFIG))).expanduser()
    data = _json_file(path)
    if data.get("api_key") or data.get("pairing_token"):
        _assert_private_file(path)
    return {
        "base_url": os.environ.get("DSG_CINEMA_BASE_URL") or data.get("base_url") or DEFAULT_BASE_URL,
        "api_key": os.environ.get("DSG_API_KEY") or data.get("api_key"),
        "pairing_token": os.environ.get("DSG_PAIRING_TOKEN") or data.get("pairing_token"),
    }


def _auth_headers(*, require_api_key: bool = False) -> dict[str, str]:
    cfg = _config()
    api_key = cfg.get("api_key")
    pairing = cfg.get("pairing_token")
    if require_api_key:
        if not isinstance(api_key, str) or not api_key:
            raise BrowserCliError("DSG_API_KEY is required for this command")
        return {"X-DSG-API-Key": api_key}
    if isinstance(pairing, str) and pairing:
        return {"Authorization": f"Bearer {pairing}"}
    if isinstance(api_key, str) and api_key:
        return {"X-DSG-API-Key": api_key}
    raise BrowserCliError("set DSG_PAIRING_TOKEN or DSG_API_KEY")


def _redact(value: Any) -> Any:
    secrets: list[str] = []
    cfg = _config()
    for key in ("api_key", "pairing_token"):
        secret = cfg.get(key)
        if isinstance(secret, str) and secret:
            secrets.append(secret)
    try:
        state = _load_session(required=False)
        token = state.get("session_token")
        if isinstance(token, str) and token:
            secrets.append(token)
    except BrowserCliError:
        pass

    def scrub(text: str) -> str:
        for secret in secrets:
            text = text.replace(secret, "<redacted>")
        return text

    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out[key] = "<redacted>" if key in {"api_key", "pairing_token", "session_token"} else _redact(item)
        return out
    return value


def _request(method: str, path: str, body: dict[str, Any] | None = None, *, require_api_key: bool = False) -> dict[str, Any]:
    cfg = _config()
    base = str(cfg["base_url"]).rstrip("/") + "/"
    url = urljoin(base, path.lstrip("/"))
    headers = {"Accept": "application/json", **_auth_headers(require_api_key=require_api_key)}
    payload = None
    if body is not None:
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=payload, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            detail: Any = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw[:1000]
        raise BrowserCliError(f"HTTP {exc.code}: {json.dumps(_redact(detail), ensure_ascii=False)}") from exc
    except urllib.error.URLError as exc:
        raise BrowserCliError(f"network error: {exc.reason}") from exc


def _session_path() -> Path:
    return Path(os.environ.get("DSG_BROWSER_SESSION_FILE", str(DEFAULT_SESSION))).expanduser()


def _save_session(data: dict[str, Any]) -> None:
    path = _session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _load_session(*, required: bool = True) -> dict[str, Any]:
    path = _session_path()
    if not path.exists():
        if required:
            raise BrowserCliError("no agent session; run: dsg-browser connect ...")
        return {}
    _assert_private_file(path)
    data = _json_file(path)
    if required and not isinstance(data.get("session_token"), str):
        raise BrowserCliError("session file does not contain a valid session token")
    return data


def _print(data: Any) -> None:
    print(json.dumps(_redact(data), ensure_ascii=False, indent=2, sort_keys=True))


def _action(kind: str, parameters: dict[str, Any], controller: str = "agent_executor") -> dict[str, Any]:
    state = _load_session()
    body = {
        "session_token": state["session_token"],
        "kind": kind,
        "controller": controller,
        "parameters": parameters,
    }
    return _request("POST", "/chatgpt-actions/remote-browser/action", body)


def cmd_status(_: argparse.Namespace) -> None:
    _print(_request("GET", "/chatgpt-actions/remote-browser/status"))


def cmd_view(args: argparse.Namespace) -> None:
    data = _request("GET", "/remote-browser/browserbase/live-frame", require_api_key=True)
    if data.get("provider") != "azure_container_apps":
        raise BrowserCliError(f"production provider is not Azure: {data.get('provider')}")
    if not data.get("connected") or not data.get("embed_url"):
        raise BrowserCliError("shared Azure browser is not connected")
    cfg = _config()
    url = urljoin(str(cfg["base_url"]).rstrip("/") + "/", str(data["embed_url"]).lstrip("/"))
    print(url)
    if args.open:
        opener = next((name for name in ("termux-open-url", "xdg-open", "open") if _which(name)), None)
        if not opener:
            raise BrowserCliError("no supported URL opener found; use the printed URL")
        subprocess.run([opener, url], check=True)


def _which(name: str) -> str | None:
    from shutil import which
    return which(name)


def cmd_connect(args: argparse.Namespace) -> None:
    body = {
        "plan_id": args.plan_id,
        "agent_identity": args.agent_identity,
        "step_id": args.step_id,
        "ttl_seconds": args.ttl,
    }
    data = _request("POST", "/chatgpt-actions/remote-browser/connect", body)
    token = data.get("session_token")
    if not isinstance(token, str) or not token:
        raise BrowserCliError("connect response did not return a session token")
    _save_session({
        "session_token": token,
        "plan_id": args.plan_id,
        "agent_identity": args.agent_identity,
        "step_id": args.step_id,
        "provider": data.get("provider"),
        "continuity": data.get("continuity"),
    })
    _print({
        "connected": True,
        "plan_id": args.plan_id,
        "step_id": args.step_id,
        "provider": data.get("provider"),
        "continuity": data.get("continuity"),
    })


def cmd_disconnect(_: argparse.Namespace) -> None:
    state = _load_session()
    data = _request("POST", "/chatgpt-actions/remote-browser/disconnect", {"session_token": state["session_token"]})
    path = _session_path()
    if path.exists():
        path.unlink()
    _print(data)


def cmd_navigate(args: argparse.Namespace) -> None:
    _print(_action("browser.navigate", {"url": args.url}))


def cmd_extract(_: argparse.Namespace) -> None:
    _print(_action("browser.extract", {}, controller="agent_verifier"))


def cmd_screenshot(args: argparse.Namespace) -> None:
    _print(_action("browser.screenshot", {"full_page": args.full_page}, controller="agent_verifier"))


def cmd_click(args: argparse.Namespace) -> None:
    _print(_action("browser.click", {"selector": args.selector}))


def cmd_type(args: argparse.Namespace) -> None:
    _print(_action("browser.type", {"selector": args.selector, "value": args.value}))


def cmd_select(args: argparse.Namespace) -> None:
    _print(_action("browser.select", {"selector": args.selector, "value": args.value}))


def cmd_scroll(args: argparse.Namespace) -> None:
    _print(_action("browser.scroll", {"delta_x": args.x, "delta_y": args.y}))


def cmd_press(args: argparse.Namespace) -> None:
    _print(_action("keyboard.press", {"key": args.key}))


def cmd_upload(args: argparse.Namespace) -> None:
    if not args.file_ref.startswith("artifact://"):
        raise BrowserCliError("upload requires an artifact:// file_ref")
    _print(_action("browser.upload", {"selector": args.selector, "file_ref": args.file_ref}))


def cmd_download(args: argparse.Namespace) -> None:
    _print(_action("browser.download", {"selector": args.selector}))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dsg-browser", description="DSG governed shared Azure browser CLI")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status").set_defaults(func=cmd_status)
    view = sub.add_parser("view", help="print a short-lived mobile/shared viewer URL")
    view.add_argument("--open", action="store_true")
    view.set_defaults(func=cmd_view)
    connect = sub.add_parser("connect", help="join the shared browser under an approved plan")
    connect.add_argument("--plan-id", required=True)
    connect.add_argument("--step-id", required=True)
    connect.add_argument("--agent-identity", required=True)
    connect.add_argument("--ttl", type=int, default=900, choices=range(60, 3601))
    connect.set_defaults(func=cmd_connect)
    sub.add_parser("disconnect").set_defaults(func=cmd_disconnect)
    nav = sub.add_parser("navigate"); nav.add_argument("url"); nav.set_defaults(func=cmd_navigate)
    sub.add_parser("extract").set_defaults(func=cmd_extract)
    shot = sub.add_parser("screenshot"); shot.add_argument("--full-page", action="store_true"); shot.set_defaults(func=cmd_screenshot)
    click = sub.add_parser("click"); click.add_argument("selector"); click.set_defaults(func=cmd_click)
    typ = sub.add_parser("type"); typ.add_argument("selector"); typ.add_argument("value"); typ.set_defaults(func=cmd_type)
    sel = sub.add_parser("select"); sel.add_argument("selector"); sel.add_argument("value"); sel.set_defaults(func=cmd_select)
    scroll = sub.add_parser("scroll"); scroll.add_argument("--x", type=float, default=0); scroll.add_argument("--y", type=float, default=600); scroll.set_defaults(func=cmd_scroll)
    press = sub.add_parser("press"); press.add_argument("key"); press.set_defaults(func=cmd_press)
    upload = sub.add_parser("upload"); upload.add_argument("selector"); upload.add_argument("file_ref"); upload.set_defaults(func=cmd_upload)
    download = sub.add_parser("download"); download.add_argument("selector"); download.set_defaults(func=cmd_download)
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        args.func(args)
        return 0
    except BrowserCliError as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
