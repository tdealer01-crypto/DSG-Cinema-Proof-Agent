# Agents for Humans — Strands adapter

Status: **build prepared; not submitted to Devpost**.

This isolated adapter makes the current DSG Verified Execution service usable as a Strands Agents custom tool for the **Professional Agents** track. It does not replace Cinema, Z3, entitlement, or billing. The agent sends evidence-backed bounded facts to the existing `/verify/evaluate` contract and accepts a result only when DSG returns a valid `VERIFIED_GLOBAL_OPTIMUM` proof receipt.

## User value

A professional automation agent can perform its normal work and then ask DSG to verify whether the bounded action stayed inside the approved plan and deterministic constraints. The user sees one of three DSG decisions — `ALLOW`, `REVIEW`, or `BLOCK` — plus the proof hash. If verification is unavailable or malformed, the adapter fails closed instead of inventing success.

## Run

Python 3.10+ is required by the current Strands SDK.

```bash
cd hackathons/agents-for-humans
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DSG_VERIFY_URL="https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io"
# Optional for attributed/metered proofs:
# export DSG_API_KEY="dsg_live_..."
python agent.py
```

The Strands model provider still needs its own supported credentials/configuration. No model credential is committed to this repository.

## Test

```bash
cd hackathons/agents-for-humans
python -m pytest -q test_dsg_client.py
python -m py_compile dsg_client.py agent.py
```

The unit tests do not call AWS, an LLM, or production DSG. They verify the fail-closed proof-receipt boundary deterministically.

## Devpost readiness boundary

The Agents for Humans submission rules currently require a new AI agent built with Strands Agents SDK, a public code repository, README/setup instructions, MIT or Apache license, architecture diagram, a demo video of at most five minutes, AWS Builder ID, and required submission answers. A live demo link is optional but can improve Technical Implementation scoring.

Still external / owner-specific before submission:

- register for the hackathon and explicitly accept its rules, terms, and eligibility statement;
- provide the required registration questionnaire answers;
- provide the AWS Builder ID;
- attach the required architecture diagram;
- provide the required demo video URL;
- confirm the final Devpost submission answers and track.

Do not describe this adapter as submitted, accepted, or prize-eligible until Devpost confirms those states.
