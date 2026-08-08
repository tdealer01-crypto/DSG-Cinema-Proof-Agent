# DSG Cinema Proof Agent

Evidence-first incident response for cinema, streaming, rendering, and media-production systems.

**Runtime path:** Gemini / Google ADK → Grafana MCP telemetry → deterministic Z3 recovery gate → SHA-256 proof → tamper-evident audit chain.

**Hybrid optimization path:** deterministic QUBO / Ising-equivalent annealing → real server-side Z3 → SHA-256 proof → tamper-evident audit chain.

> **Truth boundary:** implementation is not the same as a verified live deployment. Annealing output is a candidate only; a verified policy claim requires server-side Z3 SAT. External Gemini, Grafana, Cloud Run, and audit-backend success is only claimed after real runtime evidence exists.

## Implemented

- Google ADK agent with stable `gemini-3.6-flash` as the default model.
- Grafana MCP via ADK `McpToolset`, restricted to read-only telemetry tools.
- Official `grafana/mcp-grafana` Docker service with `--disable-write`.
- Cinema recovery policy: restart requires metrics evidence + log evidence + explicit human approval.
- Real deterministic QUBO / Ising-equivalent simulated annealing candidate search, ported from `Compliance-ising-z3-Deterministic-`.
- Real server-side `z3-solver`; Android local checks are explicitly labeled local.
- One-call hybrid endpoint: `POST /v1/hybrid/solve`.
- MCP hybrid tool: `solve_policy_hybrid`.
- SHA-256 proof, optional HMAC-SHA256, SQLite/Firestore/Supabase audit backends.
- DSG MCP Streamable HTTP at `/mcp`, protected when `DSG_API_KEY` is configured.
- Android companion: deterministic QUBO candidate → `/v1/verify` → HTTP/Z3/proof/audit evidence.
- Web demo at `/` that does not fabricate output.

## Fail closed

- `/v1/cinema/investigate` rejects execution if `GRAFANA_MCP_URL` is absent.
- Gemini/Grafana failures stay failures; no canned success response is substituted.
- Hybrid annealing success is never promoted to a proof unless server-side Z3 verifies the exact candidate.
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

Endpoints: `GET /health`, `GET /v1/capabilities`, `POST /v1/hybrid/solve`, `POST /v1/cinema/investigate`, `POST /v1/verify`, `GET /v1/audit/{event_hash}`, `/mcp`.

The Supabase migration is under `supabase/migrations/`. See `docs/HYBRID_SOLVER.md`, `docs/VERIFICATION.md`, and `docs/CONTEST_STATUS.md` for evidence boundaries.

MIT licensed.
