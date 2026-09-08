from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "marketplace" / "agent-plugin"
MARKETPLACE = ROOT / ".github" / "plugin" / "marketplace.json"
COPILOT_EVIDENCE = ROOT / "evidence" / "client" / "copilot-cli-plugin-e2e-2026-08-21.json"
COPILOT_MCP_EVIDENCE = ROOT / "evidence" / "client" / "copilot-cli-mcp-auth-e2e-2026-08-21.json"
COPILOT_FULL_EVIDENCE = ROOT / "evidence" / "client" / "copilot-cli-full-governed-e2e-2026-08-21.json"
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
PLUGIN_RELEASE = "1.1.0"
SPACETIME_MCP_URL = (
    "https://dsg-spacetime-prod.greenglacier-493f3f71.westus3.azurecontainerapps.io/mcp"
)
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


def test_plugin_manifest_targets_agent_plugins_v1_and_spacetime_release():
    manifest = _json(PLUGIN / "plugin.json")
    assert manifest["$schema"] == PLUGIN_SCHEMA
    assert set(manifest) <= PLUGIN_FIELDS
    assert manifest["name"] == "dsg-governance"
    assert manifest["version"] == PLUGIN_RELEASE
    assert PLUGIN_NAME_RE.fullmatch(manifest["name"])
    assert "--" not in manifest["name"]
    assert ".." not in manifest["name"]
    assert manifest["repository"] == "https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent"
    assert "spacetime" in {item.lower() for item in manifest["keywords"]}


def test_copilot_marketplace_catalog_points_to_spacetime_plugin_release():
    catalog = _json(MARKETPLACE)
    assert set(catalog) == {"name", "owner", "metadata", "plugins"}
    assert catalog["name"] == "dsg-agent-plugins"
    assert catalog["owner"]["name"] == "DSG ONE"
    assert catalog["metadata"]["version"] == PLUGIN_RELEASE
    assert len(catalog["plugins"]) == 1

    entry = catalog["plugins"][0]
    manifest = _json(PLUGIN / "plugin.json")
    assert entry["name"] == manifest["name"] == "dsg-governance"
    assert entry["version"] == manifest["version"] == PLUGIN_RELEASE
    assert entry["source"] == "./marketplace/agent-plugin"
    assert entry["strict"] is True
    assert "mcpServers" not in entry

    source = (ROOT / entry["source"].removeprefix("./")).resolve()
    assert source == PLUGIN.resolve()
    assert source.is_dir()
    assert (source / "plugin.json").is_file()
    assert (source / "mcp.json").is_file()


def test_mcp_config_targets_spacetime_https_without_embedded_credentials():
    config = _json(PLUGIN / "mcp.json")
    assert set(config) == {"$schema", "mcpServers"}
    assert config["$schema"] == MCP_SCHEMA
    assert set(config["mcpServers"]) == {"dsg-spacetime"}

    server = config["mcpServers"]["dsg-spacetime"]
    assert set(server) == {"type", "url"}
    assert server["type"] == "streamable-http"
    assert server["url"] == SPACETIME_MCP_URL

    parsed = urlsplit(server["url"])
    assert parsed.scheme == "https"
    assert parsed.hostname == "dsg-spacetime-prod.greenglacier-493f3f71.westus3.azurecontainerapps.io"
    assert parsed.username is None and parsed.password is None
    assert parsed.fragment == ""
    assert parsed.path == "/mcp"
    assert "headers" not in server

    serialized = json.dumps(config).lower()
    for secret_marker in (
        "authorization",
        "bearer ",
        "x-dsg-api-key",
        "dsg_spacetime_api_key=",
        "sk_live_",
        "sk_test_",
        "whsec_",
    ):
        assert secret_marker not in serialized


