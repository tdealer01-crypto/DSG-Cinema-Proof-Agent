# First Proof #6 — Finite ε-light Vertex Subset Benchmark

## Source problem

First Proof problem #6 asks whether there is a universal constant `c > 0` such that, for every graph `G=(V,E)` and every `ε in (0,1]`, there is a subset `S` of size at least `c ε |V|` satisfying

`εL - L_S >= 0`

in the positive-semidefinite (Loewner) order, where `L` is the graph Laplacian and `L_S` keeps only edges with both endpoints in `S`.

OpenAI's published proof attempt proposes `c = 1/256`. This repository does **not** claim to prove that universal theorem.

Source: https://openai.com/index/first-proof-submissions/

## What DSG verifies now

The first benchmark is deliberately finite and nontrivial:

- graph: complete graph `K8`
- epsilon: `1/2`
- target: `|S| >= 4`
- candidate search: deterministic QUBO / Ising-equivalent simulated annealing
- authoritative check: exact rational matrix `M = εL - L_S`
- PSD certificate: every principal minor of `M` is computed exactly with rational arithmetic
- Z3: checks the fixed subset cardinality and all rational principal-minor inequalities
- evidence: QUBO hash, Ising-model hash, trajectory hash, candidate hash, matrix hash, certificate hash, SMT2 hash, proof hash, and audit event hash

For an `8 x 8` matrix there are `2^8 - 1 = 255` nonempty principal minors. A symmetric real matrix is PSD iff all principal minors are nonnegative, so this is an exact finite-instance certificate.

## Why this is not a trivial independent-set case

For the benchmark candidate `|S|=4` in `K8`, the induced subgraph has six internal edges. Therefore `L_S` is nonzero. The benchmark exercises the actual matrix inequality instead of succeeding only because `S` has no internal edges.

## Run the built-in benchmark

`POST /v1/math/first-proof-6/benchmark`

No request body is required.

Read these fields first:

- `result.status`
- `result.candidate.subset`
- `result.candidate.internal_edges`
- `result.verification.status`
- `result.verification.principal_minors_checked`
- `result.verification.negative_principal_minors`
- `result.proof_hash`
- `result.audit.event_hash`

`FINITE_INSTANCE_VERIFIED` means the fixed candidate met the size target, the exact rational PSD certificate had no negative principal minor, and Z3 returned SAT for the complete certificate.

`CANDIDATE_REJECTED` means the candidate failed the target or exact PSD verification.

`UNKNOWN` means the authoritative verifier did not establish either state.

## Verify another finite graph

`POST /v1/math/first-proof-6/verify-instance`

Example payload:

```json
{
  "vertices": 6,
  "edges": [[0,1],[1,2],[2,3],[3,4],[4,5]],
  "epsilon_numerator": 1,
  "epsilon_denominator": 2,
  "target_size": 3,
  "seed": 42,
  "max_iterations": 5000
}
```

The current exact principal-minor verifier limits graphs to at most 10 vertices because the number of principal minors grows exponentially.

## Search vs proof boundary

The QUBO objective targets the requested subset size and uses an internal-edge penalty as a sparsity surrogate. It is a candidate-search heuristic only; it does **not** encode the PSD condition exactly.

The proof boundary starts after a candidate is fixed:

1. build `L` and `L_S` exactly using rational numbers;
2. build `M = εL - L_S` exactly;
3. compute every principal minor exactly;
4. require every minor to be nonnegative;
5. ask real server-side `z3-solver` to check the fixed membership, size target, and rational certificate;
6. hash the model, certificate, SMT2 representation, result, and audit event.

## Truth boundary

A successful result proves only the supplied finite graph instance. It does not prove that every graph has a sufficiently large ε-light subset, and it does not prove the proposed universal constant `c = 1/256`.
