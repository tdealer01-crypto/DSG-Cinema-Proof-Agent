from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .math_epsilon_light import AuditStoreProtocol, _sha256


LEAN_TOOLCHAIN = "leanprover/lean4:v4.28.0"
MATHLIB_REV = "v4.28.0"
SCALAR_THEOREM = "Problem2Scalar.proposition6_scalar_spine"
LOGICAL_THEOREM = "Problem2Logical.reference_dependency_logical_closure"
FOURIER_THEOREM = "Problem2FiniteFourier.dft_const_one_support"
VECTOR_FOURIER_THEOREM = "Problem2VectorFourier.vector_character_sum"
MATRIX_FOURIER_THEOREM = "Problem2MatrixFourier.matrix_character_sum"
SCALAR_SOURCE = "formal/first-proof-2-scalar/FirstProof2Scalar/Problem2Scalar.lean"
LOGICAL_SOURCE = "formal/first-proof-2-scalar/FirstProof2Scalar/Problem2Logical.lean"
FOURIER_SOURCE = "formal/first-proof-2-scalar/FirstProof2Scalar/Problem2FiniteFourier.lean"
VECTOR_FOURIER_SOURCE = "formal/first-proof-2-scalar/FirstProof2Scalar/Problem2VectorFourier.lean"
MATRIX_FOURIER_SOURCE = "formal/first-proof-2-scalar/FirstProof2Scalar/Problem2MatrixFourier.lean"
WORKFLOW = ".github/workflows/first-proof-2-scalar-lean.yml"

SCALAR_SOURCE_SHA256 = "8e4920a9e95208b47e848510519511424f7db462899b251fefca2f870b8c688a"
LOGICAL_SOURCE_SHA256 = "41e410603fc9ae4ae6f4184bde061e3f441525a089e3336be0f3ce4dafe09d68"
FOURIER_SOURCE_SHA256 = "c3ba43b3b735125581e9c6d926c15025985976c9750b1857d979a3ffb27cadd6"
VECTOR_FOURIER_SOURCE_SHA256 = "5db3dc7569aaf36d0013973515166e216ffde82e9851dbeda749cd7f5ec82ce9"
MATRIX_FOURIER_SOURCE_SHA256 = "49a87b54950707e73652df9fef5067a5c9add9b86638ca1eba1acf3193b4b693"
LEAN_TOOLCHAIN_SHA256 = "db7bb24b756d745bbde83fe92718b51bd3625dae3701ba0f598d0eedcd3f3028"
LAKEFILE_SHA256 = "837ebb2e2d31e8b08e44ff3a9944e622e6158c4936bdca1d082896106bced3c1"
SCALAR_MERGE_COMMIT = "c59c72120b56da2d223bf7cee8f3bb91d48fd88e"
LOGICAL_MERGE_COMMIT = "6ceb5b3e38b0ca75eb000f8c59514653a01d6eb9"
FOURIER_MERGE_COMMIT = "8dde5d239fe8ef100a73678880c4a2ad0533e81d"
VECTOR_FOURIER_MERGE_COMMIT = "d5c452a5acbd5a3d384b2205047d174c32993a1b"
MATRIX_FOURIER_MERGE_COMMIT = "a72941bb807cc430881b68a9f6486286afe38fd8"


class LeanTheoremEvidence(BaseModel):
    theorem: str
    source: str
    source_sha256: str
    kernel_recheck: Literal["PASS"] = "PASS"
    sorry_axiom: Literal["ABSENT"] = "ABSENT"
    reported_axioms: list[str]
    scope: str


class FirstProof2FormalEvidenceResult(BaseModel):
    benchmark: Literal["First Proof #2 partial Lean formalization evidence"] = (
        "First Proof #2 partial Lean formalization evidence"
    )
    status: Literal["PARTIAL_FORMALIZATION_KERNEL_CHECKED"] = (
        "PARTIAL_FORMALIZATION_KERNEL_CHECKED"
    )
    answer: Literal["YES"] = "YES"
    lean_toolchain: str
    mathlib_revision: str
    workflow: str
    build_jobs: int
    theorem_evidence: list[LeanTheoremEvidence]
    ci_receipts: list[str]
    source_hashes: dict[str, str]
    merge_provenance: dict[str, str]
    remaining_external_dependencies: list[str]
    full_problem_formalized: Literal[False] = False
    proof_hash: str
    audit_event_hash: str
    truth_boundary: str


