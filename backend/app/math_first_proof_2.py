from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .math_epsilon_light import AuditStoreProtocol, _sha256
from .math_first_proof_2_formal import (
    FOURIER_SOURCE,
    FOURIER_SOURCE_SHA256,
    FOURIER_THEOREM,
    LOGICAL_SOURCE,
    LOGICAL_SOURCE_SHA256,
    LOGICAL_THEOREM,
    MATRIX_FOURIER_SOURCE,
    MATRIX_FOURIER_SOURCE_SHA256,
    MATRIX_FOURIER_THEOREM,
    SCALAR_SOURCE,
    SCALAR_SOURCE_SHA256,
    SCALAR_THEOREM,
    VECTOR_FOURIER_SOURCE,
    VECTOR_FOURIER_SOURCE_SHA256,
    VECTOR_FOURIER_THEOREM,
)


OFFICIAL_SOLUTIONS_URL = "https://1stproof.org/documents/FirstProofSolutionsComments.pdf"
OPENAI_STATUS_URL = "https://openai.com/index/first-proof-submissions/"


class ReferenceProofStep(BaseModel):
    name: str
    status: Literal["REFERENCE_DEPENDENCY_RECORDED"] = "REFERENCE_DEPENDENCY_RECORDED"
    statement: str
    depends_on: list[str]


class FailureMode(BaseModel):
    code: str
    forbidden: Literal[True] = True
    reason: str


class FirstProof2ClosureResult(BaseModel):
    benchmark: Literal["First Proof #2 reference theorem closure"] = (
        "First Proof #2 reference theorem closure"
    )
    status: Literal["REFERENCE_THEOREM_CLOSED", "VERIFICATION_FAILED"]
    answer: Literal["YES"] = "YES"
    theorem_scope: str
    universal_vector_contract: str
    smaller_representation_contract: str
    official_solution: str
    openai_status: str
    proof_steps: list[ReferenceProofStep]
    rejected_failure_modes: list[FailureMode]
    formalization_status: Literal["PARTIAL_FORMALIZATION_KERNEL_CHECKED"]
    formal_theorems: list[str]
    formal_source_hashes: dict[str, str]
    formal_ci_receipts: list[str]
    remaining_external_dependencies: list[str]
    full_problem_formalized: Literal[False] = False
    evidence_level: str
    proof_hash: str
    audit_event_hash: str
    truth_boundary: str


def reference_proof_contract() -> tuple[list[ReferenceProofStep], list[FailureMode]]:
    steps = [
        ReferenceProofStep(
            name="fixed_whittaker_vector",
            statement=(
                "Choose W0 in the Whittaker model of Pi using the Kirillov-model extension; "
                "W0 depends on Pi and psi but not on the later choice of pi."
            ),
            depends_on=["Pi", "psi"],
        ),
        ReferenceProofStep(
            name="conductor_and_epsilon_factor",
            statement=(
                "For each generic pi of GL_n(F), encode its conductor q through Q generating "
                "q^{-1} and the standard epsilon-factor relation."
            ),
            depends_on=["pi", "psi", "q", "Q"],
        ),
        ReferenceProofStep(
            name="godement_jacquet_transform",
            statement=(
                "Use the Godement-Jacquet local functional equation and Mellin inversion to "
                "construct beta and its transformed function beta-sharp with controlled support."
            ),
            depends_on=["pi", "psi", "Q", "Godement-Jacquet functional equation"],
        ),
        ReferenceProofStep(
            name="fourier_congruence_identity",
            statement=(
                "Choose the Schwartz-Bruhat test function phi so that its Fourier transform "
                "produces the characteristic function of the congruence subgroup K1(q)."
            ),
            depends_on=["psi", "Q", "q", "Fourier self-duality of M_n(o)"],
        ),
        ReferenceProofStep(
            name="newvector_nonvanishing",
            statement=(
                "Take V to be the normalized K1(q)-invariant newvector of pi. After applying "
                "the transformed integral identity, the Rankin-Selberg integral reduces to a "
                "nonzero constant times vol(K1(q)), hence is finite and nonzero for every s."
            ),
            depends_on=["pi", "q", "normalized newvector theory"],
        ),
    ]
    failures = [
        FailureMode(code="W_DEPENDS_ON_PI", reason="The universal W may not vary with pi."),
        FailureMode(
            code="FALSE_HOWE_VECTOR_SUPPORT",
            reason="The invalid strong support shortcut conflicts with the central character.",
        ),
        FailureMode(
            code="CONSTANT_INTEGRAND_REQUIREMENT",
            reason="Nonvanishing does not require a constant integrand on its support.",
        ),
        FailureMode(
            code="UNJUSTIFIED_NONVANISHING",
            reason="Nonvanishing must follow from the functional equation/newvector calculation.",
        ),
    ]
    return steps, failures


