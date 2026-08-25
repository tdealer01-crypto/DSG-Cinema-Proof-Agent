import pytest
from pydantic import ValidationError

from api_v1.improvement_proof import ImprovementEnvelope, verify_improvement_envelope


def envelope(**overrides):
    data = {
        "schemaVersion": "dsg-agentic-improvement-v1",
        "candidateId": "candidate-1",
        "goalId": "goal-1",
        "approvedPlanHash": "plan-hash",
        "targetRepository": "tdealer01-crypto/dsg-one-v1",
        "baselineCommit": "a" * 40,
        "candidateCommit": "b" * 40,
        "allowedPaths": ["lib/dsg/app-builder/**"],
        "baselineMetric": {"name": "success_rate", "value": 0.8, "direction": "HIGHER_IS_BETTER"},
        "candidateMetric": {"name": "success_rate", "value": 0.9, "direction": "HIGHER_IS_BETTER"},
        "constraintsPassed": True,
        "planAligned": True,
        "testsPassed": True,
        "buildPassed": True,
        "simulationHash": "sim-hash",
        "candidateAuthority": "SIMULATION_ONLY",
        "promotionAuthority": "DSG_CONTROL_PLANE",
        "selfPromotionAllowed": False,
        "requestedPromotion": "PR",
        "evidence": [
            {"kind": "commit", "uri": "git://candidate", "commitSha": "b" * 40},
            {"kind": "metric", "uri": "artifact://metric.json", "commitSha": "b" * 40},
            {"kind": "test_output", "uri": "artifact://tests.txt", "commitSha": "b" * 40},
        ],
    }
    data.update(overrides)
    return ImprovementEnvelope(**data)


def test_verifies_structural_binding_deterministically():
    first = verify_improvement_envelope(envelope())
    second = verify_improvement_envelope(envelope())
    assert first.verified is True
    assert first.verification == "VERIFIED_ENVELOPE_BINDING"
    assert first.proofHash == second.proofHash
    assert first.boundCandidateCommit == "b" * 40


def test_blocks_missing_required_evidence():
    proof = verify_improvement_envelope(envelope(evidence=[
        {"kind": "commit", "uri": "git://candidate", "commitSha": "b" * 40}
    ]))
    assert proof.verified is False
    assert any(item.startswith("EVIDENCE_KINDS_MISSING") for item in proof.failures)


def test_blocks_evidence_bound_to_unknown_commit():
    proof = verify_improvement_envelope(envelope(evidence=[
        {"kind": "commit", "uri": "git://candidate", "commitSha": "c" * 40},
        {"kind": "metric", "uri": "artifact://metric.json", "commitSha": "c" * 40},
        {"kind": "test_output", "uri": "artifact://tests.txt", "commitSha": "c" * 40},
    ]))
    assert proof.verified is False
    assert "NO_EVIDENCE_BOUND_TO_CANDIDATE_COMMIT" in proof.failures
    assert any(item.startswith("EVIDENCE_COMMIT_MISMATCH") for item in proof.failures)


def test_blocks_false_plan_test_or_build_claims():
    proof = verify_improvement_envelope(envelope(planAligned=False, testsPassed=False, buildPassed=False))
    assert proof.verified is False
    assert "PLAN_NOT_ALIGNED" in proof.failures
    assert "TESTS_NOT_PASSED" in proof.failures
    assert "BUILD_NOT_PASSED" in proof.failures


def test_schema_rejects_self_promotion_authority_and_unknown_fields():
    with pytest.raises(ValidationError):
        envelope(candidateAuthority="PROMOTION_AUTHORITY")
    with pytest.raises(ValidationError):
        envelope(selfPromotionAllowed=True)
    with pytest.raises(ValidationError):
        envelope(unexpected="forbidden")
