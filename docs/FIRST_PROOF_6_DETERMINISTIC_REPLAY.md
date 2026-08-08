# First Proof #6 — Deterministic Lean Replay

## Purpose

This gate verifies reproducibility of the existing formal Lean proof of First Proof Problem #6. It does **not** claim that DSG independently discovered the proof.

## Pinned inputs

- Formalization repository: `frenzymath/Archon-FirstProof-Results`
- Formalization commit: `a5694249bd8b94bd1dbab7cc7d477f0fdd322471`
- Lean toolchain: `leanprover/lean4:v4.28.0`
- Mathlib: `v4.28.0` as pinned by the formalization's `lakefile.toml`
- Main theorem file: `FirstProof/FirstProof6/Problem6.lean`
- Main theorem: `Problem6.exists_eps_light_subset`
- Certified bound in this formalization: `c = 1/256`

## PASS criteria

A run is `REPRODUCIBLE_FORMAL_PROOF=PASS` only if all of the following hold in a clean GitHub Actions runner:

1. The external formalization checkout resolves to the exact pinned commit.
2. The `lean-toolchain` file is exactly Lean 4.28.0.
3. The Problem #6 source tree contains no `sorry` or `admit` placeholders.
4. The pinned Mathlib cache/dependencies resolve successfully.
5. `lake build` succeeds from the pinned source.
6. `lake env lean FirstProof/FirstProof6/Problem6.lean` succeeds, causing the Lean kernel to recheck the theorem file.
7. The run prints source/toolchain/file hashes as a replay receipt.

## Interpretation

A PASS establishes that the formal proof is reproducible under the pinned source and toolchain: rerunning the same proof program yields successful kernel checking again.

It does not establish independent discovery by DSG. Provenance remains separate from proof validity and reproducibility.
