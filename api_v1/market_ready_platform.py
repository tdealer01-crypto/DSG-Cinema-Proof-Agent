from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("DSG_MARKET_READY_RUNTIME", str(ROOT / ".market-ready-runtime"))).resolve()
APPS = RUNTIME / "apps"
STATE = RUNTIME / "state"
TEMPLATE = ROOT / "web" / "customer-dashboard"
SOURCE = RUNTIME / "source-repo"
SOURCE_BARE = RUNTIME / "source-repo.git"
for p in (RUNTIME, APPS, STATE):
    p.mkdir(parents=True, exist_ok=True)

MASTER_SECRET_RAW = os.environ.get("DSG_PROVISIONER_SECRET", "").strip()
MASTER_SECRET = MASTER_SECRET_RAW.encode()
SANDBOX_MODE = os.environ.get("DSG_SANDBOX_MODE", "1") == "1"
REQUIRE_PLATFORM_AUTH = os.environ.get("DSG_PLATFORM_REQUIRE_AUTH", "0") == "1"
GITHUB_APP_INSTALL_URL = os.environ.get("DSG_GITHUB_APP_INSTALL_URL", "").strip()
GITHUB_APP_ID = os.environ.get("DSG_GITHUB_APP_ID", "").strip()
GITHUB_WEBHOOK_SECRET = os.environ.get("DSG_GITHUB_WEBHOOK_SECRET", "").strip()
PRODUCTION_E2E_PROVEN = os.environ.get("DSG_PRODUCTION_E2E_PROVEN", "0") == "1"

LOCK = threading.RLock()
INSTALL_LOCKS: dict[str, threading.RLock] = {}

router = APIRouter(prefix="/platform", tags=["market-ready-install"])


def now() -> float:
    return time.time()


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def install_lock(install_id: str) -> threading.RLock:
    with LOCK:
        return INSTALL_LOCKS.setdefault(install_id, threading.RLock())


def state_path(install_id: str) -> Path:
    return STATE / f"{install_id}.json"


def load_install(install_id: str) -> dict[str, Any]:
    path = state_path(install_id)
    if not path.exists():
        raise HTTPException(404, "installation not found")
    return json.loads(path.read_text(encoding="utf-8"))


def save_install(s: dict[str, Any]) -> None:
    s["updated_at_unix"] = now()
    atomic_json(state_path(s["installation_id"]), s)


def platform_auth(x_dsg_api_key: str | None) -> None:
    if not REQUIRE_PLATFORM_AUTH:
        return
    supplied = (x_dsg_api_key or "").strip()
    if not supplied:
        raise HTTPException(401, "workspace authentication required")
    from revenue import api as billing
    if billing.get_engine().accounts.authenticate(supplied) is None:
        raise HTTPException(401, "missing or invalid DSG API key")


def provisioner_secret_ready() -> bool:
    return len(MASTER_SECRET_RAW) >= 32


def callback_signature(install_id: str, target_id: str, nonce: str, authorized: bool) -> str:
    canonical = f"{install_id}\n{target_id}\n{nonce}\n{str(authorized).lower()}".encode()
    return hmac.new(MASTER_SECRET, canonical, hashlib.sha256).hexdigest()


def ensure_local_source_repo() -> str:
    """Create a deterministic local Git source from the bundled customer template once."""
    with LOCK:
        commit_file = RUNTIME / "source_commit.txt"
        if SOURCE_BARE.exists() and commit_file.exists():
            return commit_file.read_text(encoding="utf-8").strip()
        shutil.rmtree(SOURCE, ignore_errors=True)
        shutil.rmtree(SOURCE_BARE, ignore_errors=True)
        commit_file.unlink(missing_ok=True)
        if not shutil.which("git"):
            raise RuntimeError("git executable is required by the sandbox local-git provider")
        shutil.copytree(TEMPLATE, SOURCE)
        subprocess.run(["git", "init", "-q", str(SOURCE)], check=True)
        subprocess.run(["git", "-C", str(SOURCE), "config", "user.email", "sandbox@dsg.invalid"], check=True)
        subprocess.run(["git", "-C", str(SOURCE), "config", "user.name", "DSG Sandbox"], check=True)
        subprocess.run(["git", "-C", str(SOURCE), "add", "."], check=True)
        subprocess.run(["git", "-C", str(SOURCE), "commit", "-qm", "DSG customer template snapshot"], check=True)
        commit = subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
        subprocess.run(["git", "clone", "-q", "--bare", str(SOURCE), str(SOURCE_BARE)], check=True)
        commit_file.write_text(commit + "\n", encoding="utf-8")
        return commit


