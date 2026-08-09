from __future__ import annotations

from app.audit import AuditStore
from app.math_aimo_exact import AimoExactEnergyRequest, _sha256_json, verify_aimo_exact_energy


def _store(tmp_path) -> AuditStore:
    store = AuditStore(str(tmp_path / "aimo-audit.sqlite3"))
    store.initialize()
    return store


def _problem() -> dict:
    return {
        "problemId": "sealed-qubo-1",
        "statement": "Minimize the supplied finite QUBO encoding.",
        "domain": "combinatorics",
        "constraints": {},
    }


def test_qubo_global_optimum_passes_with_exact_and_z3_proof(tmp_path) -> None:
    problem = _problem()
    encoding = {
        "kind": "qubo-v1",
        "variableCount": 2,
        "linear": [{"i": 0, "weight": 1}, {"i": 1, "weight": 2}],
        "quadratic": [{"i": 0, "j": 1, "weight": 3}],
        "objective": "min",
    }
    request = AimoExactEnergyRequest.model_validate(
        {
            "schemaVersion": "dsg-aimo-exact-energy-v1",
            "problemId": "sealed-qubo-1",
            "problem": problem,
            "problemHash": _sha256_json({"schemaVersion": "dsg-aimo-v1", "problem": problem}),
            "encodingHash": _sha256_json(encoding),
            "encoding": encoding,
            "witness": {
                "kind": "qubo-v1",
                "assignmentIndex": "0",
                "variableCount": 2,
                "energy": "0",
                "bits": [0, 0],
            },
            "proveOptimality": True,
        }
    )

    result = verify_aimo_exact_energy(request, _store(tmp_path))

    assert result.verdict == "PASS"
    assert result.certificate_level == "VERIFIED_GLOBAL_OPTIMUM"
    assert result.proof_complete is True
    assert result.exact_energy_match is True
    assert result.z3_witness_status == "UNSAT_NEGATION"
    assert result.z3_optimality_status == "UNSAT_NO_BETTER_ASSIGNMENT"
    assert result.counterexample is None


def test_suboptimal_qubo_candidate_is_blocked_with_counterexample(tmp_path) -> None:
    problem = _problem()
    encoding = {
        "kind": "qubo-v1",
        "variableCount": 2,
        "linear": [{"i": 0, "weight": 1}, {"i": 1, "weight": 2}],
        "objective": "min",
    }
    request = AimoExactEnergyRequest.model_validate(
        {
            "schemaVersion": "dsg-aimo-exact-energy-v1",
            "problem": problem,
            "problemHash": _sha256_json({"schemaVersion": "dsg-aimo-v1", "problem": problem}),
            "encodingHash": _sha256_json(encoding),
            "encoding": encoding,
            "witness": {
                "kind": "qubo-v1",
                "assignmentIndex": "1",
                "variableCount": 2,
                "energy": "1",
                "bits": [1, 0],
            },
            "proveOptimality": True,
        }
    )

    result = verify_aimo_exact_energy(request, _store(tmp_path))

    assert result.verdict == "BLOCKED"
    assert result.proof_complete is False
    assert result.z3_optimality_status == "SAT_BETTER_ASSIGNMENT_FOUND"
    assert result.counterexample is not None
    assert int(result.counterexample.energy) < 1


def test_ising_global_optimum_passes(tmp_path) -> None:
    problem = {
        "problemId": "sealed-ising-1",
        "statement": "Minimize the supplied finite Ising encoding.",
        "constraints": {},
    }
    encoding = {
        "kind": "ising-v1",
        "variableCount": 2,
        "h": [{"i": 0, "weight": 1}, {"i": 1, "weight": 1}],
        "j": [{"i": 0, "j": 1, "weight": -1}],
        "objective": "min",
    }
    request = AimoExactEnergyRequest.model_validate(
        {
            "schemaVersion": "dsg-aimo-exact-energy-v1",
            "problem": problem,
            "problemHash": _sha256_json({"schemaVersion": "dsg-aimo-v1", "problem": problem}),
            "encodingHash": _sha256_json(encoding),
            "encoding": encoding,
            "witness": {
                "kind": "ising-v1",
                "assignmentIndex": "0",
                "variableCount": 2,
                "energy": "-3",
                "spins": [-1, -1],
            },
            "proveOptimality": True,
        }
    )

    result = verify_aimo_exact_energy(request, _store(tmp_path))

    assert result.verdict == "PASS"
    assert result.recomputed_energy == "-3"
    assert result.z3_optimality_status == "UNSAT_NO_BETTER_ASSIGNMENT"


def test_wrong_problem_hash_fails_closed(tmp_path) -> None:
    problem = _problem()
    encoding = {"kind": "qubo-v1", "variableCount": 1, "linear": []}
    request = AimoExactEnergyRequest.model_validate(
        {
            "schemaVersion": "dsg-aimo-exact-energy-v1",
            "problem": problem,
            "problemHash": "sha256:" + "0" * 64,
            "encodingHash": _sha256_json(encoding),
            "encoding": encoding,
            "witness": {
                "kind": "qubo-v1",
                "assignmentIndex": "0",
                "variableCount": 1,
                "energy": "0",
                "bits": [0],
            },
            "proveOptimality": True,
        }
    )

    result = verify_aimo_exact_energy(request, _store(tmp_path))

    assert result.verdict == "BLOCKED"
    assert result.problem_hash_valid is False
    assert result.proof_complete is False


def test_verified_witness_without_optimality_stays_review(tmp_path) -> None:
    problem = _problem()
    encoding = {"kind": "qubo-v1", "variableCount": 1, "linear": [{"i": 0, "weight": 1}]}
    request = AimoExactEnergyRequest.model_validate(
        {
            "schemaVersion": "dsg-aimo-exact-energy-v1",
            "problem": problem,
            "problemHash": _sha256_json({"schemaVersion": "dsg-aimo-v1", "problem": problem}),
            "encodingHash": _sha256_json(encoding),
            "encoding": encoding,
            "witness": {
                "kind": "qubo-v1",
                "assignmentIndex": "0",
                "variableCount": 1,
                "energy": "0",
                "bits": [0],
            },
            "proveOptimality": False,
        }
    )

    result = verify_aimo_exact_energy(request, _store(tmp_path))

    assert result.verdict == "REVIEW"
    assert result.certificate_level == "VERIFIED_WITNESS"
    assert result.proof_complete is False
