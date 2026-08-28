"""Microsoft Foundry runner for Stripe readiness, repair, and research.

Configuration mode combines a read-only OpenAPI tool with one strict,
argument-free function tool.  The function executes in this local process, so
Stripe values never enter a prompt, conversation, tool argument, or Foundry
trace.  Research mode is deliberately separate and receives only Web Search.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .secure_config import execute_secure_configuration

OPENAPI_SPEC_PATH = Path(__file__).with_name("stripe_readiness.openapi.json")
FUNCTION_NAME = "apply_approved_stripe_production_values"
AGENT_NAME = "dsg-stripe-marketplace-fix"

CONFIGURATION_INSTRUCTIONS = """
You are the DSG Stripe Marketplace readiness agent. Use the read-only OpenAPI
tool to inspect /health, /openapi.json, and /marketplace/stripe/status. Report
only observed facts. Never ask for, repeat, infer, transform, or place a Stripe
key, signing secret, authorize URL, DSG API key, or plan credential in chat.

When the live status is ACTION_REQUIRED, identify the non-PASS check names. If
the operator asks to apply an already-approved repair, call
apply_approved_stripe_production_values with exactly an empty JSON object. The
local host owns all sensitive input and the plan gate. Treat
WAITING_DEPLOYMENT, WAITING_OPERATOR_INPUT, WAITING_PERMISSION, BLOCK, and ERROR
as terminal refusals; never claim a write or deployment occurred. A successful
configuration write still requires a production deployment and a fresh live
probe. Do not perform marketplace upload, External Test, review, or publication.
""".strip()


def load_read_only_openapi_spec() -> dict[str, Any]:
    with OPENAPI_SPEC_PATH.open(encoding="utf-8") as handle:
        spec = json.load(handle)
    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise ValueError("Stripe readiness OpenAPI spec has no paths")
    for path, operations in paths.items():
        if not isinstance(operations, dict) or set(operations) != {"get"}:
            raise ValueError(f"OpenAPI tool is not read-only: {path}")
    return spec


def function_tool_schema() -> dict[str, Any]:
    """Return the strict zero-argument schema visible to the Foundry model."""
    return {
        "name": FUNCTION_NAME,
        "description": (
            "Ask the trusted local host to apply only missing fixed-name Stripe "
            "values through an approved DSG plan. No value is accepted as an argument."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "strict": True,
    }


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _required(environ: Mapping[str, str], name: str) -> str:
    value = (environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _agent_reference(agent: Any) -> dict[str, dict[str, str]]:
    return {"agent_reference": {"name": agent.name, "type": "agent_reference"}}


def run_configuration_agent(
    prompt: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Create an ephemeral prompt-agent version and run the local tool loop."""
    current_env = os.environ if environ is None else environ
    endpoint = _required(current_env, "FOUNDRY_PROJECT_ENDPOINT")
    model = _required(current_env, "FOUNDRY_MODEL_DEPLOYMENT_NAME")

    # Imports stay local so repository tests and the secure host do not require
    # Foundry packages unless an operator actually runs this entry point.
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import (
        AutoCodeInterpreterToolParam,
        CodeInterpreterTool,
        FunctionTool,
        OpenApiAnonymousAuthDetails,
        OpenApiFunctionDefinition,
        OpenApiTool,
        PromptAgentDefinition,
    )
    from azure.identity import DefaultAzureCredential
    from openai.types.responses.response_input_param import FunctionCallOutput

    project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    openai = project.get_openai_client()
    function_schema = function_tool_schema()
    tools: list[Any] = [
        OpenApiTool(
            openapi=OpenApiFunctionDefinition(
                name="dsg-stripe-readiness",
                description="Read-only DSG production health and Stripe readiness probes.",
                spec=load_read_only_openapi_spec(),
                auth=OpenApiAnonymousAuthDetails(),
            )
        ),
        FunctionTool(**function_schema),
    ]
    if _enabled(current_env.get("FOUNDRY_ENABLE_CODE_INTERPRETER")):
        tools.append(
            CodeInterpreterTool(container=AutoCodeInterpreterToolParam(file_ids=[]))
        )

    agent_name = (current_env.get("FOUNDRY_STRIPE_AGENT_NAME") or AGENT_NAME).strip()
    agent = project.agents.create_version(
        agent_name=agent_name,
        definition=PromptAgentDefinition(
            model=model,
            instructions=CONFIGURATION_INSTRUCTIONS,
            tools=tools,
        ),
        description="Readiness-only Stripe diagnosis with a local plan-gated repair host.",
    )
    conversation = openai.conversations.create()
    keep_resources = _enabled(current_env.get("FOUNDRY_KEEP_AGENT_RESOURCES"))
    try:
        response = openai.responses.create(
            input=prompt,
            conversation=conversation.id,
            extra_body=_agent_reference(agent),
        )
        for _ in range(6):
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                return response.output_text
            outputs = []
            for call in calls:
                if call.name != FUNCTION_NAME:
                    result = {
                        "decision": "BLOCK",
                        "executed": False,
                        "error": "UNRECOGNIZED_LOCAL_FUNCTION",
                        "secret_values_exposed": False,
                    }
                else:
                    try:
                        arguments = json.loads(call.arguments or "{}")
                    except json.JSONDecodeError:
                        arguments = None
                    if arguments != {}:
                        result = {
                            "decision": "BLOCK",
                            "executed": False,
                            "error": "FUNCTION_ARGUMENTS_FORBIDDEN",
                            "secret_values_exposed": False,
                        }
                    else:
                        result = execute_secure_configuration(environ=current_env)
                outputs.append(
                    FunctionCallOutput(
                        type="function_call_output",
                        call_id=call.call_id,
                        output=json.dumps(result, separators=(",", ":"), sort_keys=True),
                    )
                )
            response = openai.responses.create(
                input=outputs,
                conversation=conversation.id,
                extra_body=_agent_reference(agent),
            )
        raise RuntimeError("Foundry function loop exceeded six responses")
    finally:
        if not keep_resources:
            openai.conversations.delete(conversation_id=conversation.id)
            project.agents.delete_version(
                agent_name=agent.name,
                agent_version=agent.version,
            )


def research_request(prompt: str, *, model: str) -> dict[str, Any]:
    """Build the research-only Responses request; it has no mutation function."""
    return {
        "model": model,
        "tools": [{"type": "web_search"}],
        "reasoning": {"effort": "high"},
        "input": prompt,
    }


def run_research(
    prompt: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Run citation-oriented Web Search without any configuration capability."""
    current_env = os.environ if environ is None else environ
    endpoint = _required(current_env, "FOUNDRY_PROJECT_ENDPOINT")
    model = _required(current_env, "FOUNDRY_RESEARCH_MODEL_DEPLOYMENT_NAME")

    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    response = project.get_openai_client().responses.create(
        **research_request(prompt, model=model)
    )
    if not response.output_text:
        raise RuntimeError("Foundry research returned no text")
    if not any(item.type == "web_search_call" for item in response.output):
        raise RuntimeError("Foundry research returned without a Web Search call")
    return response.output_text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("configure", "research"),
        default="configure",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default=(
            "Inspect production Stripe Marketplace readiness. Apply the approved "
            "local repair only if the live incremental contract and plan gate allow it."
        ),
    )
    args = parser.parse_args()
    if args.mode == "research":
        print(run_research(args.prompt))
    else:
        print(run_configuration_agent(args.prompt))


if __name__ == "__main__":
    main()