def clone_target(target_id: str) -> tuple[Path, str]:
    commit = ensure_local_source_repo()
    target = APPS / target_id
    if target.exists():
        return target, commit
    temp = APPS / f".{target_id}.{uuid.uuid4().hex}.tmp"
    subprocess.run(["git", "clone", "-q", "--shared", str(SOURCE_BARE), str(temp)], check=True, timeout=30)
    head = subprocess.check_output(["git", "-C", str(temp), "rev-parse", "HEAD"], text=True).strip()
    if head != commit:
        shutil.rmtree(temp, ignore_errors=True)
        raise RuntimeError(f"source HEAD mismatch: {head} != {commit}")
    temp.rename(target)
    return target, commit


def detect_framework(root: Path) -> dict[str, Any]:
    files = {p.name.lower() for p in root.iterdir() if p.is_file()}
    signals: list[str] = []
    frameworks: list[str] = []
    package = root / "package.json"
    if package.exists():
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        signals.append("package.json")
        if "next" in deps:
            frameworks.append("Next.js")
        if "react" in deps:
            frameworks.append("React")
        if not frameworks:
            frameworks.append("Node.js")
    if (root / "requirements.txt").exists() or (root / "pyproject.toml").exists() or (root / "server.py").exists():
        frameworks.append("Python")
        signals.append("python")
        text = ""
        for name in ("requirements.txt", "pyproject.toml", "server.py"):
            p = root / name
            if p.exists():
                try:
                    text += p.read_text(encoding="utf-8", errors="ignore").lower()
                except Exception:
                    pass
        if "fastapi" in text:
            frameworks.append("FastAPI")
    if (root / "Dockerfile").exists():
        frameworks.append("Docker")
        signals.append("Dockerfile")
    if (root / "pnpm-workspace.yaml").exists() or (root / "turbo.json").exists():
        frameworks.append("Monorepo")
        signals.append("workspace")
    if not frameworks and "index.html" in files and ({"app.js", "dashboard.js"} & files):
        frameworks.append("Static Web")
        signals.append("index.html + app.js")
    frameworks = list(dict.fromkeys(frameworks))
    return {
        "frameworks": frameworks or ["Unknown"],
        "signals": signals,
        "recommended_install": "github" if (root / ".git").exists() else "api",
    }


def provision_files(s: dict[str, Any]) -> dict[str, str]:
    target, source_commit = clone_target(s["target_id"])
    dsg = target / ".dsg"
    workflows = target / ".github" / "workflows"
    dsg.mkdir(parents=True, exist_ok=True)
    workflows.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema": "dsg.installation.v2",
        "installation_id": s["installation_id"],
        "target_id": s["target_id"],
        "integration": s["integration"],
        "install_path": s["install_path"],
        "scope": s["scope"],
        "permissions": s["permissions"],
        "source_commit": source_commit,
        "status": "PROVISIONED",
    }
    manifest_path = dsg / "installation.json"
    atomic_json(manifest_path, manifest)

    verify_path = dsg / "verify_install.py"
    verify_path.write_text(
        """from pathlib import Path\nimport json, hashlib, sys\nroot=Path(__file__).resolve().parents[1]\nm=json.loads((root/'.dsg/installation.json').read_text())\nrequired=[root/'.dsg/installation.json',root/'.github/workflows/dsg-governance.yml']\nok=m.get('schema')=='dsg.installation.v2' and m.get('status')=='PROVISIONED' and all(p.exists() for p in required)\nprint('DSG_INSTALL_VERIFY=PASS' if ok else 'DSG_INSTALL_VERIFY=FAIL')\nsys.exit(0 if ok else 1)\n""",
        encoding="utf-8",
    )

    workflow = workflows / "dsg-governance.yml"
    workflow.write_text(
        """name: DSG Governance\non:\n  workflow_dispatch:\n  pull_request:\npermissions:\n  contents: read\njobs:\n  dsg-installation-check:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.x'\n      - run: python .dsg/verify_install.py\n""",
        encoding="utf-8",
    )
    return {
        ".dsg/installation.json": sha256_file(manifest_path),
        ".dsg/verify_install.py": sha256_file(verify_path),
        ".github/workflows/dsg-governance.yml": sha256_file(workflow),
    }


