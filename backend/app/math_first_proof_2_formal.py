from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .math_epsilon_light import AuditStoreProtocol, _sha256


LEAN_TOOLCHAIN = "leanprover/lean4:v4.28.0"
MATHLIB_REV = "v4.28.0"
SCALAR_THEOREM = "Problem2Scalar.proposition6_scalar_spine"
LOGICAL_THEOREM = "Problem2Logical.reference_dependency_logical_closure"
SCALAR_SOURCE = "formal/first-proof-2-scalar/FirstProof2Scalar/Problem2Scalar.lean"
LOGICAL_SOURCE = "formal/first-proof-2-scalar/FirstProof2Scalar/Problem2Logical.lean"
WORKFLOW = ".github/workflows/first-proof-2-scalar-lean.yml"

SCALAR_SOURCE_SHA256 = "8e4920a9e95208b47e848510519511424f7db462899b251fefca2f870b8c688a"
LOGICAL_SOURCE_SHA256 = "41e410603fc9ae4ae6f4184bde061e3f441525a089e3336be0f3ce4dafe09d68"
LEAN_TOOLCHAIN_SHA256 = "db7bb24b756d745bbde83fe92718b51bd3625dae3701ba0f598d0eedcd3f3028"
LAKEFILE_SHA256 = "837ebb2e2d31e8b08e44ff3a9944e622e6158c4936bdca1d082896106bced3c1"
SCALAR_MERGE_COMMIT = "c59c72120b56da2d223bf7cee8f3bb91d48fd88e"
LOGICAL_MERGE_COMMIT = "6ceb5b3e38b0ca75eb000f8c59514653a01d6eb9"


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
    theorem_evidence = [
        LeanTheoremEvidence(
            theorem=SCALAR_THEOREM,
            source=SCALAR_SOURCE,
            source_sha256=SCALAR_SOURCE_SHA256,
            reported_axioms=["propext", "Classical.choice", "Quot.sound"],
            scope=(
                "Lean proof of the exponent cancellation, basepoint normalization, and abstract "
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
    ]
    dependencies = [
        "Kirillov-model extension",
        "Godement-Jacquet local functional equation",
        "Mellin support transform",
        "Fourier-to-K1(q) identity",
        "normalized newvector theory",
        "local epsilon-factor nonvanishing",
    ]
    source_hashes = {
        SCALAR_SOURCE: SCALAR_SOURCE_SHA256,
        LOGICAL_SOURCE: LOGICAL_SOURCE_SHA256,
        "formal/first-proof-2-scalar/lean-toolchain": LEAN_TOOLCHAIN_SHA256,
        "formal/first-proof-2-scalar/lakefile.toml": LAKEFILE_SHA256,
    }
    merge_provenance = {
        "scalar_formalization": SCALAR_MERGE_COMMIT,
        "logical_skeleton": LOGICAL_MERGE_COMMIT,
    }
    receipts = [
        "FIRST_PROOF_2_SCALAR_LEAN=PASS",
        "FIRST_PROOF_2_LOGICAL_SKELETON=PASS",
        "NO_SORRY_AXIOM=PASS",
    ]
    payload = {
        "answer": "YES",
        "status": "PARTIAL_FORMALIZATION_KERNEL_CHECKED",
        "lean_toolchain": LEAN_TOOLCHAIN,
        "mathlib_revision": MATHLIB_REV,
        "workflow": WORKFLOW,
        "build_jobs": 8029,
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
        build_jobs=8029,
        theorem_evidence=theorem_evidence,
        ci_receipts=receipts,
        source_hashes=source_hashes,
        merge_provenance=merge_provenance,
        remaining_external_dependencies=dependencies,
        proof_hash=proof_hash,
        audit_event_hash=audit.event_hash,
        truth_boundary=(
            "DSG has kernel-checked an in-repository Lean formalization of the scalar obligations "
            "and the quantifier/dependency deduction skeleton for First Proof #2. This is a partial "
            "formalization only. The six deep p-adic representation-theoretic results remain explicit "
            "external theorem dependencies; DSG does not claim a full formal proof of Problem #2 or "
            "independent discovery of its mathematical solution."
        ),
    )
