# First Proof #2 — Reference Reconstruction Audit

## Status

`REFERENCE_RECONSTRUCTION_AUDITED`

This artifact reconstructs the dependency chain of the published Paul Nelson solution to First Proof #2 and machine-checks the scalar/logical spine that can honestly be encoded in Z3. It is **not** an independent formalization of non-archimedean representation theory and does not claim independent discovery.

Source of mathematical proof:

- First Proof solutions and comments: https://1stproof.org/documents/FirstProofSolutionsComments.pdf
- Problem #2 statement: Section 3, Question 2.
- Human solution: Appendix section for the Rankin–Selberg test-vector problem, Lemmas 2–5 and Proposition 6.

## The critical quantifier

For fixed generic `Pi` of `GL_{n+1}(F)`, one Whittaker vector `W0` must be selected **before** the smaller representation `pi` is chosen.

Allowed dependence:

```text
W0 = W0(Pi, psi)
```

Forbidden dependence:

```text
W0 = W0(Pi, psi, pi, q, Q)
```

For each later `pi`, its conductor `q`, generator `Q` of `q^{-1}`, and the smaller-group Whittaker vector `V` may vary.

## Published proof chain reconstructed

1. **Fixed W0 / Kirillov extension** — equation (6) constructs the smaller-block Whittaker function and the Kirillov-model statement extends it to the fixed `Pi`.
2. **Conductor and epsilon factor** — equation (1) ties the conductor scale `|Q|` to the local epsilon factor.
3. **Godement–Jacquet functional equation** — Lemma 2 supplies equations (2)–(3).
4. **Mellin support transform** — Lemma 3 constructs `beta` and `beta-sharp` with conductor-controlled support and boundary values.
5. **Integral transform** — Lemma 4 turns the original weighted integral into its Fourier/Godement–Jacquet transform.
6. **Fourier to congruence subgroup** — Lemma 5 proves equations (7)–(8), in particular

```text
beta-sharp(det g) * phi-hat(g) = |Q|^n * 1_{K1(q)}(g).
```

7. **Normalized newvector** — Proposition 6 uses the unique normalized `K1(q)`-invariant newvector `V`, with `V(1)=1`.
8. **Basepoint evaluation** — the transformed integral becomes

```text
|Q|^n * vol(K1(q)).
```

9. **Homogeneity** — equations (19)–(20) propagate the basepoint identity to every complex `s`, yielding

```text
ell_RS(s, u_Q W0, d_Q V) = c * |Q|^(-n/2),
```

with `c != 0` under the standard nonvanishing of the local epsilon factor and positivity of Haar volume.

## What Z3 checks here

`backend/app/math_first_proof_2_reconstruction.py` proves the negations of these scalar claims UNSAT:

- `proposition6_exponent_cancellation` — `-(s-1/2) + (s-(n+1)/2) = -n/2`.
- `basepoint_normalization` — at `s=(n+1)/2`, the exponent in equation (20) is zero.
- `nonzero_scalar_factor` — positive epsilon modulus denominator, positive `|Q|^n`, and positive `vol(K1(q))` imply the modulus of `c` is positive.

These checks are deterministic and tamper-evident through the repository audit chain.

## What remains external mathematics

The following are deliberately labelled `REFERENCE_THEOREM_REQUIRED`:

- Kirillov-model extension.
- Godement–Jacquet local functional equation.
- Mellin inversion/support facts used in Lemma 3.
- Fourier calculation and `K1(q)` characterization in Lemma 5.
- Existence/uniqueness and invariance of the normalized newvector.
- Nonvanishing of the local epsilon factor.

A future full formal proof would need these notions and theorems inside a proof assistant or an independently checkable formal library. Python/Z3 does not substitute for them.

## Why the earlier LLM route failed

The First Proof commentary documents two central failure patterns: allowing `W` to depend on `pi`, which weakens the theorem, and using an invalid stronger support claim for a Howe vector that conflicts with the central character. The correct route instead obtains nonvanishing through the Godement–Jacquet transform and newvector calculation.

## Claim boundary

Allowed claim:

> DSG reconstructs and deterministically audits the scalar/logical spine of the published solution to First Proof #2 while preserving all deep representation-theoretic inputs as explicit cited dependencies.

Not allowed:

> DSG independently solved or fully formalized First Proof #2.
