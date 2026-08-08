# Hybrid integration status

## Implemented on research branch

- Deterministic Mulberry32 PRNG ported from `Compliance-ising-z3-Deterministic-`.
- QUBO policy matrix construction ported from the same source.
- QUBO to Ising `J / h / offset` transformation ported from the same source.
- Deterministic Metropolis simulated annealing candidate search.
- Deterministic trajectory, QUBO-matrix, Ising-model, and solution SHA-256 hashes.
- Candidate forwarded to the existing real Python `z3-solver` verifier.
- Existing proof hash, optional HMAC signature, and tamper-evident audit chain reused without simulation.
- FastAPI endpoint `POST /v1/hybrid/solve`.
- MCP tool `solve_policy_hybrid`.
- Tests for replay determinism, Z3-verified SAT, and impossible-policy rejection.

## Not claimed until CI evidence exists

- Full dependency-installed test pass for this branch.
- Production deployment of the new endpoint.
- General mathematical theorem proving.
- Any result for the OpenAI First Proof ten-problem benchmark.

The branch must pass the repository GitHub Actions workflow before merge.
