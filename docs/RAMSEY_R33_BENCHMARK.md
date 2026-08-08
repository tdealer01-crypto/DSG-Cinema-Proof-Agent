# Ramsey R(3,3)=6 — exact Ising + Z3 benchmark

This benchmark is a machine-checked validation target for the DSG hybrid math path.
It is a classical theorem, not a claim that DSG has solved one of the 2026 open research problems.

## The theorem

`R(3,3)=6` means:

- there exists a red/blue coloring of the edges of `K5` with no monochromatic triangle; and
- every red/blue coloring of the edges of `K6` contains a monochromatic triangle.

Together these establish the exact Ramsey number.

## Ising formulation

Each graph edge is a spin `s_e ∈ {-1,+1}` representing one of two colors.
For a triangle with edge spins `a,b,c`, the exact monochromatic-triangle indicator is

```text
(1 + a*b + a*c + b*c) / 4
```

It equals `1` iff all three spins are equal and `0` otherwise. Summing this term over all triangles gives a quadratic Ising Hamiltonian whose energy is exactly the number of monochromatic triangles. No cubic-to-QUBO reduction, ancilla variable, or approximation is used.

## Proof path

```text
K5
  -> deterministic Ising simulated annealing (seed=42)
  -> zero-energy coloring candidate
  -> Z3 fixes every edge to that candidate
  -> SAT
  -> proves R(3,3) > 5

K6
  -> Z3 encodes every edge as a Boolean color
  -> for every triangle: not(all red) AND not(all blue)
  -> solver.check()
  -> UNSAT
  -> proves R(3,3) <= 6

SAT witness + UNSAT exhaustive finite proof
  -> R(3,3) = 6
  -> SHA-256 proof hash
  -> tamper-evident audit event
```

## API

```text
POST /v1/math/ramsey-r33/prove
```

The endpoint returns:

- `status`: `PROVED` only when the K5 Ising witness has energy 0, Z3 verifies that fixed witness as SAT, and Z3 proves the K6 existence formula UNSAT;
- the K5 edge coloring;
- Ising model, trajectory, candidate, and SMT2 hashes;
- Z3 version/status for both finite checks;
- proof hash and audit-chain event.

The same benchmark is available through MCP tool `prove_ramsey_r33_mcp`.

## Truth boundary

This proves only the finite classical theorem `R(3,3)=6`. It validates that the repository can perform a real deterministic Ising search and an exact Z3 proof in one auditable path. It does not by itself prove any of OpenAI's 2026 First Proof research submissions or other open-ended universal theorems.