def verify_installation(s: dict[str, Any]) -> dict[str, Any]:
    target = APPS / s["target_id"]
    missing: list[str] = []
    mismatches: list[str] = []
    required = [
        target / ".dsg" / "installation.json",
        target / ".dsg" / "verify_install.py",
        target / ".github" / "workflows" / "dsg-governance.yml",
    ]
    for path in required:
        if not path.exists():
            missing.append(str(path.relative_to(target)))
    for rel, expected in (s.get("artifact_hashes") or {}).items():
        path = target / rel
        if not path.exists() or sha256_file(path) != expected:
            mismatches.append(rel)
    manifest_ok = False
    manifest_path = target / ".dsg" / "installation.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_ok = (
                manifest.get("installation_id") == s["installation_id"]
                and manifest.get("target_id") == s["target_id"]
                and manifest.get("status") == "PROVISIONED"
            )
        except Exception:
            manifest_ok = False
    callback_ok = s.get("callback_verified") is True
    ok = not missing and not mismatches and manifest_ok and callback_ok
    return {
        "ok": ok,
        "missing": missing,
        "hash_mismatches": mismatches,
        "manifest_ok": manifest_ok,
        "callback_verified": callback_ok,
    }


def make_first_result(s: dict[str, Any]) -> dict[str, Any]:
    canonical = json.dumps({
        "installation_id": s["installation_id"],
        "target_id": s["target_id"],
        "artifact_hashes": s.get("artifact_hashes") or {},
        "source_commit": s.get("source_commit"),
    }, sort_keys=True, separators=(",", ":")).encode()
    return {
        "kind": "INSTALLATION_INTEGRITY_PROOF",
        "verified": True,
        "decision": "PASS",
        "proof_hash": hashlib.sha256(canonical).hexdigest(),
        "claim": "DSG installation artifacts and callback binding were verified in the managed target.",
        "not_claimed": "This is not a production provider/deployment proof unless the callback came from that live provider, and it is not an AI-model quality claim.",
        "recorded_at_unix": now(),
    }


def doctor(s: dict[str, Any]) -> dict[str, Any]:
    target = APPS / s["target_id"]
    verification = verify_installation(s)
    git_head = None
    git_ok = False
    try:
        git_head = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True).strip()
        source_commit = (RUNTIME / "source_commit.txt").read_text(encoding="utf-8").strip()
        git_ok = git_head == source_commit
    except Exception:
        pass
    framework = detect_framework(target) if target.exists() else {"frameworks": ["Unknown"], "signals": []}
    checks = [
        {"name": "authorization_callback", "ok": s.get("callback_verified") is True, "detail": "Signed callback verified" if s.get("callback_verified") else "No verified callback"},
        {"name": "scope_bound", "ok": bool(s.get("scope")), "detail": s.get("scope") or "Missing scope"},
        {"name": "minimum_permissions_reviewed", "ok": bool(s.get("permissions")) and len(s.get("permissions", [])) <= 6, "detail": ", ".join(s.get("permissions") or [])},
        {"name": "manifest", "ok": verification["manifest_ok"], "detail": "Installation manifest matches target" if verification["manifest_ok"] else "Manifest mismatch"},
        {"name": "artifact_integrity", "ok": not verification["hash_mismatches"], "detail": "Artifact hashes match" if not verification["hash_mismatches"] else "Changed: " + ", ".join(verification["hash_mismatches"])},
        {"name": "source_lineage", "ok": git_ok, "detail": f"HEAD {git_head[:12]}" if git_head else "Git lineage unavailable"},
        {"name": "framework_detected", "ok": framework["frameworks"] != ["Unknown"], "detail": ", ".join(framework["frameworks"])},
        {"name": "first_result", "ok": bool(s.get("first_result")), "detail": "Verified first result exists" if s.get("first_result") else "Run first result after installation"},
    ]
    overall = all(c["ok"] for c in checks[:-1]) and verification["ok"]
    return {"ok": overall, "checks": checks, "framework": framework, "verification": verification}


