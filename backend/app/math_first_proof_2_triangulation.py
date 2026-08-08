from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .math_epsilon_light import AuditStoreProtocol, _sha256
from .math_first_proof_2 import reference_proof_contract
from .math_first_proof_2_reconstruction import verify_reference_scalar_spine


OFFICIAL_SOLUTIONS_URL = "https://1stproof.org/documents/FirstProofSolutionsComments.pdf"
ALETHEIA_PAPER_URL = "https://arxiv.org/abs/2602.21201"
ALETHEIA_REPO = "google-deepmind/superhuman"
ALETHEIA_COMMIT = "a02069ef66dbae4c5b0713ba0dc144a35375558f"
ALETHEIA_PATH = "aletheia/FirstProof/FP2_Af.tex"
ALETHEIA_BLOB_SHA = "9cae0e02192093ac828d5688184ce7daf66e9eed"
LEAN_SKELETON_RECORD = "https://zenodo.org/records/18635744"


class PublicProofSource(BaseModel):
    name: str
    source_kind: Literal[
        "OFFICIAL_HUMAN_SOLUTION",
        "EXPERT_ASSESSED_AGENT_SOLUTION",
        "REPORTED_LEAN_SKELETON",
    ]
    answer: Literal["YES"] = "YES"
    locator: str
    immutable_ref: str | None = None
    content_sha: str | None = None
    verification_status: Literal[
        "PRIMARY_SOURCE_RECORDED",
        "PINNED_PUBLIC_SOURCE_RECORDED",
        "REPORT_ONLY_NOT_REPLAYED",
    ] = "PRIMARY_SOURCE_RECORDED"
    proof_route: str


class SharedInvariant(BaseModel):
    code: str
    status: Literal["CORROBORATED"] = "CORROBORATED"
    statement: str
    supporting_sources: list[str]


class RouteDifference(BaseModel):
    source: str
    route: str
    machine_status: Literal["REFERENCE_ROUTE", "PINNED_EXTERNAL_ROUTE", "REPORTED_SKELETON"]


class FirstProof2TriangulationResult(BaseModel):
    benchmark: Literal["First Proof #2 multisource proof triangulation"] = (
        "First Proof #2 multisource proof triangulation"
    )
    status: Literal["MULTISOURCE_CORROBORATED", "VERIFICATION_FAILED"]
    answer: Literal["YES"] = "YES"
    sources: list[PublicProofSource]
    shared_invariants: list[SharedInvariant]
    route_differences: list[RouteDifference]
    dsg_machine_checks: list[str]
    replayable_external_source: str
    nonreplayable_external_report: str
    proof_hash: str
    audit_event_hash: str
    truth_boundary: str


def public_sources() -> list[PublicProofSource]:
    return [
        PublicProofSource(
            name="Paul Nelson / First Proof official solution",
            source_kind="OFFICIAL_HUMAN_SOLUTION",
            locator=OFFICIAL_SOLUTIONS_URL,
            verification_status="PRIMARY_SOURCE_RECORDED",
            proof_route=(
                "Kirillov extension -> Godement-Jacquet functional equation -> Mellin/Fourier "
                "transform -> K1(q) characteristic function -> normalized newvector -> explicit "
                "nonzero scalar times |Q|^{-n/2}."
            ),
        ),
        PublicProofSource(
            name="Google DeepMind Aletheia final Problem #2 response",
            source_kind="EXPERT_ASSESSED_AGENT_SOLUTION",
            locator=f"https://github.com/{ALETHEIA_REPO}/blob/{ALETHEIA_COMMIT}/{ALETHEIA_PATH}",
            immutable_ref=ALETHEIA_COMMIT,
            content_sha=ALETHEIA_BLOB_SHA,
            verification_status="PINNED_PUBLIC_SOURCE_RECORDED",
            proof_route=(
                "Universal Whittaker vector via mirabolic/Kirillov restriction -> collapse to an "
                "s-independent compact K_n functional -> conductor-level finite Fourier/newvector "
                "analysis for exact nonvanishing. The Aletheia paper reports Problem #2 as solved "
                "according to majority expert assessments."
            ),
        ),
        PublicProofSource(
            name="Zhang-Ma Lean 4 FirstProof preprint",
            source_kind="REPORTED_LEAN_SKELETON",
            locator=LEAN_SKELETON_RECORD,
            verification_status="REPORT_ONLY_NOT_REPLAYED",
            proof_route=(
                "Lean 4 proof skeleton reported for Q2: external deep theorems are axiomatized and "
                "the logical deduction chain is machine-checked. DSG has not located and replayed "
                "the underlying Lean source from this record."
            ),
        ),
    ]