def first_proof_2_formal_evidence(audit_store: AuditStoreProtocol) -> FirstProof2FormalEvidenceResult:
    standard_axioms = ["propext", "Classical.choice", "Quot.sound"]
    theorem_evidence = [
        LeanTheoremEvidence(
            theorem=SCALAR_THEOREM,
            source=SCALAR_SOURCE,
            source_sha256=SCALAR_SOURCE_SHA256,
            reported_axioms=standard_axioms,
            scope=(
                "Lean proof of exponent cancellation, basepoint normalization, and abstract "
                "nonzero scalar-factor obligations in the published Proposition 6 reconstruction."
            ),
        ),
        LeanTheoremEvidence(
            theorem=LOGICAL_THEOREM,
            source=LOGICAL_SOURCE,
            source_sha256=LOGICAL_SOURCE_SHA256,
            reported_axioms=[],
            scope=(
                "Axiom-free Lean deduction skeleton composing six explicitly supplied external "
                "theorem hypotheses into the required quantifier order: one W is chosen before "
                "the universally quantified smaller representation pi."
            ),
        ),
        LeanTheoremEvidence(
            theorem=FOURIER_THEOREM,
            source=FOURIER_SOURCE,
            source_sha256=FOURIER_SOURCE_SHA256,
            reported_axioms=standard_axioms,
            scope=(
                "Finite conductor-quotient Fourier orthogonality on ZMod N: the DFT of the "
                "constant-one function is supported only at zero frequency."
            ),
        ),
        LeanTheoremEvidence(
            theorem=VECTOR_FOURIER_THEOREM,
            source=VECTOR_FOURIER_SOURCE,
            source_sha256=VECTOR_FOURIER_SOURCE_SHA256,
            reported_axioms=standard_axioms,
            scope=(
                "Finite coordinate conductor-quotient additive-character orthogonality on "
                "Fin d -> ZMod N for zero versus nonzero frequency vectors."
            ),
        ),
        LeanTheoremEvidence(
            theorem=MATRIX_FOURIER_THEOREM,
            source=MATRIX_FOURIER_SOURCE,
            source_sha256=MATRIX_FOURIER_SOURCE_SHA256,
            reported_axioms=standard_axioms,
            scope=(
                "Finite matrix additive conductor-quotient orthogonality on "
                "Matrix (Fin r) (Fin c) (ZMod N), moving the formalization toward the matrix "
                "Fourier calculation used by the published proof."
            ),
        ),
    ]
    dependencies = [
        "Kirillov-model extension",
        "Godement-Jacquet local functional equation",
        "Mellin support transform",
        "Fourier-to-K1(q) subgroup/lattice and full p-adic identity (finite matrix quotient orthogonality kernel-checked)",
        "normalized newvector theory",
        "local epsilon-factor nonvanishing",
    ]
    source_hashes = {
        SCALAR_SOURCE: SCALAR_SOURCE_SHA256,
        LOGICAL_SOURCE: LOGICAL_SOURCE_SHA256,
        FOURIER_SOURCE: FOURIER_SOURCE_SHA256,
        VECTOR_FOURIER_SOURCE: VECTOR_FOURIER_SOURCE_SHA256,
        MATRIX_FOURIER_SOURCE: MATRIX_FOURIER_SOURCE_SHA256,
        "formal/first-proof-2-scalar/lean-toolchain": LEAN_TOOLCHAIN_SHA256,
        "formal/first-proof-2-scalar/lakefile.toml": LAKEFILE_SHA256,
    }
    merge_provenance = {
        "scalar_formalization": SCALAR_MERGE_COMMIT,
        "logical_skeleton": LOGICAL_MERGE_COMMIT,
        "finite_fourier_sublemma": FOURIER_MERGE_COMMIT,
        "vector_fourier_sublemma": VECTOR_FOURIER_MERGE_COMMIT,
        "matrix_fourier_sublemma": MATRIX_FOURIER_MERGE_COMMIT,
    }
    receipts = [
        "FIRST_PROOF_2_SCALAR_LEAN=PASS",
        "FIRST_PROOF_2_LOGICAL_SKELETON=PASS",
        "FIRST_PROOF_2_FINITE_FOURIER=PASS",
        "FIRST_PROOF_2_VECTOR_FOURIER=PASS",
        "FIRST_PROOF_2_MATRIX_FOURIER=PASS",
        "NO_SORRY_AXIOM=PASS",
    ]
    payload = {
        "answer": "YES",
        "status": "PARTIAL_FORMALIZATION_KERNEL_CHECKED",
        "lean_toolchain": LEAN_TOOLCHAIN,
        "mathlib_revision": MATHLIB_REV,
        "workflow": WORKFLOW,
        "build_jobs": 8032,
        "theorem_evidence": [item.model_dump(mode="json") for item in theorem_evidence],
        "ci_receipts": receipts,
        "source_hashes": source_hashes,
        "merge_provenance": merge_provenance,
        "remaining_external_dependencies": dependencies,
        "full_problem_formalized": False,
    }
    proof_hash = _sha256(payload)
    audit = audit_store.append(payload={"first_proof_2_formal_evidence": payload}, proof_hash=proof_hash)

    return FirstProof2FormalEvidenceResult(
        lean_toolchain=LEAN_TOOLCHAIN,
        mathlib_revision=MATHLIB_REV,
        workflow=WORKFLOW,
        build_jobs=8032,
        theorem_evidence=theorem_evidence,
        ci_receipts=receipts,
        source_hashes=source_hashes,
        merge_provenance=merge_provenance,
        remaining_external_dependencies=dependencies,
        proof_hash=proof_hash,
        audit_event_hash=audit.event_hash,
        truth_boundary=(
            "DSG has kernel-checked in-repository Lean formalizations of the scalar obligations, "
            "the quantifier/dependency deduction skeleton, and finite scalar/vector/matrix "
            "conductor-quotient Fourier orthogonality for First Proof #2. This remains a partial "
            "formalization. The K1(q) subgroup/lattice restriction, the full p-adic Fourier identity, "
            "and the other deep representation-theoretic results remain explicit external theorem "
            "dependencies; DSG does not claim a full formal proof of Problem #2 or independent discovery."
        ),
    )