class InstallStart(BaseModel):
    target_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    integration: Literal["mcp", "github", "api"] = "github"
    install_path: Literal["web", "ai", "cli"] = "web"
    scope: str = Field(default="selected-repository", max_length=120)
    permissions: list[str] = Field(default_factory=lambda: ["metadata:read", "contents:read", "actions:write"])
    admin_required: bool = False


class CallbackBody(BaseModel):
    installation_id: str
    target_id: str
    nonce: str
    authorized: bool = True


class AdminRequestBody(BaseModel):
    installation_id: str
    reason: str = "Repository owner approval required"


@router.get("/health")
def health() -> dict[str, Any]:
    source_commit = None
    source_error = None
    try:
        source_commit = ensure_local_source_repo()
    except Exception as exc:
        source_error = str(exc)
    return {
        "ok": source_error is None,
        "service": "dsg-one-market-ready",
        "version": "2.0.0",
        "sandbox_mode": SANDBOX_MODE,
        "source_commit": source_commit,
        "source_error": source_error,
    }


@router.get("/readiness")
def readiness() -> JSONResponse:
    h = health()
    checks = {
        "local_source": h["source_error"] is None,
        "template_present": TEMPLATE.exists(),
        "state_writable": os.access(STATE, os.W_OK),
        "cinema_backend_configured": True,
        "production_github_install_url": bool(GITHUB_APP_INSTALL_URL),
        "production_github_app_id": bool(GITHUB_APP_ID),
        "production_github_webhook_secret": bool(GITHUB_WEBHOOK_SECRET),
        "production_secret_configured": provisioner_secret_ready(),
        "production_e2e_proven": PRODUCTION_E2E_PROVEN,
    }
    runtime_checks = ["local_source", "template_present", "state_writable", "cinema_backend_configured"]
    configuration_checks = [
        "production_github_install_url", "production_github_app_id",
        "production_github_webhook_secret", "production_secret_configured",
    ]
    configuration_ready = all(checks[k] for k in configuration_checks) and not SANDBOX_MODE
    production_ready = configuration_ready and checks["production_e2e_proven"]
    body = {
        "ok": all(checks[k] for k in runtime_checks),
        "configuration_ready": configuration_ready,
        "production_ready": production_ready,
        "checks": checks,
        "truth_boundary": (
            "Sandbox local-git provisioning is real. production_ready remains false until live GitHub/Azure "
            "end-to-end deployment evidence has been produced and DSG_PRODUCTION_E2E_PROVEN=1 is set by the deployment pipeline."
        ),
    }
    return JSONResponse(body, status_code=200 if body["ok"] else 503)


@router.get("/capabilities")
def capabilities() -> dict[str, Any]:
    return {
        "install_paths": ["web", "ai", "cli"],
        "integrations": ["mcp", "github", "api"],
        "features": [
            "scope_review", "minimum_permissions", "admin_approval_request", "signed_callback",
            "framework_detection", "automatic_provisioning", "installation_doctor", "repair",
            "lifecycle", "first_verified_result", "tamper_detection",
        ],
        "sandbox_mode": SANDBOX_MODE,
        "github_native_redirect": GITHUB_APP_INSTALL_URL or None,
    }


