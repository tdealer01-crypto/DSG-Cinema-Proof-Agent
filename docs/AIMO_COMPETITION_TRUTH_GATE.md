# DSG AIMO Competition Truth Gate

Status: **REVIEW until CI passes and the upstream DSG ONE / DSG AGI Simulation adapters are deployed and exercised end-to-end.**

## Pipeline

```text
dsg-one-v1
  -> deterministic orchestration / shard dispatch
  -> dsg-agi-simulation
  -> deterministic QUBO / Ising candidate + witness
  -> DSG-Cinema-Proof-Agent
  -> exact integer recomputation + hash binding + Z3 global-optimality query
  -> PASS / REVIEW / BLOCKED + tamper-evident audit receipt
```

## Final endpoint

`POST /v1/math/aimo/exact-energy-witness`

The request must include:

- canonical problem object and `problemHash`
- integer `qubo-v1` or `ising-v1` encoding and `encodingHash`
- assignment index
- bits or spins
- claimed integer energy
- `proveOptimality=true` for a final competition certificate

## What PASS means

PASS is fail-closed and requires all of the following:

1. The problem hash recomputes exactly from the supplied problem envelope.
2. The encoding hash recomputes exactly from the supplied finite encoding.
3. The supplied bits/spins reconstruct the supplied assignment index.
4. Exact Python integer arithmetic recomputes the claimed energy.
5. A fixed-witness Z3 check proves `energy != claimed_energy` UNSAT.
6. With `proveOptimality=true`, a second Z3 query proves that the existence of any assignment with strictly lower energy is UNSAT.
7. The certificate and audit event are hashed and persisted.

The only final PASS certificate level is:

`VERIFIED_GLOBAL_OPTIMUM`

A witness that is correct but has not had global optimality proved stays `REVIEW` with `proof_complete=false`.

If Z3 finds a better assignment, the candidate is `BLOCKED` and the returned counterexample is intended to be fed back into deterministic search.

If Z3 returns UNKNOWN, the result is `REVIEW`; UNKNOWN never becomes PASS.

## Truth boundary

This gate proves optimality only for the supplied finite integer QUBO/Ising encoding. It does not by itself prove that an encoder correctly captured every semantic requirement of an olympiad problem stated in natural language.

Therefore the full competition system still needs a trustworthy problem-to-encoding/proof strategy layer and, where applicable, an independent theorem/proof checker such as Lean or another exact domain-specific verifier.

## Upstream contract

`dsg-agi-simulation` should send verification payloads to this endpoint with the same problem object it hashed during shard creation. Do not send only the hash: Cinema independently recomputes the hash from the problem envelope.

Recommended verification payload:

```json
{
  "schemaVersion": "dsg-aimo-exact-energy-v1",
  "problemId": "sealed-001",
  "problem": {
    "problemId": "sealed-001",
    "statement": "...",
    "constraints": {
      "aimoEncoding": {}
    }
  },
  "problemHash": "sha256:...",
  "encodingHash": "sha256:...",
  "encoding": {},
  "witness": {
    "kind": "qubo-v1",
    "assignmentIndex": "0",
    "variableCount": 1,
    "energy": "0",
    "bits": [0]
  },
  "proveOptimality": true,
  "z3TimeoutMs": 30000
}
```

## Competition readiness gates

Do not claim `AIMO_COMPETITION_READY` until all are evidenced:

- Cinema backend CI PASS
- existing deterministic Lean replay regression PASS
- DSG AGI Simulation deterministic replay tests PASS
- DSG ONE orchestration tests PASS
- deployed URLs and authentication configured
- one sealed unseen end-to-end run with no human intervention
- replay of that run produces the same deterministic core receipt
- measured latency/compute budget fits the competition rules in force at submission time
