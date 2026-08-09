from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator
from z3 import And, Bool, BoolVal, If, IntVal, Solver, Sum, get_version_string, is_true, sat, unsat

from .models import AuditChainProof

_INT_RE = re.compile(r"^-?\d+$")
MAX_VARIABLES = 62

IntegerLike = StrictInt | str


def _parse_int(value: IntegerLike, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer, not bool")
    if isinstance(value, int):
        return value
    if not _INT_RE.fullmatch(value):
        raise ValueError(f"{field} must be a decimal integer string")
    return int(value)


def _validate_integer_like(value: IntegerLike, field: str) -> IntegerLike:
    _parse_int(value, field)
    return value


def _stable_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_json(payload: Any) -> str:
    digest = hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


class AimoLinearTerm(BaseModel):
    i: int = Field(ge=0)
    weight: IntegerLike

    @field_validator("weight")
    @classmethod
    def validate_weight(cls, value: IntegerLike) -> IntegerLike:
        return _validate_integer_like(value, "weight")


class AimoQuadraticTerm(BaseModel):
    i: int = Field(ge=0)
    j: int = Field(ge=0)
    weight: IntegerLike

    @field_validator("weight")
    @classmethod
    def validate_weight(cls, value: IntegerLike) -> IntegerLike:
        return _validate_integer_like(value, "weight")


class AimoQuboEncoding(BaseModel):
    kind: Literal["qubo-v1"]
    variableCount: int = Field(ge=1, le=MAX_VARIABLES)
    constant: IntegerLike = 0
    linear: list[AimoLinearTerm] = Field(default_factory=list)
    quadratic: list[AimoQuadraticTerm] = Field(default_factory=list)
    objective: Literal["min"] = "min"

    @field_validator("constant")
    @classmethod
    def validate_constant(cls, value: IntegerLike) -> IntegerLike:
        return _validate_integer_like(value, "constant")

    @model_validator(mode="after")
    def validate_term_indexes(self) -> "AimoQuboEncoding":
        for term in self.linear:
            if term.i >= self.variableCount:
                raise ValueError(f"linear term index out of range: {term.i}")
        for term in self.quadratic:
            if term.i >= self.variableCount or term.j >= self.variableCount:
                raise ValueError(f"quadratic term index out of range: {term.i},{term.j}")
        return self


class AimoIsingEncoding(BaseModel):
    kind: Literal["ising-v1"]
    variableCount: int = Field(ge=1, le=MAX_VARIABLES)
    constant: IntegerLike = 0
    h: list[AimoLinearTerm] = Field(default_factory=list)
    j: list[AimoQuadraticTerm] = Field(default_factory=list)
    objective: Literal["min"] = "min"

    @field_validator("constant")
    @classmethod
    def validate_constant(cls, value: IntegerLike) -> IntegerLike:
        return _validate_integer_like(value, "constant")

    @model_validator(mode="after")
    def validate_term_indexes(self) -> "AimoIsingEncoding":
        for term in self.h:
            if term.i >= self.variableCount:
                raise ValueError(f"h term index out of range: {term.i}")
        for term in self.j:
            if term.i >= self.variableCount or term.j >= self.variableCount:
                raise ValueError(f"j term index out of range: {term.i},{term.j}")
        return self


AimoEncoding = Annotated[AimoQuboEncoding | AimoIsingEncoding, Field(discriminator="kind")]


class AimoEnergyWitness(BaseModel):
    kind: Literal["qubo-v1", "ising-v1"]
    assignmentIndex: str = Field(pattern=r"^\d+$")
    variableCount: int = Field(ge=1, le=MAX_VARIABLES)
    energy: str = Field(pattern=r"^-?\d+$")
    bits: list[Literal[0, 1]] | None = None
    spins: list[Literal[-1, 1]] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "AimoEnergyWitness":
        if self.kind == "qubo-v1":
            if self.bits is None or self.spins is not None:
                raise ValueError("qubo-v1 witness requires bits and forbids spins")
            if len(self.bits) != self.variableCount:
                raise ValueError("bits length must equal variableCount")
        else:
            if self.spins is None or self.bits is not None:
                raise ValueError("ising-v1 witness requires spins and forbids bits")
            if len(self.spins) != self.variableCount:
                raise ValueError("spins length must equal variableCount")
        if int(self.assignmentIndex) >= (1 << self.variableCount):
            raise ValueError("assignmentIndex is outside the encoded search space")
        return self


class AimoExactEnergyRequest(BaseModel):
    schemaVersion: Literal["dsg-aimo-exact-energy-v1"]
    problemId: str | None = Field(default=None, max_length=300)
    problem: dict[str, Any]
    problemHash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    encodingHash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    encoding: AimoEncoding
    witness: AimoEnergyWitness
    proveOptimality: bool = True
    z3TimeoutMs: int = Field(default=30_000, ge=1, le=120_000)

    @model_validator(mode="after")
    def validate_cross_fields(self) -> "AimoExactEnergyRequest":
        if self.encoding.kind != self.witness.kind:
            raise ValueError("encoding kind and witness kind must match")
        if self.encoding.variableCount != self.witness.variableCount:
            raise ValueError("encoding variableCount and witness variableCount must match")
        statement = self.problem.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError("problem.statement is required")
        return self


class AimoExactEnergyResult(BaseModel):
    schema_version: Literal["dsg-aimo-exact-energy-certificate-v1"] = "dsg-aimo-exact-energy-certificate-v1"
    verdict: Literal["PASS", "REVIEW", "BLOCKED"]
    certificate_level: Literal["VERIFIED_GLOBAL_OPTIMUM", "VERIFIED_WITNESS", "REVIEW", "BLOCKED"]
    proof_complete: bool
    problem_hash_valid: bool
    encoding_hash_valid: bool
    assignment_index_valid: bool
    exact_energy_match: bool
    claimed_energy: str
    recomputed_energy: str
    z3_witness_status: Literal["UNSAT_NEGATION", "SAT_CONTRADICTION", "UNKNOWN"]
    z3_optimality_status: Literal[
        "UNSAT_NO_BETTER_ASSIGNMENT",
        "SAT_BETTER_ASSIGNMENT_FOUND",
        "UNKNOWN",
        "NOT_REQUESTED",
    ]
    counterexample: AimoEnergyWitness | None = None
    solver_name: Literal["Z3"] = "Z3"
    solver_version: str
    proof_hash: str
    truth_boundary: str
    next_action: str | None = None
    audit: AuditChainProof


def _encoding_payload(encoding: AimoEncoding) -> dict[str, Any]:
    return encoding.model_dump(mode="json", exclude_unset=True, exclude_none=True)


def _expected_problem_hash(problem: dict[str, Any]) -> str:
    return _sha256_json({"schemaVersion": "dsg-aimo-v1", "problem": problem})


def _expected_encoding_hash(encoding: AimoEncoding) -> str:
    return _sha256_json(_encoding_payload(encoding))


def _assignment_from_witness(witness: AimoEnergyWitness) -> list[int]:
    if witness.kind == "qubo-v1":
        assert witness.bits is not None
        return [int(value) for value in witness.bits]
    assert witness.spins is not None
    return [int(value) for value in witness.spins]


def _assignment_index(kind: str, values: list[int]) -> int:
    if kind == "qubo-v1":
        return sum(value << index for index, value in enumerate(values))
    return sum((1 if value == 1 else 0) << index for index, value in enumerate(values))


def _compute_energy(encoding: AimoEncoding, values: list[int]) -> int:
    energy = _parse_int(encoding.constant, "constant")
    if encoding.kind == "qubo-v1":
        for term in encoding.linear:
            energy += _parse_int(term.weight, f"linear[{term.i}]") * values[term.i]
        for term in encoding.quadratic:
            energy += _parse_int(term.weight, f"quadratic[{term.i},{term.j}]") * values[term.i] * values[term.j]
    else:
        for term in encoding.h:
            energy += _parse_int(term.weight, f"h[{term.i}]") * values[term.i]
        for term in encoding.j:
            energy += _parse_int(term.weight, f"j[{term.i},{term.j}]") * values[term.i] * values[term.j]
    return energy


def _z3_energy_expression(encoding: AimoEncoding, variables: list[Any]) -> Any:
    terms: list[Any] = [IntVal(_parse_int(encoding.constant, "constant"))]
    if encoding.kind == "qubo-v1":
        for term in encoding.linear:
            weight = _parse_int(term.weight, f"linear[{term.i}]")
            terms.append(If(variables[term.i], weight, 0))
        for term in encoding.quadratic:
            weight = _parse_int(term.weight, f"quadratic[{term.i},{term.j}]")
            terms.append(If(And(variables[term.i], variables[term.j]), weight, 0))
    else:
        for term in encoding.h:
            weight = _parse_int(term.weight, f"h[{term.i}]")
            terms.append(If(variables[term.i], weight, -weight))
        for term in encoding.j:
            weight = _parse_int(term.weight, f"j[{term.i},{term.j}]")
            terms.append(If(variables[term.i] == variables[term.j], weight, -weight))
    return Sum(*terms)


def _model_counterexample(encoding: AimoEncoding, variables: list[Any], model: Any) -> AimoEnergyWitness:
    bits = [1 if is_true(model.eval(variable, model_completion=True)) else 0 for variable in variables]
    if encoding.kind == "qubo-v1":
        values = bits
        witness_bits: list[Literal[0, 1]] = [0 if value == 0 else 1 for value in bits]
        return AimoEnergyWitness(
            kind="qubo-v1",
            assignmentIndex=str(_assignment_index("qubo-v1", values)),
            variableCount=encoding.variableCount,
            energy=str(_compute_energy(encoding, values)),
            bits=witness_bits,
        )

    spins_raw = [1 if value == 1 else -1 for value in bits]
    witness_spins: list[Literal[-1, 1]] = [-1 if value == -1 else 1 for value in spins_raw]
    return AimoEnergyWitness(
        kind="ising-v1",
        assignmentIndex=str(_assignment_index("ising-v1", spins_raw)),
        variableCount=encoding.variableCount,
        energy=str(_compute_energy(encoding, spins_raw)),
        spins=witness_spins,
    )


def verify_aimo_exact_energy(request: AimoExactEnergyRequest, audit_store: Any) -> AimoExactEnergyResult:
    problem_hash_valid = _expected_problem_hash(request.problem) == request.problemHash
    encoding_hash_valid = _expected_encoding_hash(request.encoding) == request.encodingHash

    values = _assignment_from_witness(request.witness)
    recomputed_index = _assignment_index(request.witness.kind, values)
    assignment_index_valid = recomputed_index == int(request.witness.assignmentIndex)

    recomputed_energy = _compute_energy(request.encoding, values)
    claimed_energy = int(request.witness.energy)
    exact_energy_match = recomputed_energy == claimed_energy

    variables = [Bool(f"aimo_{request.witness.kind}_{index}") for index in range(request.encoding.variableCount)]
    energy_expression = _z3_energy_expression(request.encoding, variables)

    witness_solver = Solver()
    witness_solver.set(timeout=request.z3TimeoutMs)
    for variable, value in zip(variables, values):
        witness_solver.add(variable == BoolVal(value == 1))
    witness_solver.add(energy_expression != claimed_energy)
    witness_check = witness_solver.check()
    if witness_check == unsat:
        z3_witness_status: Literal["UNSAT_NEGATION", "SAT_CONTRADICTION", "UNKNOWN"] = "UNSAT_NEGATION"
    elif witness_check == sat:
        z3_witness_status = "SAT_CONTRADICTION"
    else:
        z3_witness_status = "UNKNOWN"

    base_valid = (
        problem_hash_valid
        and encoding_hash_valid
        and assignment_index_valid
        and exact_energy_match
        and z3_witness_status == "UNSAT_NEGATION"
    )

    counterexample: AimoEnergyWitness | None = None
    if request.proveOptimality and base_valid:
        optimality_solver = Solver()
        optimality_solver.set(timeout=request.z3TimeoutMs)
        optimality_solver.add(energy_expression < claimed_energy)
        optimality_check = optimality_solver.check()
        if optimality_check == unsat:
            z3_optimality_status: Literal[
                "UNSAT_NO_BETTER_ASSIGNMENT", "SAT_BETTER_ASSIGNMENT_FOUND", "UNKNOWN", "NOT_REQUESTED"
            ] = "UNSAT_NO_BETTER_ASSIGNMENT"
        elif optimality_check == sat:
            z3_optimality_status = "SAT_BETTER_ASSIGNMENT_FOUND"
            counterexample = _model_counterexample(request.encoding, variables, optimality_solver.model())
        else:
            z3_optimality_status = "UNKNOWN"
    else:
        z3_optimality_status = "NOT_REQUESTED"

    if not base_valid:
        verdict: Literal["PASS", "REVIEW", "BLOCKED"] = "BLOCKED"
        certificate_level: Literal["VERIFIED_GLOBAL_OPTIMUM", "VERIFIED_WITNESS", "REVIEW", "BLOCKED"] = "BLOCKED"
        proof_complete = False
        next_action = "Fix the problem/encoding hash, assignment index, exact energy, or witness contradiction before retrying."
    elif not request.proveOptimality:
        verdict = "REVIEW"
        certificate_level = "VERIFIED_WITNESS"
        proof_complete = False
        next_action = "Retry with proveOptimality=true for a final competition truth-gate certificate."
    elif z3_optimality_status == "UNSAT_NO_BETTER_ASSIGNMENT":
        verdict = "PASS"
        certificate_level = "VERIFIED_GLOBAL_OPTIMUM"
        proof_complete = True
        next_action = None
    elif z3_optimality_status == "SAT_BETTER_ASSIGNMENT_FOUND":
        verdict = "BLOCKED"
        certificate_level = "BLOCKED"
        proof_complete = False
        next_action = "Return the counterexample to deterministic search; the submitted candidate is not globally optimal."
    else:
        verdict = "REVIEW"
        certificate_level = "REVIEW"
        proof_complete = False
        next_action = "Increase the Z3 timeout or use an independent optimality certificate; UNKNOWN cannot PASS."

    proof_payload = {
        "schema_version": "dsg-aimo-exact-energy-certificate-v1",
        "request": request.model_dump(mode="json", exclude_none=True),
        "checks": {
            "problem_hash_valid": problem_hash_valid,
            "encoding_hash_valid": encoding_hash_valid,
            "assignment_index_valid": assignment_index_valid,
            "exact_energy_match": exact_energy_match,
            "recomputed_energy": str(recomputed_energy),
            "z3_witness_status": z3_witness_status,
            "z3_optimality_status": z3_optimality_status,
            "counterexample": counterexample.model_dump(mode="json") if counterexample else None,
        },
        "verdict": verdict,
        "certificate_level": certificate_level,
        "proof_complete": proof_complete,
        "solver_version": get_version_string(),
    }
    proof_hash = _sha256_json(proof_payload)
    audit = audit_store.append(proof_payload, proof_hash)

    return AimoExactEnergyResult(
        verdict=verdict,
        certificate_level=certificate_level,
        proof_complete=proof_complete,
        problem_hash_valid=problem_hash_valid,
        encoding_hash_valid=encoding_hash_valid,
        assignment_index_valid=assignment_index_valid,
        exact_energy_match=exact_energy_match,
        claimed_energy=str(claimed_energy),
        recomputed_energy=str(recomputed_energy),
        z3_witness_status=z3_witness_status,
        z3_optimality_status=z3_optimality_status,
        counterexample=counterexample,
        solver_version=get_version_string(),
        proof_hash=proof_hash,
        truth_boundary=(
            "PASS proves the submitted finite integer QUBO/Ising witness is bound to the supplied problem and encoding hashes, "
            "has the exact recomputed energy, and that Z3 found the existence of any strictly lower-energy assignment UNSAT. "
            "This is an optimality certificate for the supplied finite encoding only; it does not by itself prove that the encoding "
            "faithfully represents every semantic requirement of the original natural-language olympiad problem."
        ),
        next_action=next_action,
        audit=audit,
    )