def test_agent_skill_targets_canonical_spacetime_flow():
    skill_path = PLUGIN / "skills" / "dsg-governed-execution" / "SKILL.md"
    metadata, body = _frontmatter(skill_path)

    assert metadata["name"] == skill_path.parent.name
    assert SKILL_NAME_RE.fullmatch(metadata["name"])
    assert metadata["metadata"]["version"] == PLUGIN_RELEASE
    assert "Agent Plugins 1.0" in metadata["compatibility"]
    assert "DSG_SPACETIME_API_KEY" in metadata["compatibility"]
    assert body.lstrip().startswith("# DSG Governed Execution")

    for tool in (
        "spacetime_discover",
        "spacetime_compose",
        "spacetime_execute",
        "spacetime_verify_evidence",
    ):
        assert f"`{tool}`" in body

    for legacy_tool in (
        "dsg_create_plan",
        "dsg_approve_plan",
        "dsg_record_execution",
        "dsg_get_proof",
        "dsg_live_start",
    ):
        assert legacy_tool not in body

    assert "Never call the external provider directly as a fallback" in body
    assert "connection failure is never approval" in body


def test_spacetime_package_contract_declares_canonical_tools_and_client_managed_auth():
    readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
    assert "MCP protocol 2025-06-18" in readme
    assert "Bearer authentication via client-managed DSG_SPACETIME_API_KEY" in readme
    assert "plugin installation and authenticated MCP use are separate gates" in readme
    assert "client credential binding is required" in readme
    assert "copilot mcp add --transport http" in readme
    assert "dsg-spacetime-auth" in readme
    for tool in (
        "spacetime_discover",
        "spacetime_compose",
        "spacetime_execute",
        "spacetime_verify_evidence",
    ):
        assert tool in readme


def test_plugin_readme_separates_current_release_from_historical_client_evidence():
    readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
    assert "Plugin release:** `1.1.0`" in readme
    assert "Agent Plugins specification:** `1.0.0`" in readme
    assert SPACETIME_MCP_URL.removesuffix("/mcp") in readme
    assert "spacetime_execute" in readme
    assert "copilot plugin marketplace update dsg-agent-plugins" in readme
    assert "copilot plugin update dsg-governance" in readme
    assert "32482954936" in readme
    assert "32497793523" in readme
    assert "32499134400" in readme
    assert "HISTORICAL v1.0.0" in readme
    assert readme.count("NOT VERIFIED") >= 3
    assert "Historical v1.0.0 client runs do not prove v1.1.0 client compatibility" in readme
    assert "Copilot CLI — plugin v1.0.0" in readme


def test_historical_copilot_evidence_remains_bound_to_v1_0_0():
    install = _json(COPILOT_EVIDENCE)
    assert install["client"] == "GitHub Copilot CLI"
    assert install["workflow_run_id"] == 32482954936
    assert install["plugin_version"] == "1.0.0"
    assert all(value == "PASS" for value in install["results"].values())

    mcp = _json(COPILOT_MCP_EVIDENCE)
    assert mcp["workflow_run_id"] == 32497793523
    assert mcp["mcp_url"].endswith("/api/v1/mcp")
    assert all(value == "PASS" for value in mcp["results"].values())

    full = _json(COPILOT_FULL_EVIDENCE)
    assert full["workflow_run_id"] == 32499134400
    assert full["mcp_url"].endswith("/api/v1/mcp")
    assert full["receipt"]["decision"] == "ALLOW"
    assert full["receipt"]["receipt_hash_verified"] is True


def test_revenue_reference_matches_spacetime_entitlement_boundary():
    text = (
        PLUGIN
        / "skills"
        / "dsg-governed-execution"
        / "references"
        / "revenue.md"
    ).read_text(encoding="utf-8")
    assert "DSG Spacetime Revenue and Entitlement Boundary" in text
    assert "spacetime_execute" in text
    assert "DSG_SPACETIME_API_KEY" in text
    assert "does not embed billing credentials" in text
    assert "do not create a purchase automatically" in text
    assert "/billing/activate" not in text
    assert "/billing/checkout/session" not in text