@router.post("/install/start")
def install_start(body: InstallStart, x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key")) -> dict[str, Any]:
    platform_auth(x_dsg_api_key)
    for path in STATE.glob("*.json"):
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
            if prior.get("target_id") == body.target_id and prior.get("status") not in ("UNINSTALLED", "DENIED"):
                raise HTTPException(409, "target already has an active installation")
        except HTTPException:
            raise
        except Exception:
            continue
    target, commit = clone_target(body.target_id)
    install_id = "ins_" + uuid.uuid4().hex
    nonce = secrets.token_urlsafe(24)
    framework = detect_framework(target)
    status = "PENDING_ADMIN" if body.admin_required else "WAITING_AUTHORIZATION"
    s = {
        "installation_id": install_id,
        "target_id": body.target_id,
        "integration": body.integration,
        "install_path": body.install_path,
        "scope": body.scope,
        "permissions": body.permissions,
        "nonce": nonce,
        "status": status,
        "callback_verified": False,
        "framework": framework,
        "source_commit": commit,
        "lifecycle": [{"state": status, "at": now()}],
        "created_at_unix": now(),
    }
    save_install(s)
    return {
        "installation_id": install_id,
        "target_id": body.target_id,
        "status": status,
        "framework": framework,
        "scope": body.scope,
        "permissions": body.permissions,
        "admin_required": body.admin_required,
        "github_install_url": GITHUB_APP_INSTALL_URL or None,
        "sandbox_authorization_available": SANDBOX_MODE,
    }


@router.post("/install/request-admin")
def request_admin(body: AdminRequestBody, x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key")) -> dict[str, Any]:
    platform_auth(x_dsg_api_key)
    with install_lock(body.installation_id):
        s = load_install(body.installation_id)
        s["status"] = "ADMIN_APPROVAL_REQUESTED"
        s["admin_request"] = {"reason": body.reason, "requested_at_unix": now()}
        s["lifecycle"].append({"state": "ADMIN_APPROVAL_REQUESTED", "at": now()})
        save_install(s)
    return {"installation_id": body.installation_id, "status": s["status"], "message": "Approval request recorded; no external notification is claimed unless the provider confirms delivery."}


@router.post("/sandbox/authorize/{install_id}")
def sandbox_authorize(install_id: str, authorized: bool = True, x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key")) -> dict[str, Any]:
    platform_auth(x_dsg_api_key)
    if not SANDBOX_MODE:
        raise HTTPException(404, "sandbox authorization disabled")
    s = load_install(install_id)
    sig = callback_signature(s["installation_id"], s["target_id"], s["nonce"], authorized)
    body = CallbackBody(installation_id=s["installation_id"], target_id=s["target_id"], nonce=s["nonce"], authorized=authorized)
    return process_callback(body, sig)


def process_callback(body: CallbackBody, signature: str) -> dict[str, Any]:
    if not provisioner_secret_ready():
        raise HTTPException(503, "DSG_PROVISIONER_SECRET is not configured")
    with install_lock(body.installation_id):
        s = load_install(body.installation_id)
        expected = callback_signature(body.installation_id, body.target_id, body.nonce, body.authorized)
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(401, "invalid callback signature")
        if body.target_id != s["target_id"] or body.nonce != s["nonce"]:
            raise HTTPException(400, "callback binding mismatch")
        if not body.authorized:
            s["status"] = "DENIED"
            s["lifecycle"].append({"state": "DENIED", "at": now()})
            save_install(s)
            return {"installation_id": body.installation_id, "status": "DENIED"}
        s["status"] = "AUTHORIZED"
        s["lifecycle"].append({"state": "AUTHORIZED", "at": now()})
        hashes = provision_files(s)
        s["artifact_hashes"] = hashes
        s["callback_verified"] = True
        s["status"] = "PROVISIONED"
        s["lifecycle"].append({"state": "PROVISIONED", "at": now()})
        result = verify_installation(s)
        s["status"] = "VERIFIED" if result["ok"] else "VERIFY_FAILED"
        s["lifecycle"].append({"state": s["status"], "at": now()})
        first = None
        if result["ok"]:
            s["verified_at_unix"] = now()
            first = make_first_result(s)
            s["first_result"] = first
            s["lifecycle"].append({"state": "FIRST_RESULT_VERIFIED", "at": now()})
            s["status"] = "HEALTHY"
            s["lifecycle"].append({"state": "HEALTHY", "at": now()})
        save_install(s)
    return {"installation_id": body.installation_id, "target_id": body.target_id, "status": s["status"], "verification": result, "first_result": first}


@router.post("/install/callback")
def install_callback(body: CallbackBody, x_dsg_callback_signature: str | None = Header(default=None, alias="X-DSG-Callback-Signature")) -> dict[str, Any]:
    return process_callback(body, x_dsg_callback_signature or "")


@router.get("/install/{install_id}")
def install_status(install_id: str, x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key")) -> dict[str, Any]:
    platform_auth(x_dsg_api_key)
    s = load_install(install_id)
    public = {k: v for k, v in s.items() if k != "nonce"}
    public["verification"] = verify_installation(s) if s.get("callback_verified") else {"ok": False, "reason": "callback not verified"}
    return public


@router.post("/install/{install_id}/doctor")
def install_doctor(install_id: str, x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key")) -> dict[str, Any]:
    platform_auth(x_dsg_api_key)
    s = load_install(install_id)
    result = doctor(s)
    s["last_doctor"] = {"at": now(), "ok": result["ok"]}
    save_install(s)
    return result


@router.post("/install/{install_id}/repair")
def install_repair(install_id: str, x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key")) -> dict[str, Any]:
    platform_auth(x_dsg_api_key)
    with install_lock(install_id):
        s = load_install(install_id)
        if not s.get("callback_verified"):
            raise HTTPException(409, "cannot repair before authorization callback is verified")
        hashes = provision_files(s)
        s["artifact_hashes"] = hashes
        result = verify_installation(s)
        s["status"] = "VERIFIED" if result["ok"] else "VERIFY_FAILED"
        s["lifecycle"].append({"state": "REPAIRED" if result["ok"] else "REPAIR_FAILED", "at": now()})
        save_install(s)
    return {"installation_id": install_id, "status": s["status"], "verification": result}


@router.post("/install/{install_id}/first-result")
def first_result(install_id: str, x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key")) -> dict[str, Any]:
    platform_auth(x_dsg_api_key)
    with install_lock(install_id):
        s = load_install(install_id)
        if s.get("first_result"):
            return s["first_result"]
        verification = verify_installation(s)
        if not verification["ok"] or s.get("status") not in ("VERIFIED", "HEALTHY"):
            raise HTTPException(409, "installation must be verified before first result")
        result = make_first_result(s)
        s["first_result"] = result
        s["status"] = "HEALTHY"
        s["lifecycle"].append({"state": "FIRST_RESULT_VERIFIED", "at": now()})
        s["lifecycle"].append({"state": "HEALTHY", "at": now()})
        save_install(s)
    return result


@router.delete("/install/{install_id}")
def uninstall(install_id: str, x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key")) -> dict[str, Any]:
    platform_auth(x_dsg_api_key)
    with install_lock(install_id):
        s = load_install(install_id)
        target = APPS / s["target_id"]
        shutil.rmtree(target, ignore_errors=True)
        s["status"] = "UNINSTALLED"
        s["lifecycle"].append({"state": "UNINSTALLED", "at": now()})
        save_install(s)
    return {"installation_id": install_id, "status": "UNINSTALLED"}


@router.get("/frameworks/{target_id}")
def framework_for_target(target_id: str) -> dict[str, Any]:
    target = APPS / target_id
    if not target.exists():
        raise HTTPException(404, "target not found")
    return detect_framework(target)


def install(app: Any) -> None:
    """Install the Market-Ready provisioning surface into Cinema."""
    app.include_router(router)
