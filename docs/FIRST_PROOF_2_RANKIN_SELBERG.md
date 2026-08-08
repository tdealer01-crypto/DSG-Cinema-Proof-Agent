# First Proof #2 — Rankin–Selberg Test Vector Verification Track

## Status

**Mathematical answer:** YES, by the published human solution of Paul Nelson in *First Proof solutions and comments*.

**DSG status:** reference-theorem closure / proof-obligation tracking. This repository does **not** claim an independent discovery or an independent machine formalization of the p-adic representation-theory proof.

**OpenAI status:** OpenAI publicly states that its Problem #2 attempt is now believed to be incorrect after the official commentary and community analysis.

## Problem contract

Fix a generic irreducible admissible representation `Pi` of `GL_{n+1}(F)` in its `psi^{-1}`-Whittaker model. The problem asks whether there exists a **single** Whittaker vector `W` such that, for **every** generic irreducible admissible representation `pi` of `GL_n(F)`, with conductor ideal `q`, generator `Q` of `q^{-1}`, and `u_Q = I_{n+1} + Q E_{n,n+1}`, one can choose `V` in the `psi`-Whittaker model of `pi` so that the shifted local Rankin–Selberg integral is finite and nonzero for every complex `s`.

The critical quantifier is:

```text
exists W = W(Pi, psi)
  such that for every pi
    there exists V = V(pi)
```

The following weaker statement is **not enough**:

```text
for every pi
  there exists W = W(Pi, pi, psi)
```

The conductor-dependent translate `u_Q` may vary with `pi`; the underlying Whittaker vector `W` must not.

## Published proof dependency chain

1. **Fixed Whittaker vector.** Construct `W0` from a compactly supported Whittaker function on `GL_n(F)` and extend it to the `GL_{n+1}(F)` Whittaker model using the Kirillov model. This fixes `W0` before the smaller representation `pi` is chosen.
2. **Conductor / epsilon-factor relation.** For each `pi`, encode the conductor by `Q` and the standard local epsilon-factor relation.
3. **Godement–Jacquet functional equation.** Introduce a radial Schwartz–Bruhat function `beta`, use Mellin inversion, and transport the integral through the local functional equation to `beta-sharp`.
4. **Fourier/congruence identity.** Choose the matrix Schwartz function `phi` so that `beta-sharp(det g) * phi-hat(g)` becomes a scalar multiple of the characteristic function of `K1(q)`.
5. **Newvector nonvanishing.** Take `V` to be the normalized `K1(q)`-invariant newvector. The transformed Rankin–Selberg integral becomes a nonzero scalar times `vol(K1(q))`; homogeneity then gives finiteness and nonvanishing for every `s`.

## Regression guards against the incorrect LLM route

The DSG closure contract rejects the following proof patterns:

- `W_DEPENDS_ON_PI` — proves only the weaker quantifier order.
- `FALSE_HOWE_VECTOR_SUPPORT` — the support condition cited in the failed route conflicts with the central character and is not a valid general Howe-vector statement.
- `CONSTANT_INTEGRAND_REQUIREMENT` — nonvanishing does not require a constant integrand; in the `n=1` model case the integral is a normalized Gauss sum and is generally nonconstant.
- `UNJUSTIFIED_NONVANISHING` — nonvanishing is the core obligation and must come from the functional-equation/newvector calculation rather than a support heuristic.

## What DSG verifies now

`backend/app/math_first_proof_2.py` records the reference proof dependency structure, enforces the universal-`W` dependency contract, hashes the closure payload, and writes it to the tamper-evident audit store.

`backend/tests/test_math_first_proof_2.py` checks that:

- the universal `W` step depends on `Pi` and `psi` only;
- all four documented failure modes remain forbidden;
- the closure result is explicitly reference-scoped;
- proof and audit hashes are emitted.

## Truth boundary

This is **not** yet a Lean/Coq/Isabelle formalization of the Godement–Jacquet functional equation, Kirillov-model extension, local epsilon factors, or newvector theory. Python tests cannot prove those mathematical results. The published human proof remains the mathematical source of truth for those steps.

The next meaningful verification target is a formal or independently referee-checked reconstruction of the dependency chain without the invalid Howe-vector support shortcut.

## Sources

- Official solutions/comments: https://1stproof.org/documents/FirstProofSolutionsComments.pdf
- OpenAI status: https://openai.com/index/first-proof-submissions/
