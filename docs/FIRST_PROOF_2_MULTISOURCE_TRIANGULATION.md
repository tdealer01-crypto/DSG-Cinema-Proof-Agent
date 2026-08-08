# First Proof #2 — multisource proof triangulation

This track strengthens the evidence around First Proof Problem #2 without changing the claim boundary.

## Sources

### 1. Official human solution

- Source: First Proof Solutions and Comments.
- Author of the solution: Paul Nelson.
- Answer: YES.
- Route: Kirillov extension -> Godement-Jacquet functional equation -> Mellin/Fourier transform -> `K1(q)` characteristic-function identity -> normalized newvector -> explicit nonzero scalar.

### 2. Google DeepMind Aletheia

Pinned public source:

```text
repository: google-deepmind/superhuman
commit: a02069ef66dbae4c5b0713ba0dc144a35375558f
path: aletheia/FirstProof/FP2_Af.tex
Git blob SHA: 9cae0e02192093ac828d5688184ce7daf66e9eed
```

The Aletheia paper reports Problem #2 as solved according to majority expert assessments. Its final response follows a route materially different from the official Proposition 6 calculation: it fixes a universal Whittaker vector using mirabolic/Kirillov restriction, removes the `s` dependence by reducing to a compact `K_n` functional, and uses conductor-level finite Fourier/newvector structure for nonvanishing.

DSG records this as a pinned external route. DSG does not claim authorship of the Aletheia proof.

### 3. Zhang–Ma Lean 4 preprint

Zenodo record:

```text
https://zenodo.org/records/18635744
```

The record reports a Lean 4 proof skeleton for Q2 that axiomatizes deep external theorems and machine-checks the logical deduction chain.

Current DSG status:

```text
REPORT_ONLY_NOT_REPLAYED
```

DSG has not located a public Lean source tree and immutable source commit for this Q2 skeleton. Therefore it is not presented as a deterministic Lean replay.

## Shared invariants

The official and Aletheia routes independently support the following critical structure:

1. The larger-group Whittaker vector `W` is fixed before `pi` is chosen.
2. `W` must not depend on `pi`, its conductor `q`, or generator `Q`.
3. The conductor data and the smaller-group vector `V` may depend on `pi`.
4. The final construction controls/removes `s` dependence and proves a finite nonzero integral for every `s`.
5. The accepted routes do not rely on the false strong Howe-vector support shortcut documented in the incorrect OpenAI attempt.

## DSG machine checks

Before issuing `MULTISOURCE_CORROBORATED`, DSG re-runs:

- universal-`W` quantifier guard;
- documented `W_DEPENDS_ON_PI` failure-mode guard;
- Proposition 6 exponent-cancellation Z3 obligation;
- basepoint-normalization Z3 obligation;
- nonzero-scalar-factor Z3 obligation;
- immutable Aletheia commit and Git blob pins.

The certificate is hashed and appended to the tamper-evident audit chain.

## Claim boundary

`MULTISOURCE_CORROBORATED` means that multiple public solution routes agree on the YES answer and the critical quantifier/nonvanishing structure, while DSG independently re-runs its own deterministic metadata/scalar checks.

It does **not** mean:

- Z3 proves p-adic representation theory;
- DSG has a full Lean/Coq formalization of Problem #2;
- the reported Zhang–Ma Lean skeleton has been kernel-replayed by DSG;
- DSG independently discovered the solution.

The remaining strongest upgrade is a deterministic proof-assistant replay from a public, immutable Q2 formalization source tree, or a new full formalization of the six deep representation-theoretic dependencies already listed in `FIRST_PROOF_2_RECONSTRUCTION_AUDIT.md`.