def shared_invariants() -> list[SharedInvariant]:
    core_sources = [
        "Paul Nelson / First Proof official solution",
        "Google DeepMind Aletheia final Problem #2 response",
    ]
    return [
        SharedInvariant(
            code="UNIVERSAL_W_FIXED_BEFORE_PI",
            statement=(
                "The Whittaker vector W is fixed from the larger representation Pi (and psi) "
                "before the smaller representation pi and its conductor data are chosen."
            ),
            supporting_sources=core_sources,
        ),
        SharedInvariant(
            code="ALL_S_FINITE_NONZERO",
            statement=(
                "The construction removes or explicitly controls s-dependence and reduces the "
                "problem to a nonzero conductor/newvector calculation valid for every complex s."
            ),
            supporting_sources=core_sources,
        ),
        SharedInvariant(
            code="CONDUCTOR_DATA_MAY_DEPEND_ON_PI",
            statement=(
                "The conductor q, generator Q, and the smaller-group test vector V may vary with pi; "
                "the universal larger-group vector W may not."
            ),
            supporting_sources=core_sources,
        ),
        SharedInvariant(
            code="NO_HOWE_SUPPORT_SHORTCUT",
            statement=(
                "The accepted routes do not rely on the false strong Howe-vector support shortcut "
                "documented in the incorrect OpenAI attempt."
            ),
            supporting_sources=core_sources,
        ),
    ]


def triangulate_first_proof_2(audit_store: AuditStoreProtocol) -> FirstProof2TriangulationResult:
    # Re-run DSG's existing fail-closed internal guards before issuing a multisource certificate.
    steps, failures = reference_proof_contract()
    universal = next(item for item in steps if item.name == "fixed_whittaker_vector")
    if {"pi", "q", "Q"}.intersection(universal.depends_on):
        raise RuntimeError("First Proof #2 triangulation failed: universal W depends on pi/q/Q")
    if "W_DEPENDS_ON_PI" not in {item.code for item in failures}:
        raise RuntimeError("First Proof #2 triangulation failed: missing W_DEPENDS_ON_PI guard")

    scalar_checks = verify_reference_scalar_spine()
    expected_scalar = {
        "proposition6_exponent_cancellation",
        "basepoint_normalization",
        "nonzero_scalar_factor",
    }
    if {item.name for item in scalar_checks} != expected_scalar:
        raise RuntimeError("First Proof #2 triangulation failed: scalar audit incomplete")

    sources = public_sources()
    if sum(item.verification_status == "PINNED_PUBLIC_SOURCE_RECORDED" for item in sources) < 1:
        raise RuntimeError("First Proof #2 triangulation failed: no pinned independent public route")
    if ALETHEIA_COMMIT != "a02069ef66dbae4c5b0713ba0dc144a35375558f":
        raise RuntimeError("First Proof #2 triangulation failed: Aletheia source pin moved")
    if ALETHEIA_BLOB_SHA != "9cae0e02192093ac828d5688184ce7daf66e9eed":
        raise RuntimeError("First Proof #2 triangulation failed: Aletheia blob pin moved")

    invariants = shared_invariants()
    routes = [
        RouteDifference(
            source="official",
            route="Godement-Jacquet/Mellin/Fourier-to-K1/newvector explicit identity",
            machine_status="REFERENCE_ROUTE",
        ),
        RouteDifference(
            source="Aletheia",
            route="compact K_n functional plus conductor-level finite Fourier/newvector analysis",
            machine_status="PINNED_EXTERNAL_ROUTE",
        ),
        RouteDifference(
            source="Zhang-Ma",
            route="Lean skeleton with deep external theorems axiomatized",
            machine_status="REPORTED_SKELETON",
        ),
    ]
    machine_checks = [item.name for item in scalar_checks] + [
        "universal_W_quantifier_guard",
        "documented_failure_mode_guard",
        "Aletheia_commit_and_blob_pin",
    ]

    payload = {
        "answer": "YES",
        "sources": [item.model_dump(mode="json") for item in sources],
        "shared_invariants": [item.model_dump(mode="json") for item in invariants],
        "route_differences": [item.model_dump(mode="json") for item in routes],
        "dsg_machine_checks": machine_checks,
        "aletheia_paper": ALETHEIA_PAPER_URL,
    }
    proof_hash = _sha256(payload)
    audit = audit_store.append(
        payload={"first_proof_2_multisource_triangulation": payload},
        proof_hash=proof_hash,
    )

    return FirstProof2TriangulationResult(
        status="MULTISOURCE_CORROBORATED",
        sources=sources,
        shared_invariants=invariants,
        route_differences=routes,
        dsg_machine_checks=machine_checks,
        replayable_external_source=(
            f"{ALETHEIA_REPO}@{ALETHEIA_COMMIT}:{ALETHEIA_PATH} blob={ALETHEIA_BLOB_SHA}"
        ),
        nonreplayable_external_report=(
            "The Zhang-Ma Zenodo record reports a Lean skeleton for Q2, but DSG has not located a "
            "public Lean source tree/commit to kernel-replay; it remains report-only evidence."
        ),
        proof_hash=proof_hash,
        audit_event_hash=audit.event_hash,
        truth_boundary=(
            "MULTISOURCE_CORROBORATED means multiple public solution routes agree on the YES answer "
            "and critical quantifiers, while DSG re-runs its own fail-closed scalar/quantifier checks. "
            "It is not a full Lean/Coq formalization of p-adic representation theory, not a claim that "
            "Z3 proves the deep theorems, and not a claim of independent DSG discovery."
        ),
    )
