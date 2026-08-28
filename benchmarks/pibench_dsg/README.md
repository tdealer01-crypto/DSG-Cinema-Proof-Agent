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
8. every turn emits an internal SHA-256 proof receipt chained to the prior receipt.

The proof receipt includes hashes of the benchmark context, tool inventory, assistant content, proposed tool calls, emitted tool calls, gate status, reason codes, and previous receipt hash. Receipt format `dsg-pibench-proof/v2` records deterministic representation normalization without claiming that the gate repairs semantic ordering.

### Evidence boundary

The DSG gate proves the **execution contract** it enforces. It does **not** by itself prove that the model interpreted a policy correctly. PI-Bench is the independent evaluator of policy semantics, required state transitions, forbidden actions, privacy boundaries, and final decision correctness.

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

Optional:

- `OPENAI_MODEL` — default `gpt-5`
- `REASONING_EFFORT` — default `medium`

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

The health and bootstrap checks do not require an LLM key. A real PI-Bench turn does.

CI evidence includes unit-test output, resolved Python dependency versions, Docker image inspection, agent card, bootstrap request/response, container log, and SHA-256 checksums. `SHA256SUMS.txt` intentionally excludes itself.

## Public submission path

1. CI tests the gate, compiles the server, validates the manifest shape, builds `linux/amd64`, and smoke-tests the A2A card/bootstrap contract.
2. Merge only after those checks pass.
3. Main-branch CI publishes the GHCR image and immutable digest evidence.
4. Make the GHCR package public.
5. Register the image as a purple agent on AgentBeats and copy its `agentbeats_id`.
6. Submit the registered agent to the PI-Bench green agent using AgentBeats Quick Submit or the official manual leaderboard flow.
7. The public result is valid only after the AgentBeats/PI-Bench assessment completes and the score appears in the public leaderboard/evidence record.

## Claim policy

Before step 7, use:

> DSG has an AgentBeats-compatible PI-Bench submission package with reproducible CI and deterministic proof-gated tool execution.

After step 7 succeeds, the public score may be reported with the exact assessment date, model, image digest, AgentBeats result link, and PI-Bench metrics. Do not claim public benchmark completion before that evidence exists.

---

© 2026 DSG.PICS · `DSG.PICS-IP-2026-V1` · Intellectual Property Attribution. Third-party/open-source benchmark and dependency licenses remain under their respective terms.
