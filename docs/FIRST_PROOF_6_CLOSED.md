# First Proof #6 — theorem closure

## Status

**Mathematical answer: YES.** A universal constant exists. The official human solution by Daniel Spielman proves the stronger statement for every finite weighted undirected graph with

\[
|S| \ge \frac{\varepsilon n}{42},\qquad \varepsilon L-L_S \succeq 0,
\]

for `0 < epsilon < 1`. Therefore the original simple-graph problem is closed with `c = 1/42`.

This repository does **not** claim independent discovery of that theorem. DSG records and checks the proof provenance, verifies the scalar constant arithmetic with Z3, and keeps the previous finite-instance machinery as executable regression evidence.

## Proof architecture

The reference proof can be organized into five dependencies:

1. Normalize induced Laplacians with the Moore–Penrose inverse square root of the full Laplacian. This turns epsilon-lightness into an operator-norm bound on a normalized matrix.
2. Use effective-resistance leverage scores to control the cost of adding a new vertex to a growing set.
3. Use a truncated one-sided BSS barrier potential that tracks only the largest `sigma` eigenvalues, where `sigma = floor(epsilon*n/42)`.
4. At each greedy step, more than half of the unused vertices satisfy the leverage bound and at least half satisfy the barrier bound, so an acceptable next vertex exists.
5. Starting from one vertex and performing `sigma` additions keeps the spectral barrier at most `epsilon` and produces `sigma + 1 > epsilon*n/42` vertices.

The constants used by the reference argument are `delta = 21/n`, `phi = n/21`, and `sigma = floor(epsilon*n/42)`.

## DSG verification boundary

`backend/app/math_epsilon_light_theorem.py` checks the scalar spine of the argument by asking Z3 for counterexamples to each required inequality. Every encoded negation must be `UNSAT` before a closure certificate is emitted.

The matrix-analysis lemmas themselves are not re-proved by Z3 in this repository. They are supplied by the official reference proof. A separate public Lean artifact for First Proof #6 is linked as independent formal evidence; DSG records that reference but does not claim to have recompiled that external project locally.

## Evidence

- Official reference solution: `https://cowles.yale.edu/sites/default/files/2026-04/d2511.pdf`
- Public Lean artifact: `https://github.com/frenzymath/Archon-FirstProof-Results/blob/main/FirstProof/FirstProof6/Problem6.lean`
- Earlier OpenAI proof attempt (`c = 1/256`): `https://cdn.openai.com/pdf/26177a73-3b75-4828-8c91-e8f1cf27aaa0/oai_first_proof.pdf`

## Claim policy

Allowed claim: **“First Proof #6 is solved in the literature; DSG has a provenance-linked closure certificate and machine-checks the scalar constant arithmetic for the official `c=1/42` proof.”**

Disallowed claim: **“DSG independently discovered the solution to First Proof #6.”**
