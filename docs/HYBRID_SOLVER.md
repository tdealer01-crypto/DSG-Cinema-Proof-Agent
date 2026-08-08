# DSG Hybrid QUBO / Ising + Z3 Solver

This integration combines the real deterministic annealing implementation from `tdealer01-crypto/Compliance-ising-z3-Deterministic-` with the real server-side `z3-solver`, SHA-256 proof, and tamper-evident audit chain already present in this repository.

## Source provenance

The candidate-search behavior was ported from these verified source paths in `Compliance-ising-z3-Deterministic-`:

- `app/src/main/java/com/example/data/qubo/DeterministicRNG.kt` — Mulberry32 deterministic RNG.
- `app/src/main/java/com/example/data/qubo/QuboPolicyEngine.kt` — QUBO construction, energy delta, Metropolis simulated annealing, deterministic cooling, and QUBO-to-Ising transformation.
- Source inspected at commit `b85aa98445caecf8607738cd9d4b9f9ba178e8d3`.

The authoritative verifier remains this repository's Python backend:

- `backend/app/verifier.py` imports the real `z3-solver` package and checks the fixed candidate as SAT / UNSAT / UNKNOWN.
- `backend/app/service.py` hashes the verification payload and appends it to the configured audit chain.

## One-call flow

```text
POST /v1/hybrid/solve
  -> deterministic QUBO matrix
  -> QUBO -> Ising J/h/offset transform
  -> seeded simulated annealing candidate search
  -> candidate + trajectory/model hashes
  -> real server-side Z3 verification
  -> SAT / UNSAT / UNKNOWN
  -> SHA-256 proof
  -> audit.event_hash
```

The same flow is exposed as the MCP tool `solve_policy_hybrid`.

## Truth boundary

The annealing result is a **candidate**, not a formal proof. Only the server-side Z3 result is treated as the authoritative verification state.

- `Z3_VERIFIED`: Z3 returned SAT for the exact candidate and constraints.
- `Z3_REJECTED`: Z3 returned UNSAT.
- `Z3_UNKNOWN`: Z3 could not establish SAT or UNSAT.

The service does not turn an annealing success into a proof claim by itself.

## Request example

```json
{
  "preset_name": "TEST",
  "rules": [
    {
      "id": 10,
      "name": "A",
      "cost": 10,
      "risk_reduction": 5,
      "business_value": 10,
      "category": "TEST"
    },
    {
      "id": 20,
      "name": "B",
      "cost": 10,
      "risk_reduction": 10,
      "business_value": 20,
      "category": "TEST"
    }
  ],
  "constraints": [
    {
      "type": "implication",
      "if_rule": 10,
      "then_rule": 20,
      "description": "A requires B"
    },
    {
      "type": "max_cost",
      "budget": 20,
      "description": "Budget cap"
    }
  ],
  "config": {
    "seed": 42,
    "max_iterations": 5000,
    "initial_temperature": 100.0,
    "min_temperature": 0.001,
    "cooling_rate": 0.995,
    "penalty_weight": 1000.0
  }
}
```

## Evidence returned

The response includes:

- selected binary configuration;
- QUBO energy and feasibility penalty;
- deterministic seed and executed iteration count;
- `qubo_matrix_hash`;
- `ising_model_hash`;
- `trajectory_hash`;
- candidate `solution_hash`;
- Z3 status and unsat core when applicable;
- proof hash and optional HMAC signature;
- tamper-evident audit sequence / previous hash / event hash.

## Current scope

This endpoint solves the existing DSG policy constraint language: implication, equivalence, mutual exclusion, at-least-one, minimum-active, and maximum-cost. It is not yet a general theorem prover for arbitrary mathematical statements. Research benchmarks must first formalize each problem into a supported finite constraint model or add a dedicated formalization layer.
