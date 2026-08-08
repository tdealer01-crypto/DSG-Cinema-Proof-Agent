# DSG Cinema Proof Agent

Evidence-first incident response, deterministic optimization, and reproducible proof verification for cinema, streaming, rendering, media-production, policy, and mathematical research workflows.

**Runtime path:** Gemini / Google ADK → Grafana MCP telemetry → deterministic Z3 recovery gate → SHA-256 proof → tamper-evident audit chain.

**Hybrid optimization path:** deterministic QUBO / Ising-equivalent annealing → real server-side Z3 → SHA-256 proof → tamper-evident audit chain.

**Math verification path:** deterministic Ising/QUBO candidate search → exact finite verifier → real Z3 → SHA-256 proof → audit chain.

**Formal reproducibility path:** pinned external Lean source → pinned Lean/Mathlib toolchain → clean `lake build` → Lean kernel recheck → theorem axiom audit → deterministic replay receipt.

> **Truth boundary:** implementation is not the same as a verified live deployment. Annealing output is a candidate only. The Ramsey benchmark proves only `R(3,3)=6`. First Proof #2 is represented by (1) a provenance-linked human reference closure and (2) a DSG reconstruction audit that machine-checks its quantifier/scalar spine while keeping Kirillov, Godement–Jacquet, Mellin/Fourier, newvector, and epsilon-factor inputs as explicit reference dependencies. DSG does **not** claim independent discovery or an independent formalization of those deep p-adic representation-theoretic lemmas. First Proof #6 has two distinct evidence paths: (1) a provenance-linked reference-theorem closure endpoint and exact finite-instance/sweep evidence, and (2) an independent deterministic replay of the published Archon/FrenzyMath Lean formalization of `Problem6.exists_eps_light_subset` with certified bound `c=1/256`. DSG verifies reproducibility of that published formal proof; it does **not** claim independent discovery or authorship of the proof. External Gemini, Grafana, Cloud Run, and audit-backend success is only claimed after real runtime evidence exists.

## Implemented

- Google ADK agent with stable `gemini-3.6-flash` as the default model.
- Grafana MCP via ADK `McpToolset`, restricted to read-only telemetry tools.
- Official `grafana/mcp-grafana` Docker service with `--disable-write`.
- Cinema recovery policy: restart requires metrics evidence + log evidence + explicit human approval.
- Real deterministic QUBO / Ising-equivalent simulated annealing candidate search, ported from `Compliance-ising-z3-Deterministic-`.
- Real server-side `z3-solver`; Android local checks are explicitly labeled local.
- One-call hybrid endpoint: `POST /v1/hybrid/solve`.
- Exact Ramsey `R(3,3)=6` benchmark: `POST /v1/math/ramsey-r33/prove`.
- First Proof #2 provenance-linked theorem closure: `POST /v1/math/first-proof-2/closure`.
- First Proof #2 machine-audited reference reconstruction: `POST /v1/math/first-proof-2/reconstruction`.
- First Proof #6 provenance-linked theorem closure: `POST /v1/math/first-proof-6/closure`.
- First Proof #6 finite ε-light benchmark: `POST /v1/math/first-proof-6/benchmark`.
- Generic finite ε-light instance endpoint: `POST /v1/math/first-proof-6/verify-instance`.
- Exact finite First Proof #6 family/epsilon/constant sweep: `POST /v1/math/first-proof-6/sweep`.
- MCP tools for First Proof #2 closure/reconstruction, First Proof #6 closure/finite evidence, Ramsey, and policy hybrid solving.
- Deterministic Lean replay workflow for First Proof #6 with pinned source commit and Lean 4.28.0.
- Lean theorem axiom audit using `#print axioms Problem6.exists_eps_light_subset`; the replay gate fails if `sorryAx` appears.
- SHA-256 proof, optional HMAC-SHA256, SQLite/Firestore/Supabase audit backends.
- DSG MCP Streamable HTTP at `/mcp`, protected when `DSG_API_KEY` is configured.
- Android companion: deterministic QUBO candidate → `/v1/verify` → HTTP/Z3/proof/audit evidence.
- Web demo at `/` that does not fabricate output.

## First Proof #2 — reference reconstruction audit

The repository now exposes two evidence surfaces for **First Proof Problem #2 — the local Rankin–Selberg test-vector problem**:

```text
POST /v1/math/first-proof-2/closure
POST /v1/math/first-proof-2/reconstruction
```

