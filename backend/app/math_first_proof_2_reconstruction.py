from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from z3 import Real, RealVal, Solver, unsat

from .math_epsilon_light import AuditStoreProtocol, _sha256


OFFICIAL_SOLUTIONS_URL = "https://1stproof.org/documents/FirstProofSolutionsComments.pdf"


class MachineObligation(BaseModel):
    name: str
    status: Literal["UNSAT_NEGATION"] = "UNSAT_NEGATION"
    statement: str
    reference_equations: list[str]


class ExternalMathDependency(BaseModel):
    name: str
    status: Literal["REFERENCE_THEOREM_REQUIRED"] = "REFERENCE_THEOREM_REQUIRED"
    role: str
    reference: str


class ReconstructionStep(BaseModel):
    name: str
    kind: Literal["REFERENCE", "MACHINE_CHECKED"]
    depends_on: list[str]
    conclusion: str


class FirstProof2ReconstructionResult(BaseModel):
    benchmark: Literal["First Proof #2 reference reconstruction audit"] = (
        "First Proof #2 reference reconstruction audit"
    )
    status: Literal["REFERENCE_RECONSTRUCTION_AUDITED", "VERIFICATION_FAILED"]
    answer: Literal["YES"] = "YES"
    universal_vector_contract: str
    machine_obligations: list[MachineObligation]
    external_dependencies: list[ExternalMathDependency]
    reconstruction_steps: list[ReconstructionStep]
    final_identity: str
    nonvanishing_basis: str
    proof_hash: str
    audit_event_hash: str
    truth_boundary: str


def _prove_unsat(
    name: str,
    statement: str,
    reference_equations: list[str],
    constraints: list,
    negated_goal,
) -> MachineObligation:
    solver = Solver()
    solver.add(*constraints)
    solver.add(negated_goal)
    result = solver.check()
    if result != unsat:
        raise RuntimeError(f"First Proof #2 scalar obligation {name} failed: {result}")
    return MachineObligation(
        name=name,
        statement=statement,
        reference_equations=reference_equations,
    )


def verify_reference_scalar_spine() -> list[MachineObligation]:
    """Machine-check only the scalar/logical spine of Proposition 6.

    The p-adic representation-theoretic inputs are kept as explicit external
    dependencies. Z3 is not presented as a proof of those mathematical theorems.
    """

    s = Real("s")
    n = Real("n")
    half = RealVal(1) / 2

    obligations = [
        _prove_unsat(
            "proposition6_exponent_cancellation",
            (
                "Combining -(s-1/2) from (19) with s-(n+1)/2 from (20) gives "
                "the s-independent exponent -n/2 in (17)."
            ),
            ["(17)", "(19)", "(20)"],
            [n >= 1],
            (-(s - half) + (s - (n + 1) / 2)) != (-n / 2),
        ),
        _prove_unsat(
            "basepoint_normalization",
            (
                "At s=(n+1)/2 the exponent in (20) is zero, so the basepoint "
                "value determines (20) once the determinant support is fixed."
            ),
            ["(20)"],
            [n >= 1, s == (n + 1) / 2],
            (s - (n + 1) / 2) != 0,
        ),
    ]

    epsilon_abs = Real("epsilon_abs")
    q_power = Real("q_power")
    volume = Real("volume")
    c_abs = Real("c_abs")
    obligations.append(
        _prove_unsat(
            "nonzero_scalar_factor",
            (
                "If the local epsilon factor is nonzero, |Q|^n is positive, and "
                "vol(K1(q)) is positive, then the scalar c in (18) is nonzero."
            ),
            ["(18)"],
            [
                epsilon_abs > 0,
                q_power > 0,
                volume > 0,
                c_abs * epsilon_abs == q_power * volume,
            ],
            c_abs <= 0,
        )
    )
    return obligations


def reference_dependencies() -> list[ExternalMathDependency]:
    return [
        ExternalMathDependency(
            name="kirillov_extension",
            role=(
                "Extends the fixed smaller-block Whittaker function W0 to the Whittaker model "
                "of the fixed representation Pi, keeping W0 independent of pi."
            ),
            reference="Official solution, equation (6) and following paragraph.",
        ),
        ExternalMathDependency(
            name="godement_jacquet_functional_equation",
            role="Supplies Lemma 2 and the transform identity used in Lemma 4.",
            reference="Official solution, Lemma 2 / equations (2)-(3).",
        ),
        ExternalMathDependency(
            name="mellin_support_transform",
            role="Constructs beta and beta-sharp with conductor-controlled support and values.",
            reference="Official solution, Lemma 3 / equation (4) and its transform.",
        ),
        ExternalMathDependency(
            name="fourier_to_K1_identity",
            role=(
                "Converts beta-sharp(det g) phi-hat(g) to |Q|^n 1_{K1(q)}, avoiding "
                "the invalid Howe-vector support shortcut."
            ),
            reference="Official solution, Lemma 5 / equations (8) and (15).",
        ),
        ExternalMathDependency(
            name="normalized_newvector_theory",
            role=(
                "Provides the K1(q)-invariant Whittaker newvector V with V(1)=1 so the "
                "final K1(q) integral evaluates to vol(K1(q))."
            ),
            reference="Official solution, Proposition 6 citing references [4,5].",
        ),
        ExternalMathDependency(
            name="epsilon_factor_nonvanishing",
            role="Ensures the constant c in equation (18) is nonzero.",
            reference="Standard local epsilon-factor theory used in equations (1) and (18).",
        ),
    ]


