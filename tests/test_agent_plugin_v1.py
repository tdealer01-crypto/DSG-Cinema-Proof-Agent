from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from fastapi.testclient import TestClient

import cinema_main


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "marketplace" / "agent-plugin"
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
PLUGIN_FIELDS = {
    "$schema",
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "extensions",
}
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PLUGIN_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")

client = TestClient(cinema_main.app)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} must start with YAML frontmatter"
    end = text.find("\n---\n", 4)
    assert end >= 0, f"{path} has no closing YAML frontmatter marker"
    metadata = yaml.safe_load(text[4:end])
    assert isinstance(metadata, dict)
    return metadata, text[end + 5 :]


def test_plugin_manifest_targets_agent_plugins_v1_and_uses_only_portable_fields():
    manifest = _json(PLUGIN / "plugin.json")
    assert manifest["$schema"] == PLUGIN_SCHEMA
    assert set(manifest) <= PLUGIN_FIELDS
    assert isinstance(manifest["name"], str)
    assert 1 <= len(manifest["name"]) <= 64
    assert PLUGIN_NAME_RE.fullmatch(manifest["name"])
    assert "--" not in manifest["name"]
    assert ".." not in manifest["name"]
    assert manifest["name"] == "dsg-governance"
    assert manifest["repository"] == "https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent"


def test_mcp_config_is_https_streamable_http_and_contains_no_embedded_credentials():
    config = _json(PLUGIN / "mcp.json")
    assert set(config) == {"$schema", "mcpServers"}
    assert config["$schema"] == MCP_SCHEMA
    assert set(config["mcpServers"]) == {"dsg-one"}

    server = config["mcpServers"]["dsg-one"]
    assert set(server) == {"type", "url"}
    assert server["type"] == "streamable-http"
    parsed = urlsplit(server["url"])
    assert parsed.scheme == "https"
    assert parsed.username is None and parsed.password is None
    assert parsed.fragment == ""
    assert parsed.path == "/api/v1/mcp"
    assert "headers" not in server

    serialized = json.dumps(config).lower()
    for secret_marker in ("authorization", "bearer ", "x-dsg-api-key", "sk_live_", "sk_test_", "whsec_"):
        assert secret_marker not in serialized


def test_agent_skill_frontmatter_conforms_and_name_matches_directory():
    skill_path = PLUGIN / "skills" / "dsg-governed-execution" / "SKILL.md"
    metadata, body = _frontmatter(skill_path)

    assert metadata["name"] == skill_path.parent.name
    assert SKILL_NAME_RE.fullmatch(metadata["name"])
    assert 1 <= len(metadata["name"]) <= 64
    assert isinstance(metadata["description"], str)
    assert 1 <= len(metadata["description"]) <= 1024
    assert "Use" in metadata["description"] or "use" in metadata["description"]
    assert isinstance(metadata.get("compatibility"), str)
    assert len(metadata["compatibility"]) <= 500
    assert body.lstrip().startswith("# DSG Governed Execution")


def test_plugin_truth_boundary_does_not_claim_unrun_client_compatibility():
    readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
    assert "VS Code / GitHub Copilot client install" in readme
    assert "Copilot CLI client install" in readme
    assert readme.count("NOT VERIFIED") >= 3
    assert "Package conformance is not client compatibility" in readme


def test_dsg_mcp_endpoint_performs_initialize_and_exposes_governance_tools():
    initialized = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert initialized.status_code == 200
    init_body = initialized.json()
    assert init_body["result"]["serverInfo"]["name"] == "dsg-one"
    assert init_body["result"]["capabilities"]["tools"]["listChanged"] is False

    listed = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert listed.status_code == 200
    names = {tool["name"] for tool in listed.json()["result"]["tools"]}
    assert {
        "dsg_status",
        "dsg_create_plan",
        "dsg_approve_plan",
        "dsg_verify_plan_alignment",
        "dsg_verify_constraints",
        "dsg_record_execution",
        "dsg_submit_evidence",
        "dsg_verify_execution",
        "dsg_get_proof",
    } <= names


def test_revenue_reference_preserves_user_control_and_webhook_entitlement_boundary():
    text = (
        PLUGIN
        / "skills"
        / "dsg-governed-execution"
        / "references"
        / "revenue.md"
    ).read_text(encoding="utf-8")
    assert "POST /billing/activate" in text
    assert "POST /billing/checkout/session" in text
    assert "CHECKOUT_CREATED_NOT_ENTITLED" in text
    assert "signed Stripe webhook" in text
    assert "does not autonomously purchase" in text
