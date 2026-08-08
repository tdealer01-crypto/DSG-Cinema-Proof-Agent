# Hybrid truth boundary

The hybrid runtime uses two distinct stages and must not conflate them:

1. **Candidate search** — deterministic QUBO/Ising-equivalent simulated annealing proposes a binary configuration. This is optimization output, not a proof.
2. **Authoritative verification** — the existing server-side Python `z3-solver` checks the exact candidate against the declared constraints.

Allowed top-level statuses:

- `Z3_VERIFIED` — Z3 returned SAT for the exact candidate.
- `Z3_REJECTED` — Z3 returned UNSAT.
- `Z3_UNKNOWN` — Z3 returned UNKNOWN.

A candidate search result alone must never be described as formally verified.