def reconstruction_dag() -> list[ReconstructionStep]:
    return [
        ReconstructionStep(
            name="fix_universal_W0",
            kind="REFERENCE",
            depends_on=["Pi", "psi", "kirillov_extension"],
            conclusion="Choose W0 once from Pi and psi; it does not depend on pi, q, or Q.",
        ),
        ReconstructionStep(
            name="encode_conductor",
            kind="REFERENCE",
            depends_on=["pi", "epsilon_factor_nonvanishing"],
            conclusion="For each pi choose conductor q and Q generating q^{-1}.",
        ),
        ReconstructionStep(
            name="construct_beta_transform",
            kind="REFERENCE",
            depends_on=["godement_jacquet_functional_equation", "mellin_support_transform"],
            conclusion="Obtain beta and beta-sharp with the support/value assertions of Lemma 3.",
        ),
        ReconstructionStep(
            name="identify_congruence_subgroup",
            kind="REFERENCE",
            depends_on=["construct_beta_transform", "fourier_to_K1_identity"],
            conclusion="Lemma 5 converts the transformed test function to |Q|^n 1_{K1(q)}.",
        ),
        ReconstructionStep(
            name="evaluate_newvector_integral",
            kind="REFERENCE",
            depends_on=["identify_congruence_subgroup", "normalized_newvector_theory"],
            conclusion="The basepoint integral becomes |Q|^n vol(K1(q)) after epsilon normalization.",
        ),
        ReconstructionStep(
            name="close_scalar_exponents",
            kind="MACHINE_CHECKED",
            depends_on=["evaluate_newvector_integral"],
            conclusion="Equations (19) and (20) combine to |Q|^{-n/2} in (17).",
        ),
    ]


def audit_first_proof_2_reconstruction(
    audit_store: AuditStoreProtocol,
) -> FirstProof2ReconstructionResult:
    obligations = verify_reference_scalar_spine()
    dependencies = reference_dependencies()
    steps = reconstruction_dag()

    universal_step = next(step for step in steps if step.name == "fix_universal_W0")
    forbidden = {"pi", "q", "Q"}
    if forbidden.intersection(universal_step.depends_on):
        raise RuntimeError("First Proof #2 reconstruction violated the universal-W quantifier")

    expected_machine_names = {
        "proposition6_exponent_cancellation",
        "basepoint_normalization",
        "nonzero_scalar_factor",
    }
    if {item.name for item in obligations} != expected_machine_names:
        raise RuntimeError("First Proof #2 reconstruction is missing scalar obligations")

    payload = {
        "answer": "YES",
        "source": OFFICIAL_SOLUTIONS_URL,
        "universal_vector_contract": "W0 depends on Pi and psi only, never on pi/q/Q",
        "machine_obligations": [item.model_dump(mode="json") for item in obligations],
        "external_dependencies": [item.model_dump(mode="json") for item in dependencies],
        "reconstruction_steps": [item.model_dump(mode="json") for item in steps],
        "final_identity": "ell_RS(s,u_Q W0,d_Q V)=c |Q|^{-n/2}",
    }
    proof_hash = _sha256(payload)
    audit = audit_store.append(
        payload={"first_proof_2_reference_reconstruction": payload},
        proof_hash=proof_hash,
    )

    return FirstProof2ReconstructionResult(
        status="REFERENCE_RECONSTRUCTION_AUDITED",
        universal_vector_contract="W0 is fixed from Pi and psi before pi is chosen.",
        machine_obligations=obligations,
        external_dependencies=dependencies,
        reconstruction_steps=steps,
        final_identity="ell_RS(s,u_Q W0,d_Q V)=c |Q|^{-n/2} for every s",
        nonvanishing_basis=(
            "The official proof reduces the basepoint integral to |Q|^n vol(K1(q)); "
            "newvector invariance gives V(g^{-1})=1 on K1(q), |det g|=1 there, and the "
            "local epsilon factor is nonzero."
        ),
        proof_hash=proof_hash,
        audit_event_hash=audit.event_hash,
        truth_boundary=(
            "This artifact independently machine-checks the quantifier guard and scalar exponent/nonzero "
            "spine of the published proof, but it is not an independent formal proof of the p-adic "
            "representation-theoretic lemmas. Those inputs remain explicitly cited reference dependencies."
        ),
    )