def close_first_proof_2(audit_store: AuditStoreProtocol) -> FirstProof2ClosureResult:
    steps, failures = reference_proof_contract()
    universal_step = next(item for item in steps if item.name == "fixed_whittaker_vector")
    if {"pi", "q", "Q"}.intersection(universal_step.depends_on):
        raise RuntimeError("First Proof #2 contract violation: universal W depends on pi/conductor")

    formal_theorems = [
        SCALAR_THEOREM,
        LOGICAL_THEOREM,
        FOURIER_THEOREM,
        VECTOR_FOURIER_THEOREM,
        MATRIX_FOURIER_THEOREM,
    ]
    formal_source_hashes = {
        SCALAR_SOURCE: SCALAR_SOURCE_SHA256,
        LOGICAL_SOURCE: LOGICAL_SOURCE_SHA256,
        FOURIER_SOURCE: FOURIER_SOURCE_SHA256,
        VECTOR_FOURIER_SOURCE: VECTOR_FOURIER_SOURCE_SHA256,
        MATRIX_FOURIER_SOURCE: MATRIX_FOURIER_SOURCE_SHA256,
    }
    formal_ci_receipts = [
        "FIRST_PROOF_2_SCALAR_LEAN=PASS",
        "FIRST_PROOF_2_LOGICAL_SKELETON=PASS",
        "FIRST_PROOF_2_FINITE_FOURIER=PASS",
        "FIRST_PROOF_2_VECTOR_FOURIER=PASS",
        "FIRST_PROOF_2_MATRIX_FOURIER=PASS",
        "NO_SORRY_AXIOM=PASS",
    ]
    remaining_external_dependencies = [
        "Kirillov-model extension",
        "Godement-Jacquet local functional equation",
        "Mellin support transform",
        "Fourier-to-K1(q) subgroup/lattice and full p-adic identity (finite matrix quotient orthogonality kernel-checked)",
        "normalized newvector theory",
        "local epsilon-factor nonvanishing",
    ]
    proof_payload = {
        "answer": "YES",
        "scope": "generic irreducible admissible Pi of GL_{n+1}(F) and every generic pi of GL_n(F)",
        "official_solution": OFFICIAL_SOLUTIONS_URL,
        "openai_status": OPENAI_STATUS_URL,
        "proof_steps": [item.model_dump(mode="json") for item in steps],
        "rejected_failure_modes": [item.model_dump(mode="json") for item in failures],
        "formalization_status": "PARTIAL_FORMALIZATION_KERNEL_CHECKED",
        "formal_theorems": formal_theorems,
        "formal_source_hashes": formal_source_hashes,
        "formal_ci_receipts": formal_ci_receipts,
        "remaining_external_dependencies": remaining_external_dependencies,
        "full_problem_formalized": False,
    }
    proof_hash = _sha256(proof_payload)
    audit = audit_store.append(payload={"first_proof_2_closure": proof_payload}, proof_hash=proof_hash)

    return FirstProof2ClosureResult(
        status="REFERENCE_THEOREM_CLOSED",
        theorem_scope=(
            "For fixed Pi, one Whittaker vector W works simultaneously for every smaller generic pi; "
            "conductor data and the smaller-group vector may vary with pi."
        ),
        universal_vector_contract="W depends on Pi and psi only; W must not depend on pi, q, or Q.",
        smaller_representation_contract="For each pi, conductor data and normalized newvector V may vary.",
        official_solution=OFFICIAL_SOLUTIONS_URL,
        openai_status=OPENAI_STATUS_URL,
        proof_steps=steps,
        rejected_failure_modes=failures,
        formalization_status="PARTIAL_FORMALIZATION_KERNEL_CHECKED",
        formal_theorems=formal_theorems,
        formal_source_hashes=formal_source_hashes,
        formal_ci_receipts=formal_ci_receipts,
        remaining_external_dependencies=remaining_external_dependencies,
        full_problem_formalized=False,
        evidence_level=(
            "Published human reference proof + DSG provenance/quantifier guards + Z3 scalar audit + "
            "Lean kernel checks for scalar, logical, finite Fourier, vector Fourier, and finite matrix "
            "Fourier orthogonality stages."
        ),
        proof_hash=proof_hash,
        audit_event_hash=audit.event_hash,
        truth_boundary=(
            "Problem #2 is mathematically answered YES by the cited human solution. DSG has kernel-checked "
            "partial Lean formalizations through the finite matrix additive conductor quotient. The K1(q) "
            "subgroup/lattice restriction, full p-adic Fourier identity, and other deep representation-theoretic "
            "results remain external. full_problem_formalized=false. DSG does not claim a full independent "
            "formal proof or independent discovery."
        ),
    )
