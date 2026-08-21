"""The published contract and the running app must not drift apart.

`openapi/dsg-one-v1.yaml` is what integrators build against. These tests keep it
honest: same paths, same methods, every reference resolvable, and no request
schema that would let a caller submit a verdict DSG is supposed to compute.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import cinema_main
from api_v1.models import ASSERTED_VERDICT_FIELDS

CONTRACT_PATH = Path(__file__).resolve().parent.parent / "openapi" / "dsg-one-v1.yaml"


@pytest.fixture(scope="module")
def contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def app_operations() -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    for route in cinema_main.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/v1"):
            continue
        for method in getattr(route, "methods", set()):
            if method in {"HEAD", "OPTIONS"}:
                continue
            operations.add((path, method.lower()))
    return operations


def contract_operations(contract: dict) -> set[tuple[str, str]]:
    return {
        (path, method)
        for path, item in contract["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }


def test_contract_is_openapi_31(contract):
    assert contract["openapi"].startswith("3.1")


def test_contract_and_app_expose_the_same_operations(contract):
    assert contract_operations(contract) == app_operations()


def test_contract_covers_the_flow_the_ui_drives(contract):
    required = {
        "/api/v1/plans/{plan_id}/approve",
        "/api/v1/verify/plan-alignment",
        "/api/v1/verify/constraints",
        "/api/v1/executions",
        "/api/v1/executions/{execution_id}/evidence",
        "/api/v1/executions/{execution_id}/verify",
        "/api/v1/proofs/{proof_id}",
        "/api/v1/mcp",
    }
    assert required <= set(contract["paths"])


def _walk_refs(node, found: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                found.append(value)
            else:
                _walk_refs(value, found)
    elif isinstance(node, list):
        for item in node:
            _walk_refs(item, found)


def test_every_reference_resolves(contract):
    references: list[str] = []
    _walk_refs(contract, references)
    for reference in set(references):
        assert reference.startswith("#/"), reference
        node = contract
        for segment in reference.removeprefix("#/").split("/"):
            assert segment in node, f"{reference} does not resolve at {segment}"
            node = node[segment]


def _request_schemas(contract: dict) -> list[tuple[str, dict]]:
    schemas: list[tuple[str, dict]] = []
    for path, item in contract["paths"].items():
        for method, operation in item.items():
            if method not in {"post", "put", "patch"}:
                continue
            body = operation.get("requestBody")
            if not body:
                continue
            for media in body["content"].values():
                schemas.append((f"{method.upper()} {path}", media["schema"]))
    return schemas


def _resolve(contract: dict, schema: dict) -> dict:
    reference = schema.get("$ref")
    if not reference:
        return schema
    node = contract
    for segment in reference.removeprefix("#/").split("/"):
        node = node[segment]
    return node


def _properties(contract: dict, schema: dict, seen: set[str]) -> set[str]:
    schema = _resolve(contract, schema)
    key = id(schema)
    names: set[str] = set()
    if str(key) in seen:
        return names
    seen.add(str(key))
    for name, child in (schema.get("properties") or {}).items():
        names.add(name)
        if name not in {"parameters", "facts", "observed_facts", "metadata"}:
            names |= _properties(contract, child, seen)
    for keyword in ("items", "additionalProperties"):
        child = schema.get(keyword)
        if isinstance(child, dict):
            names |= _properties(contract, child, seen)
    for keyword in ("anyOf", "oneOf", "allOf"):
        for child in schema.get(keyword) or []:
            if isinstance(child, dict):
                names |= _properties(contract, child, seen)
    return names


def test_no_request_body_accepts_a_verdict(contract):
    """The contract must not offer a field DSG refuses at runtime."""
    for label, schema in _request_schemas(contract):
        if label.endswith("/api/v1/mcp"):
            continue  # JSON-RPC envelope; tool arguments carry the same rule
        offered = _properties(contract, schema, set())
        assert not (offered & set(ASSERTED_VERDICT_FIELDS)), (
            f"{label} offers verdict fields {sorted(offered & set(ASSERTED_VERDICT_FIELDS))}"
        )


def test_contract_states_the_independent_verification_rule(contract):
    description = contract["info"]["description"]
    assert "AGENT_ASSERTED_VERDICT_REJECTED" in description
    assert "never a verdict" in description
    assert "Fail-closed" in description
