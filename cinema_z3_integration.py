#!/usr/bin/env python3
"""Fail-closed Cinema -> Z3 runtime integration helper.

This script never writes the Z3 secret into source code or Git history.
It reads secrets from environment variables, verifies the Z3 service, writes
server-side Azure App Service settings, restarts Cinema, and then performs an
end-to-end verification request through Cinema.

Required environment variables:
  Z3_SERVICE_URL=https://...
  Z3_API_SECRET=...

Optional environment variables:
  AZURE_RESOURCE_GROUP=rg-t.dealer01-0468
  CINEMA_APP_NAME=dsg-cinema-proof-agent
  CINEMA_BASE_URL=https://dsg-cinema-proof-agent.azurewebsites.net
  CINEMA_VERIFY_PATH=/solve

Usage:
  python3 cinema_z3_integration.py
  python3 cinema_z3_integration.py --verify-only
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_RESOURCE_GROUP = "rg-t.dealer01-0468"
DEFAULT_CINEMA_APP = "dsg-cinema-proof-agent"
DEFAULT_CINEMA_URL = "https://dsg-cinema-proof-agent.azurewebsites.net"
TEST_PAYLOAD = {
    "request_id": "cinema-z3-e2e",
    "preset_name": "cinema-e2e",
    "problem_type": "qubo",
    "linear": [-4, -3, 1],
    "quadratic": [[0, 1, 5], [1, 2, 2]],
    "proveOptimality": True,
    "z3TimeoutMs": 30000,
}


class IntegrationError(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise IntegrationError(f"missing required environment variable: {name}")
    return value


def require_https(url: str, name: str) -> str:
    normalized = url.rstrip("/")
    if not normalized.startswith("https://"):
        raise IntegrationError(f"{name} must use HTTPS")
    return normalized


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    bearer: str | None = None,
    timeout: int = 15,
) -> tuple[int, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                body = None
            else:
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    body = raw
            return response.status, body
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw
        return exc.code, body
    except URLError as exc:
        raise IntegrationError(f"request failed for {url}: {exc.reason}") from exc


def nested_values(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for current_key, current_value in value.items():
            if current_key == key:
                found.append(current_value)
            found.extend(nested_values(current_value, key))
    elif isinstance(value, list):
        for item in value:
            found.extend(nested_values(item, key))
    return found


def verify_exact_proof(body: Any, source: str) -> None:
    if not isinstance(body, dict):
        raise IntegrationError(f"{source} returned non-object JSON")

    verifications = nested_values(body, "verification")
    verified_flags = nested_values(body, "verified")
    proof_hashes = nested_values(body, "proof_hash")
    energies = nested_values(body, "energy_exact")

    if "VERIFIED_GLOBAL_OPTIMUM" not in verifications:
        raise IntegrationError(f"{source} did not return VERIFIED_GLOBAL_OPTIMUM")
    if True not in verified_flags:
        raise IntegrationError(f"{source} did not return verified=true")
    if not any(isinstance(item, str) and len(item) == 64 for item in proof_hashes):
        raise IntegrationError(f"{source} did not return a SHA-256 proof_hash")
    if "-4" not in [str(item) for item in energies]:
        raise IntegrationError(f"{source} returned an unexpected energy")


def verify_z3(service_url: str, secret: str) -> dict[str, Any]:
    code, ready = request_json(f"{service_url}/ready")
    if code != 200 or not isinstance(ready, dict) or ready.get("status") != "ready":
        raise IntegrationError(f"Z3 readiness failed: HTTP {code}")

    code, proof = request_json(
        f"{service_url}/solve",
        method="POST",
        payload=TEST_PAYLOAD,
        bearer=secret,
        timeout=45,
    )
    if code != 200:
        raise IntegrationError(f"Z3 solve failed: HTTP {code}")
    verify_exact_proof(proof, "Z3")
    return proof


def run_az(args: list[str]) -> str:
    if shutil.which("az") is None:
        raise IntegrationError("Azure CLI (az) is not installed")
    result = subprocess.run(
        ["az", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "Azure CLI failed"
        raise IntegrationError(message)
    return result.stdout.strip()


def configure_cinema(
    resource_group: str,
    cinema_app: str,
    service_url: str,
    secret: str,
) -> None:
    run_az(["account", "show", "--output", "none"])

    settings = [
        {
            "name": "DSG_BACKEND_BASE_URL",
            "value": service_url,
            "slotSetting": False,
        },
        {
            "name": "DSG_BACKEND_API_KEY",
            "value": secret,
            "slotSetting": False,
        },
    ]

    settings_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="dsg-cinema-settings-",
            delete=False,
        ) as handle:
            json.dump(settings, handle)
            settings_path = handle.name
        os.chmod(settings_path, 0o600)

        run_az(
            [
                "webapp",
                "config",
                "appsettings",
                "set",
                "--resource-group",
                resource_group,
                "--name",
                cinema_app,
                "--settings",
                f"@{settings_path}",
                "--output",
                "none",
            ]
        )
    finally:
        if settings_path and os.path.exists(settings_path):
            os.remove(settings_path)

    names_json = run_az(
        [
            "webapp",
            "config",
            "appsettings",
            "list",
            "--resource-group",
            resource_group,
            "--name",
            cinema_app,
            "--query",
            "[?name=='DSG_BACKEND_BASE_URL' || name=='DSG_BACKEND_API_KEY'].name",
            "--output",
            "json",
        ]
    )
    names = set(json.loads(names_json or "[]"))
    required = {"DSG_BACKEND_BASE_URL", "DSG_BACKEND_API_KEY"}
    if not required.issubset(names):
        raise IntegrationError("Cinema runtime settings were not persisted")

    run_az(
        [
            "webapp",
            "restart",
            "--resource-group",
            resource_group,
            "--name",
            cinema_app,
            "--output",
            "none",
        ]
    )


def wait_for_cinema(cinema_url: str) -> None:
    last_code = 0
    for _ in range(30):
        try:
            code, _ = request_json(f"{cinema_url}/health", timeout=10)
            last_code = code
            if code == 200:
                return
        except IntegrationError:
            pass
        time.sleep(5)
    raise IntegrationError(f"Cinema health did not recover; last HTTP status={last_code}")


def verify_through_cinema(
    cinema_url: str,
    verify_path: str,
    secret: str,
) -> dict[str, Any]:
    path = verify_path if verify_path.startswith("/") else f"/{verify_path}"
    code, body = request_json(
        f"{cinema_url}{path}",
        method="POST",
        payload=TEST_PAYLOAD,
        bearer=secret,
        timeout=60,
    )
    if code != 200:
        raise IntegrationError(f"Cinema verification failed: HTTP {code}")
    verify_exact_proof(body, "Cinema")
    return body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="verify Z3 and Cinema without changing Azure App Service settings",
    )
    args = parser.parse_args()

    try:
        service_url = require_https(require_env("Z3_SERVICE_URL"), "Z3_SERVICE_URL")
        secret = require_env("Z3_API_SECRET")
        if len(secret) < 32:
            raise IntegrationError("Z3_API_SECRET must be at least 32 characters")

        resource_group = os.getenv(
            "AZURE_RESOURCE_GROUP",
            DEFAULT_RESOURCE_GROUP,
        ).strip()
        cinema_app = os.getenv("CINEMA_APP_NAME", DEFAULT_CINEMA_APP).strip()
        cinema_url = require_https(
            os.getenv("CINEMA_BASE_URL", DEFAULT_CINEMA_URL).strip(),
            "CINEMA_BASE_URL",
        )
        verify_path = os.getenv("CINEMA_VERIFY_PATH", "/solve").strip() or "/solve"

        direct_proof = verify_z3(service_url, secret)
        print(
            "PASS Z3: exact optimum verified; proof_hash="
            + str(direct_proof.get("proof_hash", ""))
        )

        if not args.verify_only:
            configure_cinema(
                resource_group,
                cinema_app,
                service_url,
                secret,
            )
            print("PASS Cinema config: server-side Azure App Service settings persisted")
            wait_for_cinema(cinema_url)
            print("PASS Cinema health: HTTP 200 after restart")

        cinema_proof = verify_through_cinema(
            cinema_url,
            verify_path,
            secret,
        )
        print(
            "PASS E2E: Cinema returned verified Z3 proof; proof_hash="
            + str(nested_values(cinema_proof, "proof_hash")[0])
        )
        return 0
    except IntegrationError as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
