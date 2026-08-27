import base64
import hashlib
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from api_v1.github_actions_oidc import (
    AGENTIC_IMPROVEMENT_AUDIENCE,
    GITHUB_OIDC_ISSUER,
    OidcVerificationError,
    verify_github_actions_oidc,
)
from api_v1.improvement_attestation import RawEvidenceArtifact, verify_raw_improvement_evidence
from api_v1.improvement_proof import ImprovementEnvelope


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def int_b64url(value: int) -> str:
    size = max(1, (value.bit_length() + 7) // 8)
    return b64url(value.to_bytes(size, "big"))


PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_NUMBERS = PRIVATE_KEY.public_key().public_numbers()
JWKS = {
    "keys": [{
        "kty": "RSA",
        "kid": "test-key",
        "alg": "RS256",
        "use": "sig",
        "n": int_b64url(PUBLIC_NUMBERS.n),
        "e": int_b64url(PUBLIC_NUMBERS.e),
    }]
}


def token(**overrides) -> str:
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT", "kid": "test-key"}
    claims = {
        "iss": GITHUB_OIDC_ISSUER,
        "aud": AGENTIC_IMPROVEMENT_AUDIENCE,
        "sub": "repo:tdealer01-crypto/dsg-agi-simulation:ref:refs/heads/master",
        "repository": "tdealer01-crypto/dsg-agi-simulation",
        "repository_id": "1263153975",
        "repository_owner_id": "260597462",
        "repository_visibility": "private",
        "ref": "refs/heads/master",
        "sha": "a" * 40,
        "workflow_ref": "tdealer01-crypto/dsg-agi-simulation/.github/workflows/governed-self-evolution.yml@refs/heads/master",
        "workflow_sha": "a" * 40,
        "runner_environment": "github-hosted",
        "run_id": "4242",
        "run_attempt": "1",
        "event_name": "workflow_dispatch",
        "actor": "tdealer01-crypto",
        "iat": now,
        "nbf": now - 5,
        "exp": now + 600,
    }
    claims.update(overrides)
    encoded_header = b64url(json.dumps(header, sort_keys=True, separators=(",", ":")).encode())
    encoded_claims = b64url(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    signature = PRIVATE_KEY.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{encoded_header}.{encoded_claims}.{b64url(signature)}"


def raw_fixture():
    metric = json.dumps({
        "schemaVersion": "dsg-evolution-result-v1",
        "previousBestFitness": 0.8,
        "newBestFitness": 0.9,
        "improvement": 0.1,
        "verificationPassed": True,
        "simulationHash": "sim-hash",
    }, sort_keys=True, separators=(",", ":")).encode()
    tests = b"53 tests passed\n"
    build = b"build completed successfully\n"
    raw = {"metric": metric, "test_output": tests, "build_output": build}
    digests = {kind: hashlib.sha256(content).hexdigest() for kind, content in raw.items()}
    return raw, digests


def envelope_and_artifacts():
    raw, digests = raw_fixture()
    candidate = "b" * 40
    envelope = ImprovementEnvelope(**{
        "schemaVersion": "dsg-agentic-improvement-v1",
        "candidateId": "candidate-4242",
        "goalId": "goal-self-evolution",
        "approvedPlanHash": "plan-hash",
        "targetRepository": "tdealer01-crypto/dsg-agi-simulation",
        "baselineCommit": "a" * 40,
        "candidateCommit": candidate,
        "allowedPaths": ["data/simulation-input.json"],
        "baselineMetric": {"name": "fitness", "value": 0.8, "direction": "HIGHER_IS_BETTER"},
        "candidateMetric": {"name": "fitness", "value": 0.9, "direction": "HIGHER_IS_BETTER"},
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
            {"kind": "commit", "uri": f"git://tdealer01-crypto/dsg-agi-simulation@{candidate}", "repository": "tdealer01-crypto/dsg-agi-simulation", "commitSha": candidate},
            {"kind": "candidate", "uri": "simulation://candidate-4242", "repository": "tdealer01-crypto/dsg-agi-simulation", "commitSha": candidate},
            {"kind": "metric", "uri": "artifact://github-actions/4242/evolution-result.json", "sha256": digests["metric"], "repository": "tdealer01-crypto/dsg-agi-simulation", "commitSha": candidate},
            {"kind": "test_output", "uri": "artifact://github-actions/4242/candidate-tests.txt", "sha256": digests["test_output"], "repository": "tdealer01-crypto/dsg-agi-simulation", "commitSha": candidate},
            {"kind": "build_output", "uri": "artifact://github-actions/4242/candidate-build.txt", "sha256": digests["build_output"], "repository": "tdealer01-crypto/dsg-agi-simulation", "commitSha": candidate},
        ],
    })
    artifacts = [
        RawEvidenceArtifact(
            kind=kind,
            commitSha=candidate,
            sha256=digests[kind],
            contentBase64=base64.b64encode(raw[kind]).decode("ascii"),
        )
        for kind in ("metric", "test_output", "build_output")
    ]
    return envelope, artifacts


def test_oidc_and_raw_evidence_verify_deterministically():
    identity = verify_github_actions_oidc(token(), JWKS)
    envelope, artifacts = envelope_and_artifacts()
    first = verify_raw_improvement_evidence(envelope, artifacts, identity)
    second = verify_raw_improvement_evidence(envelope, artifacts, identity)
    assert identity.workflowSha == "a" * 40
    assert identity.runnerEnvironment == "github-hosted"
    assert first.verified is True
    assert first.rawEvidenceVerified is True
    assert first.verification == "VERIFIED_RAW_EVIDENCE"
    assert first.proofHash == second.proofHash
    assert first.boundCandidateCommit == "b" * 40
    assert set(first.artifactDigests) == {"metric", "test_output", "build_output"}


def test_oidc_rejects_wrong_audience_and_repository_identity():
    with pytest.raises(OidcVerificationError, match="OIDC_AUDIENCE_MISMATCH"):
        verify_github_actions_oidc(token(aud="wrong-audience"), JWKS)
    with pytest.raises(OidcVerificationError, match="OIDC_REPOSITORY_ID_MISMATCH"):
        verify_github_actions_oidc(token(repository_id="999"), JWKS)
    with pytest.raises(OidcVerificationError, match="OIDC_REPOSITORY_OWNER_ID_MISMATCH"):
        verify_github_actions_oidc(token(repository_owner_id="999"), JWKS)


def test_oidc_rejects_movable_or_untrusted_execution_identity():
    with pytest.raises(OidcVerificationError, match="OIDC_WORKFLOW_SHA_MISMATCH"):
        verify_github_actions_oidc(token(workflow_sha="c" * 40), JWKS)
    with pytest.raises(OidcVerificationError, match="OIDC_RUNNER_ENVIRONMENT_NOT_ALLOWED"):
        verify_github_actions_oidc(token(runner_environment="self-hosted"), JWKS)
    with pytest.raises(OidcVerificationError, match="OIDC_EVENT_NOT_ALLOWED"):
        verify_github_actions_oidc(token(event_name="pull_request"), JWKS)


def test_raw_evidence_blocks_tampered_bytes():
    identity = verify_github_actions_oidc(token(), JWKS)
    envelope, artifacts = envelope_and_artifacts()
    artifacts[1] = artifacts[1].model_copy(update={
        "contentBase64": base64.b64encode(b"tampered test output\n").decode("ascii")
    })
    proof = verify_raw_improvement_evidence(envelope, artifacts, identity)
    assert proof.verified is False
    assert proof.rawEvidenceVerified is False
    assert "RAW_ARTIFACT_DIGEST_MISMATCH:test_output" in proof.failures


def test_raw_metric_must_match_envelope_values():
    identity = verify_github_actions_oidc(token(), JWKS)
    envelope, artifacts = envelope_and_artifacts()
    raw_metric = json.dumps({
        "previousBestFitness": 0.8,
        "newBestFitness": 9.9,
        "verificationPassed": True,
        "simulationHash": "sim-hash",
    }, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(raw_metric).hexdigest()
    metric_ref = next(item for item in envelope.evidence if item.kind == "metric")
    metric_ref.sha256 = digest
    artifacts[0] = artifacts[0].model_copy(update={
        "sha256": digest,
        "contentBase64": base64.b64encode(raw_metric).decode("ascii"),
    })
    proof = verify_raw_improvement_evidence(envelope, artifacts, identity)
    assert proof.verified is False
    assert "RAW_METRIC_CANDIDATE_MISMATCH" in proof.failures
