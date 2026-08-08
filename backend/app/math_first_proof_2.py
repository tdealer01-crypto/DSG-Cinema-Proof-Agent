from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .math_epsilon_light import AuditStoreProtocol, _sha256


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
    evidence_level: str
    proof_hash: str
    audit_event_hash: str
    truth_boundary: str


def reference_proof_contract() -> tuple[list[ReferenceProofStep], list[FailureMode]]:
    """Record the dependency structure of the published proof of First Proof #2.

    This deliberately does not present Python, Z3, or finite computation as a proof of
    p-adic representation theory.  It captures the quantifier/dependency contract that
    invalidated several LLM attempts and the published route that avoids that failure.
    """

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
                "Take V to be the normalized K1(q)-invariant newvector of pi.  After applying "
                "the transformed integral identity, the Rankin-Selberg integral reduces to a "
                "nonzero constant times vol(K1(q)), hence is finite and nonzero for every s."
            ),
            depends_on=["pi", "q", "normalized newvector theory"],
        ),
    ]

    failures = [
        FailureMode(
            code="W_DEPENDS_ON_PI",
            reason=(
                "The problem requires one W that works for every smaller representation pi; "
                "allowing W to depend on pi proves only a weaker statement."
            ),
        ),
        FailureMode(
            code="FALSE_HOWE_VECTOR_SUPPORT",
            reason=(
                "The stronger support condition used in the incorrect LLM route conflicts with "
                "the central character and is not a valid standard Howe-vector theorem."
            ),
        ),
        FailureMode(
            code="CONSTANT_INTEGRAND_REQUIREMENT",
            reason=(
                "Nonvanishing does not require the integrand to be constant on its support; "
                "already for n=1 the relevant integral is a normalized Gauss sum and is generally nonconstant."
            ),
        ),
        FailureMode(
            code="UNJUSTIFIED_NONVANISHING",
            reason=(
                "The nonvanishing step is the core obligation and must be derived from the "
                "functional equation plus newvector calculation, not asserted from support heuristics."
            ),
        ),
    ]
    return steps, failures


def close_first_proof_2(audit_store: AuditStoreProtocol) -> FirstProof2ClosureResult:
    steps, failures = reference_proof_contract()

    # Quantifier/dependency guard: the universal W0 step must not depend on pi, q, or Q.
    universal_step = next(item for item in steps if item.name == "fixed_whittaker_vector")
    forbidden = {"pi", "q", "Q"}
    if forbidden.intersection(universal_step.depends_on):
        raise RuntimeError("First Proof #2 contract violation: universal W depends on pi/conductor")

    proof_payload = {
        "answer": "YES",
        "scope": "generic irreducible admissible Pi of GL_{n+1}(F) and every generic pi of GL_n(F)",
        "official_solution": OFFICIAL_SOLUTIONS_URL,
        "openai_status": OPENAI_STATUS_URL,
        "proof_steps": [item.model_dump(mode="json") for item in steps],
        "rejected_failure_modes": [item.model_dump(mode="json") for item in failures],
    }
    proof_hash = _sha256(proof_payload)
    audit = audit_store.append(payload={"first_proof_2_closure": proof_payload}, proof_hash=proof_hash)

    return FirstProof2ClosureResult(
        status="REFERENCE_THEOREM_CLOSED",
        theorem_scope=(
            "For a fixed generic irreducible admissible Pi of GL_{n+1}(F), one Whittaker vector W "
            "works simultaneously for every generic irreducible admissible pi of GL_n(F); the "
            "conductor-dependent translate u_Q and the smaller-group vector V may vary with pi."
        ),
        universal_vector_contract="W depends on Pi and psi only; W must not depend on pi, q, or Q.",
        smaller_representation_contract=(
            "For each pi, q and Q are its conductor data and V may be chosen as the normalized "
            "K1(q)-invariant newvector."
        ),
        official_solution=OFFICIAL_SOLUTIONS_URL,
        openai_status=OPENAI_STATUS_URL,
        proof_steps=steps,
        rejected_failure_modes=failures,
        evidence_level=(
            "Published human reference proof by Paul Nelson + DSG dependency/provenance contract and "
            "regression guards for the failure modes documented by the First Proof commentary."
        ),
        proof_hash=proof_hash,
        audit_event_hash=audit.event_hash,
        truth_boundary=(
            "Problem #2 is mathematically answered YES by the cited published human solution. "
            "This DSG artifact does not independently prove p-adic representation theory and does not "
            "claim independent discovery. It records the valid proof dependency chain and rejects the "
            "specific quantifier/support mistakes that made the prior LLM/OpenAI route incorrect."
        ),
    )
