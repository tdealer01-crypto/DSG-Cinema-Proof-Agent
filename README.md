# DSG Cinema Proof Agent

Evidence-first incident response for cinema, streaming, rendering, and media-production systems.

**Runtime path:** Gemini / Google ADK → Grafana MCP telemetry → deterministic Z3 recovery gate → SHA-256 proof → tamper-evident audit chain.

**Hybrid optimization path:** deterministic QUBO / Ising-equivalent annealing → real server-side Z3 → SHA-256 proof → tamper-evident audit chain.

**Math benchmark path:** deterministic Ising/QUBO candidate search → exact finite verifier → real Z3 → SHA-256 proof → audit chain.

> **Truth boundary:** implementation is not the same as a verified live deployment. Annealing output is a candidate only. The Ramsey benchmark proves only `R(3,3)=6`. The First Proof #6 path currently verifies finite ε-light graph instances only; it does not claim the universal theorem or the proposed constant `c=1/256`. External Gemini, Grafana, Cloud Run, and audit-backend success is only claimed after real runtime evidence exists.

## Implemented

- Google ADK agent with stable `gemini-3.6-flash` as the default model.
- Grafana MCP via ADK `McpToolset`, restricted to read-only telemetry tools.
- Official `grafana/mcp-grafana` Docker service with `--disable-write`.
- Cinema recovery policy: restart requires metrics evidence + log evidence + explicit human approval.
- Real deterministic QUBO / Ising-equivalent simulated annealing candidate search, ported from `Compliance-ising-z3-Deterministic-`.
- Real server-side `z3-solver`; Android local checks are explicitly labeled local.
- One-call hybrid endpoint: `POST /v1/hybrid/solve`.
- Exact Ramsey `R(3,3)=6` benchmark: `POST /v1/math/ramsey-r33/prove`.
- First Proof #6 finite ε-light benchmark: `POST /v1/math/first-proof-6/benchmark`.
- Generic finite ε-light instance endpoint: `POST /v1/math/first-proof-6/verify-instance`.
- MCP tools for Ramsey, First Proof #6 finite instances, and policy hybrid solving.
- SHA-256 proof, optional HMAC-SHA256, SQLite/Firestore/Supabase audit backends.
- DSG MCP Streamable HTTP at `/mcp`, protected when `DSG_API_KEY` is configured.
- Android companion: deterministic QUBO candidate → `/v1/verify` → HTTP/Z3/proof/audit evidence.
- Web demo at `/` that does not fabricate output.

## Fail closed

- `/v1/cinema/investigate` rejects execution if `GRAFANA_MCP_URL` is absent.
- Gemini/Grafana failures stay failures; no canned success response is substituted.
- Hybrid annealing success is never promoted to a proof unless server-side Z3 verifies the exact candidate.
- Ramsey benchmark reports `PROVED` only when the K5 zero-energy witness is Z3-SAT and the K6 no-monochromatic-triangle existence formula is Z3-UNSAT.
- First Proof #6 reports `FINITE_INSTANCE_VERIFIED` only when the candidate meets the size target and every principal minor of `εL - L_S` is nonnegative under exact rational arithmetic, with the certificate checked by Z3.
- A restart plan is Z3-UNSAT without the required evidence and human approval.
- Supabase service-role credentials are server-only and are not committed.

## Architecture

```text
Studio operator
  -> FastAPI /v1/cinema/investigate
  -> Google ADK + Gemini
  -> Grafana MCP (metrics/logs/dashboards/incidents; read-only)
  -> verify_recovery_plan
  -> Z3 SAT / UNSAT
  -> proof_hash + audit.event_hash

Policy / research client
  -> POST /v1/hybrid/solve
  -> deterministic QUBO matrix
  -> QUBO -> Ising J/h/offset
  -> seeded simulated annealing candidate
  -> real server-side Z3 verification
  -> proof_hash + audit.event_hash

Ramsey benchmark client
  -> POST /v1/math/ramsey-r33/prove
  -> exact quadratic Ising model for monochromatic triangles
  -> deterministic K5 witness search
  -> Z3 verifies K5 witness SAT
  -> Z3 proves K6 existence formula UNSAT
  -> proof_hash + audit.event_hash

First Proof #6 finite benchmark client
  -> POST /v1/math/first-proof-6/benchmark
  -> K8, epsilon=1/2, target |S|>=4
  -> QUBO/Ising candidate search
  -> build exact rational M = epsilon*L - L_S
  -> check all 255 principal minors
  -> Z3 checks fixed membership + rational minor certificate
  -> FINITE_INSTANCE_VERIFIED / CANDIDATE_REJECTED / UNKNOWN
  -> proof_hash + audit.event_hash

Android
  -> deterministic local QUBO candidate
  -> POST /v1/verify
  -> same server-side Z3/proof/audit service
```

## Local run

```bash
cp .env.example .env
# Put real Google/Grafana credentials in .env; never commit it.
docker compose up --build
```

Backend direct:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
uvicorn app.main:app --reload
```

Endpoints: `GET /health`, `GET /v1/capabilities`, `POST /v1/math/first-proof-6/benchmark`, `POST /v1/math/first-proof-6/verify-instance`, `POST /v1/math/ramsey-r33/prove`, `POST /v1/hybrid/solve`, `POST /v1/cinema/investigate`, `POST /v1/verify`, `GET /v1/audit/{event_hash}`, `/mcp`.

The Supabase migration is under `supabase/migrations/`. See `docs/FIRST_PROOF_6_EPSILON_LIGHT.md`, `docs/RAMSEY_R33_BENCHMARK.md`, `docs/HYBRID_SOLVER.md`, `docs/VERIFICATION.md`, and `docs/CONTEST_STATUS.md` for evidence boundaries.

MIT licensed.
