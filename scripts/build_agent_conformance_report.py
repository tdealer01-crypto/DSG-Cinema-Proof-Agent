#!/usr/bin/env python3
"""Build a compact evidence report from deterministic pytest/JUnit results.

This report intentionally distinguishes repository conformance from real client
compatibility.  CI timing is useful for regression comparison but is not a
production latency claim, and CI does not invent a dollar cost when no real
billing event occurred.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET


CASES = {
    "plugin_manifest_conformance": "test_plugin_manifest_targets_agent_plugins_v1_and_uses_only_portable_fields",
    "plugin_mcp_secret_boundary": "test_mcp_config_is_https_streamable_http_and_contains_no_embedded_credentials",
    "plugin_skill_conformance": "test_agent_skill_frontmatter_conforms_and_name_matches_directory",
    "mcp_initialize_and_tools": "test_dsg_mcp_endpoint_performs_initialize_and_exposes_governance_tools",
    "approved_action_completion": "test_clean_run_is_allowed_only_behind_a_proof",
    "out_of_plan_rejection": "test_out_of_plan_action_blocks_even_though_the_agent_cannot_say_otherwise",
    "z3_constraint_correctness": "test_constraints_violation_is_proved_as_block",
    "replay_mismatch_detection": "test_replay_mismatch_downgrades_to_review",
    "evidence_integrity": "test_evidence_that_misdescribes_its_own_hash_is_rejected",
    "fail_closed_verifier": "test_verification_fails_closed_and_issues_no_receipt",
    "checkout_without_entitlement": "test_checkout_creates_customer_and_session_without_granting_entitlement",
    "webhook_entitlement_boundary": "test_signed_scoped_subscription_event_is_what_promotes_plan",
}


def _status(case: ET.Element) -> str:
    if case.find("failure") is not None or case.find("error") is not None:
        return "FAIL"
    if case.find("skipped") is not None:
        return "SKIP"
    return "PASS"


def build(junit_path: Path) -> dict:
    root = ET.parse(junit_path).getroot()
    testcases = {case.attrib.get("name", ""): case for case in root.iter("testcase")}

    checks = {}
    missing = []
    total_seconds = 0.0
    for key, test_name in CASES.items():
        case = testcases.get(test_name)
        if case is None:
            checks[key] = {
                "status": "MISSING",
                "test": test_name,
                "duration_ms": None,
            }
            missing.append(test_name)
            continue
        seconds = float(case.attrib.get("time", "0") or 0)
        total_seconds += seconds
        checks[key] = {
            "status": _status(case),
            "test": test_name,
            "duration_ms": round(seconds * 1000, 3),
        }

    report_status = (
        "PASS"
        if not missing and all(item["status"] == "PASS" for item in checks.values())
        else "FAIL"
    )
    return {
        "schema": "dsg-agent-conformance-report/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": report_status,
        "scope": {
            "package": "Agent Plugins 1.0 structure + Agent Skill + DSG MCP",
            "execution": "deterministic repository CI using the test verifier fixture",
            "production_latency_claim": False,
            "production_cost_claim": False,
        },
        "checks": checks,
        "metrics": {
            "mapped_test_duration_ms": round(total_seconds * 1000, 3),
            "cost_per_run": None,
            "cost_status": "NOT_MEASURED_IN_CI",
        },
        "client_compatibility": {
            "vscode_copilot": "NOT_RUN",
            "copilot_cli": "NOT_RUN",
            "other_agent_plugins_clients": "NOT_RUN",
        },
        "missing_required_tests": missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    report = build(args.junit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
