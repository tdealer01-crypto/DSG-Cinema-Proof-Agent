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
MARKETPLACE = ROOT / ".github" / "plugin" / "marketplace.json"
COPILOT_EVIDENCE = ROOT / "evidence" / "client" / "copilot-cli-plugin-e2e-2026-08-21.json"
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


def test_copilot_marketplace_catalog_points_to_the_portable_plugin():
    catalog = _json(MARKETPLACE)
    assert set(catalog) == {"name", "owner", "metadata", "plugins"}
    assert catalog["name"] == "dsg-agent-plugins"
    assert catalog["owner"]["name"] == "DSG ONE"
    assert catalog["metadata"]["version"] == "1.0.0"
    assert len(catalog["plugins"]) == 1

    entry = catalog["plugins"][0]
    manifest = _json(PLUGIN / "plugin.json")
    assert entry["name"] == manifest["name"] == "dsg-governance"
    assert entry["version"] == manifest["version"] == "1.0.0"
    assert entry["source"] == "./marketplace/agent-plugin"
    assert entry["strict"] is True
    assert "mcpServers" not in entry

    source = (ROOT / entry["source"].removeprefix("./")).resolve()
    assert source == PLUGIN.resolve()
    assert source.is_dir()
    assert (source / "plugin.json").is_file()


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


def test_plugin_truth_boundary_tracks_client_surfaces_separately():
    readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
    assert "VS Code / GitHub Copilot client install" in readme
    assert "Copilot CLI client install" in readme
    assert "Copilot CLI authenticated DSG MCP tool call" in readme
    assert readme.count("NOT VERIFIED") >= 3
    assert "Package conformance is not client compatibility" in readme
    assert "copilot plugin marketplace add tdealer01-crypto/DSG-Cinema-Proof-Agent" in readme
    assert "copilot plugin install dsg-governance@dsg-agent-plugins" in readme
    assert "32482954936" in readme
    assert "1.0.80" in readme


def test_copilot_cli_install_evidence_is_specific_and_does_not_claim_mcp():
    evidence = _json(COPILOT_EVIDENCE)
    assert evidence["client"] == "GitHub Copilot CLI"
    assert evidence["client_version"] == "1.0.80"
    assert evidence["workflow_run_id"] == 32482954936
    assert evidence["workflow_job_id"] == 96773122774
    assert evidence["marketplace_name"] == "dsg-agent-plugins"
    assert evidence["plugin_name"] == "dsg-governance"
    assert evidence["plugin_version"] == "1.0.0"
    assert all(value == "PASS" for value in evidence["results"].values())
    assert evidence["authenticated_mcp_tool_call"] == "NOT_RUN"
    assert evidence["artifact"]["digest"].startswith("sha256:")


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