The closure certificate records the published human solution and enforces the critical quantifier:

```text
W0 = W0(Pi, psi)
```

The universal Whittaker vector `W0` must be fixed before the smaller representation `pi` is chosen. It must not depend on `pi`, its conductor `q`, or the conductor generator `Q`. For each `pi`, the conductor data and normalized smaller-group newvector `V` may vary.

The reconstruction audit records the published proof dependency chain and deterministically checks three scalar/logical obligations with Z3 by proving their negations UNSAT:

- `proposition6_exponent_cancellation` — equations (19) and (20) combine to the `s`-independent exponent `-n/2` in equation (17).
- `basepoint_normalization` — at `s=(n+1)/2`, the exponent in equation (20) is zero.
- `nonzero_scalar_factor` — nonzero local epsilon factor together with positive `|Q|^n` and positive `vol(K1(q))` forces the final scalar factor to be nonzero.

The following deep mathematical inputs remain explicitly marked `REFERENCE_THEOREM_REQUIRED`:

- Kirillov-model extension.
- Godement–Jacquet local functional equation.
- Mellin support transform.
- Fourier-to-`K1(q)` identity.
- Normalized newvector theory.
- Nonvanishing of the local epsilon factor.

The audited final identity from the published reconstruction is

```text
ell_RS(s, u_Q W0, d_Q V) = c * |Q|^(-n/2),   c != 0.
```

Both certificate paths emit SHA-256 proof hashes and tamper-evident audit-event hashes.

**Claim boundary:** DSG reconstructs and machine-audits the quantifier/scalar spine of the published solution. It does **not** claim that Z3 proves p-adic representation theory, does not claim a full independent proof-assistant formalization, and does not claim independent discovery of Problem #2.

See `docs/FIRST_PROOF_2_RANKIN_SELBERG.md` and `docs/FIRST_PROOF_2_RECONSTRUCTION_AUDIT.md`.

## First Proof #6 — reproducible formal verification

The repository contains a CI gate that reproduces a published Lean 4 formalization of **First Proof Problem #6 — Large ε-Light Vertex Subsets** from a clean GitHub Actions runner.

Pinned inputs:

- Formalization: `frenzymath/Archon-FirstProof-Results`
- Source commit: `a5694249bd8b94bd1dbab7cc7d477f0fdd322471`
- Lean: `leanprover/lean4:v4.28.0`
- Mathlib: `v4.28.0` as resolved by the pinned project
- Theorem file: `FirstProof/FirstProof6/Problem6.lean`
- Main theorem: `Problem6.exists_eps_light_subset`
- Machine-checked bound in this formalization: `c = 1/256`

The formal theorem states that for every finite simple graph `G` and every `ε ∈ (0,1]`, there exists an ε-light vertex set `S` satisfying

```text
|S| ≥ (ε / 256) |V|.
```

Latest verified replay evidence from the PR gate:

- clean `lake build`: **PASS** — 2,905 jobs
- `lake env lean FirstProof/FirstProof6/Problem6.lean`: **PASS**
- `#print axioms Problem6.exists_eps_light_subset`: **PASS**
- transitive `sorryAx`: **not present**
- reported Lean axioms: `propext`, `Classical.choice`, `Quot.sound`
- replay receipt: `REPRODUCIBLE_FORMAL_PROOF=PASS`

Pinned replay hashes:

```text
Problem6.lean   50b1fd60f7ef6b09160c615883e0a2073f67c33d9e4529f3432ce5f02bd5605b
lean-toolchain db7bb24b756d745bbde83fe92718b51bd3625dae3701ba0f598d0eedcd3f3028
lakefile.toml  6ac555869c58b32dd4f266e727ac2882d354bc3829f74fe4e62a07d3a5789343
```

See `.github/workflows/first-proof-6-lean-replay.yml` and `docs/FIRST_PROOF_6_DETERMINISTIC_REPLAY.md` for the reproducibility gate.

**Provenance:** the underlying Lean formalization is credited to **FrenzyMath / Archon** and is published under Apache-2.0. DSG independently reruns and verifies the published formal proof under pinned inputs; DSG does not claim to have independently discovered or authored that proof.

## Fail closed

