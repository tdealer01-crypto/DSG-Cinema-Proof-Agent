# DSG Proof-Governed Agent — PI-Bench / AgentBeats

This directory packages a dedicated **purple agent** for public evaluation on PI-Bench through AgentBeats.

The goal is to compare DSG's governance layer against other tool-using agents on the same 71-scenario policy-compliance benchmark. PI-Bench independently scores policy understanding, policy execution, policy boundaries, full compliance, semantic quality, and event-level failure signals.

## What DSG adds

The benchmark adapter uses the model selected by the assessment operator, then applies a deterministic execution-contract gate before any model-proposed tool call is returned to the benchmark:

1. tool name must exist in the benchmark-provided inventory;
2. tool arguments must be valid JSON objects;
3. arguments must satisfy the benchmark-provided JSON Schema;
4. duplicate tool-call IDs are blocked;
5. `record_decision` values are restricted to `ALLOW`, `ALLOW-CONDITIONAL`, `DENY`, or `ESCALATE`;
6. tool-call semantic order is preserved; an operational call after `record_decision`, or multiple final decisions, fails closed rather than being reordered/repaired;
7. malformed, unknown, or invalidly ordered actions fail closed and emit **zero** tool calls;
8. every locally gated turn emits an internal SHA-256 proof receipt chained to the prior receipt.

An inventory entry whose parameter block is not a valid JSON Schema is validated
against an empty object schema instead of poisoning the turn, so one defective
benchmark tool definition cannot silence the agent for a whole scenario.

The proof receipt includes hashes of the benchmark context, tool inventory, assistant content, proposed tool calls, emitted tool calls, gate status, reason codes, and previous receipt hash. Receipt format `dsg-pibench-proof/v2` records deterministic representation normalization without claiming that the gate repairs semantic ordering.

### Optional production Cinema preflight

`CINEMA_PREFLIGHT_MODE=off` is the default and preserves the existing PI-Bench baseline.

`CINEMA_PREFLIGHT_MODE=required` adds a production Cinema authorization step **before** the local deterministic gate:

`PI-Bench context → independently approved Cinema plan binding → Cinema MCP preflight → local deterministic gate → PI-Bench tools`

The adapter never calls `dsg_create_plan` or `dsg_approve_plan`. A plan must already be approved by an authority outside the model proposal path. Missing plan binding, agent-identity mismatch, MCP transport/schema failure, `WAITING_PERMISSION`, or `BLOCK` fails closed and emits **zero** PI-Bench tool calls.

The adapter maps one proposed benchmark tool to Cinema's real `ObservedAction` contract as follows:

- `action` = benchmark function/tool name;
- `target` = `pibench:<context_hash>:<toolset_hash>`;
- `step_id` = deterministic `pib-` + the first 60 hex characters of the SHA-256 canonical hash of `{context_hash, tool_name, toolset_hash}`;
- `parameters` = `{}`;
- `status` = `skipped`, because preflight happens before execution.

The Cinema `trace_id` is derived from the exact proposed call ID/function payload, so the authorization record can be correlated with that proposal without pretending the proposal has already executed.

This split is deliberate: the approved Cinema plan governs the benchmark context/tool surface, while the local deterministic gate validates the concrete PI-Bench argument JSON, JSON Schema, decision vocabulary, and semantic call ordering afterward. Cinema therefore does **not** claim that it independently proved the semantic correctness of the concrete PI-Bench arguments in this adapter; PI-Bench remains the independent evaluator of policy semantics and resulting state.

For a single pre-bound scenario, configure:

- `CINEMA_PIBENCH_PLAN_ID`
- `CINEMA_PIBENCH_AGENT_IDENTITY`
- `CINEMA_API_KEY` when the production endpoint requires it

For multiple known benchmark contexts, `CINEMA_PIBENCH_PLAN_BINDINGS_JSON` may contain a JSON object mapping exact `context_hash` values to approved `plan_id` values. A context-specific mapping takes precedence over the single-plan fallback. The approved plan must contain steps matching the deterministic action/target/step-id mapping above. It must be produced and approved independently of the model's proposal.

### Evidence boundary

The DSG gate proves the **execution contract** it enforces. It does **not** by itself prove that the model interpreted a policy correctly. PI-Bench is the independent evaluator of policy semantics, required state transitions, forbidden actions, privacy boundaries, and final decision correctness.

The Cinema preflight proves that the mapped context/tool action matched an already-approved production plan and that Cinema returned an execution-ready `ALLOW`. This benchmark adapter does not yet record PI-Bench's completed execution/evidence back into Cinema's final Z3 verification pipeline, so no final Cinema execution-proof claim should be made from preflight alone.

## Turn resilience

PI-Bench terminates an entire scenario as soon as one agent turn raises or
returns a protocol error, and a scenario that records no canonical decision is
scored zero regardless of the reasoning it contained. The adapter therefore
never surfaces a turn-level failure to the benchmark:

1. provider calls retry with exponential backoff and jitter, progressively
   dropping optional request parameters (`seed`, then `reasoning_effort`) that
   can turn a retryable error into a hard rejection;
2. a gate-blocked turn is re-proposed once with the gate's reason codes fed back
   to the model, because a blocked turn emits zero tool calls anyway;
3. an unknown or expired `context_id` rebuilds the session instead of returning
   a JSON-RPC error;
4. after repeated unrecoverable turns the agent records a fail-closed
   `ESCALATE` through `record_decision`, reusing identifiers already present in
   the transcript rather than inventing them, so the scenario still carries a
   canonical decision;
5. `###STOP###` is only emitted once a decision has been recorded.

## AgentBeats compatibility

The server implements the PI-Bench A2A network contract and advertises:

`urn:pi-bench:policy-bootstrap:v1`

Endpoints:

- `GET /.well-known/agent.json`
- `GET /.well-known/agent-card.json`
- `GET /health`
- `POST /` using A2A `message/send`

The benchmark image is built for `linux/amd64`, which is the AgentBeats GitHub-runner target. The Amber manifest uses the array-form `entrypoint` used by the current PI-Bench AgentBeats leaderboard reference manifest.

## Container

After the benchmark branch is merged, GitHub Actions publishes:

`ghcr.io/tdealer01-crypto/dsg-pibench-agent:latest`

and an immutable commit-SHA tag.

GitHub Container Registry creates new personal-account packages as private by default. Before public AgentBeats registration, the package must be changed to **Public** in GitHub Package settings so AgentBeats can pull it anonymously.

## Runtime configuration

Required:

- `OPENAI_API_KEY`

Optional baseline settings:

- `OPENAI_MODEL` — default `gpt-5`
- `REASONING_EFFORT` — default `medium`
- `MODEL_MAX_ATTEMPTS` — provider attempts per turn, default `5`
- `MODEL_RETRY_BASE_DELAY` — first backoff in seconds, default `2.0`
- `MODEL_RETRY_MAX_DELAY` — backoff ceiling in seconds, default `30.0`
- `CINEMA_PREFLIGHT_MODE` — `off` by default; set `required` only when approved plan binding is provisioned

Required when Cinema mode is `required`:

- `CINEMA_PIBENCH_AGENT_IDENTITY`
- either `CINEMA_PIBENCH_PLAN_ID` or a matching entry in `CINEMA_PIBENCH_PLAN_BINDINGS_JSON`
- `CINEMA_API_KEY` when required by the production Cinema endpoint

No secret is committed to this repository.

## Local verification

```bash
python -m pip install -r benchmarks/pibench_dsg/requirements.txt
pytest -q benchmarks/pibench_dsg/tests

docker build --platform linux/amd64 \
  -f benchmarks/pibench_dsg/Dockerfile \
  -t dsg-pibench-agent:test .

docker run --rm -p 9010:9010 dsg-pibench-agent:test \
  --host 0.0.0.0 --port 9010 --card-url http://127.0.0.1:9010/
```

The health and bootstrap checks do not require an LLM key. A real PI-Bench turn does. Required Cinema mode additionally requires an independently approved plan binding.

CI evidence includes unit-test output, resolved Python dependency versions, Docker image inspection, agent card, bootstrap request/response, container log, and SHA-256 checksums. `SHA256SUMS.txt` intentionally excludes itself.

## Public submission path

1. CI tests the gate, Cinema adapter contract, execution order, compiles the server, validates the manifest shape, builds `linux/amd64`, and smoke-tests the A2A card/bootstrap contract.
2. Merge only after those checks pass.
3. Main-branch CI publishes the GHCR image and immutable digest evidence.
4. Make the GHCR package public.
5. Register the image as a purple agent on AgentBeats and copy its `agentbeats_id`.
6. Submit the registered agent to the PI-Bench green agent using AgentBeats Quick Submit or the official manual leaderboard flow.
7. The public result is valid only after the AgentBeats/PI-Bench assessment completes and the score appears in the public leaderboard/evidence record.

For A/B evidence, keep the original assessment as the `Cinema off` baseline and run a separate assessment with `Cinema required` plus approved plan bindings. Do not relabel the earlier score as a Cinema-governed score.

## Claim policy

Before step 7, use:

> DSG has an AgentBeats-compatible PI-Bench submission package with reproducible CI and deterministic proof-gated tool execution.

After a new Cinema-required assessment succeeds, the public score may be reported only with the exact assessment date, model, image digest, Cinema mode, approved-plan binding evidence, AgentBeats result link, and PI-Bench metrics. Do not claim a new Cinema-governed benchmark result before that evidence exists.

---

© 2026 DSG.PICS · `DSG.PICS-IP-2026-V1` · Intellectual Property Attribution. Third-party/open-source benchmark and dependency licenses remain under their respective terms.