- `/v1/cinema/investigate` rejects execution if `GRAFANA_MCP_URL` is absent.
- Gemini/Grafana failures stay failures; no canned success response is substituted.
- Hybrid annealing success is never promoted to a proof unless server-side Z3 verifies the exact candidate.
- Ramsey benchmark reports `PROVED` only when the K5 zero-energy witness is Z3-SAT and the K6 no-monochromatic-triangle existence formula is Z3-UNSAT.
- First Proof #2 rejects any reconstruction in which the universal `W0` depends on `pi`, `q`, or `Q`.
- First Proof #2 keeps Kirillov/Godement–Jacquet/Mellin/Fourier/newvector/epsilon-factor inputs as explicit reference dependencies rather than relabeling them as Z3 proofs.
- First Proof #2 reconstruction status is `REFERENCE_RECONSTRUCTION_AUDITED`, not `INDEPENDENT_FORMAL_PROOF`.
- First Proof #6 finite verification reports `FINITE_INSTANCE_VERIFIED` only when the candidate meets the size target and every principal minor of `εL - L_S` is nonnegative under exact rational arithmetic, with the certificate checked by Z3.
- First Proof #6 theorem closure is explicitly provenance-linked; it is not labeled as independent DSG discovery.
- Formal replay reports `REPRODUCIBLE_FORMAL_PROOF=PASS` only after pinned checkout, pinned toolchain validation, clean build, kernel recheck, and a transitive `sorryAx` audit all pass.
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

First Proof #2 reference closure
  -> POST /v1/math/first-proof-2/closure
  -> published human solution + provenance
  -> universal W0 dependency guard
  -> documented rejection of prior LLM failure modes
  -> proof_hash + audit.event_hash

First Proof #2 reconstruction audit
  -> POST /v1/math/first-proof-2/reconstruction
  -> reference proof DAG
  -> explicit REFERENCE_THEOREM_REQUIRED dependencies
  -> Z3 scalar/logical obligations
  -> exponent/basepoint/nonzero checks
  -> REFERENCE_RECONSTRUCTION_AUDITED
  -> proof_hash + audit.event_hash

First Proof #6 finite verifier
  -> POST /v1/math/first-proof-6/benchmark or /verify-instance or /sweep
  -> QUBO/Ising candidate search where applicable
  -> exact rational M = epsilon*L - L_S
  -> exact principal-minor PSD checks
  -> Z3 certificate checks
  -> FINITE_INSTANCE_VERIFIED / CANDIDATE_REJECTED / FINITE_COUNTEREXAMPLE / UNKNOWN
  -> proof_hash + audit.event_hash

First Proof #6 theorem closure
  -> POST /v1/math/first-proof-6/closure
  -> provenance-linked reference theorem
  -> DSG scalar Z3 obligations + proof/audit hashes
  -> explicit no-independent-discovery truth boundary

First Proof #6 deterministic Lean replay
  -> checkout pinned Archon/FrenzyMath commit
  -> verify Lean 4.28.0 + source hashes
  -> lake exe cache get
  -> lake build
  -> Lean kernel rechecks Problem6.lean
  -> #print axioms Problem6.exists_eps_light_subset
  -> reject any sorryAx dependency
  -> REPRODUCIBLE_FORMAL_PROOF=PASS

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

Endpoints: `GET /health`, `GET /v1/capabilities`, `POST /v1/math/first-proof-2/closure`, `POST /v1/math/first-proof-2/reconstruction`, `POST /v1/math/first-proof-6/closure`, `POST /v1/math/first-proof-6/benchmark`, `POST /v1/math/first-proof-6/verify-instance`, `POST /v1/math/first-proof-6/sweep`, `POST /v1/math/ramsey-r33/prove`, `POST /v1/hybrid/solve`, `POST /v1/cinema/investigate`, `POST /v1/verify`, `GET /v1/audit/{event_hash}`, `/mcp`.

The Supabase migration is under `supabase/migrations/`. See `docs/FIRST_PROOF_2_RANKIN_SELBERG.md`, `docs/FIRST_PROOF_2_RECONSTRUCTION_AUDIT.md`, `docs/FIRST_PROOF_6_DETERMINISTIC_REPLAY.md`, `docs/FIRST_PROOF_6_EPSILON_LIGHT.md`, `docs/RAMSEY_R33_BENCHMARK.md`, `docs/HYBRID_SOLVER.md`, `docs/VERIFICATION.md`, and `docs/CONTEST_STATUS.md` for evidence boundaries.

MIT licensed.
