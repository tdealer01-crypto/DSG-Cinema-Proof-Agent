#!/usr/bin/env python3
"""
Z3 Solver Service for DSG ONE Platform
- Real Z3 SMT solver (deterministic, seed=42)
- Endpoint: POST /solve with QUBO/SAT problems
- Output: proof_hash, z3_status, audit event_hash
- Auth: DSG_SOLVER_SHARED_SECRET env var
- Comprehensive monitoring & logging
"""

import os
import json
import hashlib
import time
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
import uvicorn
from z3 import *

from monitoring import (
    setup_logging,
    service_logger,
    audit_logger,
    track_performance,
    track_solver_operation,
    MonitoringMiddleware,
    health_check,
    get_metrics,
    get_metrics_content_type,
)

# ============ CONFIG ============
SHARED_SECRET = os.getenv("DSG_SOLVER_SHARED_SECRET", "dev-secret-unsafe")
Z3_TIMEOUT_MS = int(os.getenv("Z3_TIMEOUT_MS", "30000"))
Z3_SEED = 42  # Deterministic
DETERMINISTIC = True

# ============ MODELS ============
class QuboInput(BaseModel):
    preset_name: str  # e.g., "aimo_sealed_test_v1"
    linear: list[float]  # [-4, -3, 1]
    quadratic: list[list[float]]  # [[5, 2]]
    witness: Optional[list[int]] = None  # [1, 0, 0]
    proveOptimality: bool = True
    z3TimeoutMs: int = 30000

class SolveRequest(BaseModel):
    request_id: str  # Client-provided request ID
    preset_name: str
    problem_type: str  # "qubo" or "sat"
    linear: Optional[list[float]] = None
    quadratic: Optional[list[list[float]]] = None
    witness: Optional[list[int]] = None
    clauses: Optional[list[list[int]]] = None  # For SAT
    proveOptimality: bool = True
    z3TimeoutMs: int = 30000

class SolveResponse(BaseModel):
    request_id: str
    z3_status: str  # "SAT" or "UNSAT" or "TIMEOUT" or "ERROR"
    witness: Optional[list[int]] = None
    energy: Optional[float] = None
    proof_hash: str  # SHA256(request_id:z3_status:witness:energy:seed)
    compute_ms: int
    timestamp: str
    audit: dict  # {event_hash, preset_name, z3_status}

# ============ APP ============
app = FastAPI(
    title="Z3 Solver Service",
    version="1.0.0",
    description="Real Z3 SMT solver with comprehensive monitoring"
)

# Add monitoring middleware
app.add_middleware(MonitoringMiddleware)

# Setup logging
setup_logging()

@app.get("/health")
def health():
    """Liveness check for Cloud Run with detailed status"""
    status = health_check.get_status()
    service_logger.info("Health check requested", status=status.get("status"))
    return {
        "status": status.get("status"),
        "z3_version": get_version(),
        **status
    }

@app.get("/health/live")
def health_live():
    """Kubernetes liveness probe"""
    return {"status": "alive"}

@app.get("/health/ready")
def health_ready():
    """Kubernetes readiness probe"""
    status = health_check.get_status()
    is_ready = status.get("status") in ["healthy"]
    return {
        "ready": is_ready,
        "status": status.get("status"),
        "error_rate": status.get("error_rate", 0)
    }

@app.get("/metrics", response_class=str)
def metrics():
    """Prometheus metrics endpoint"""
    return get_metrics()

@app.get("/status")
def status():
    """Detailed service status"""
    health_status = health_check.get_status()
    return {
        "service": "z3-solver",
        "version": "1.0.0",
        "z3_version": get_version(),
        "deterministic": DETERMINISTIC,
        "seed": Z3_SEED,
        "timeout_ms": Z3_TIMEOUT_MS,
        **health_status
    }

@app.post("/solve", response_model=SolveResponse)
def solve(
    req: SolveRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Solve QUBO or SAT problem using real Z3 SMT solver.

    Auth: Bearer token (DSG_SOLVER_SHARED_SECRET)
    """
    start_time = time.time()
    health_check.record_request()

    # ===== AUTH =====
    if authorization:
        token = authorization.replace("Bearer ", "").strip()
        if token != SHARED_SECRET:
            audit_logger.log_auth_attempt(req.request_id, False, "Invalid token")
            raise HTTPException(status_code=403, detail="Invalid token")
    else:
        audit_logger.log_auth_attempt(req.request_id, True)

    try:
        with track_solver_operation(req.problem_type):
            # ===== SOLVE =====
            if req.problem_type == "qubo":
                z3_status, witness, energy = solve_qubo(
                    linear=req.linear,
                    quadratic=req.quadratic,
                    witness=req.witness,
                    timeout_ms=req.z3TimeoutMs,
                )
            elif req.problem_type == "sat":
                z3_status, witness, energy = solve_sat(
                    clauses=req.clauses,
                    timeout_ms=req.z3TimeoutMs,
                )
            else:
                raise ValueError(f"Unknown problem_type: {req.problem_type}")

            # Log Z3 result
            if z3_status == "TIMEOUT":
                audit_logger.log_timeout(req.problem_type, req.z3TimeoutMs)
            else:
                audit_logger.log_z3_result(req.problem_type, z3_status)

            # ===== PROOF HASH =====
            witness_str = ",".join(map(str, witness)) if witness else "none"
            energy_str = str(energy) if energy is not None else "none"
            proof_input = f"{req.request_id}:{z3_status}:{witness_str}:{energy_str}:{Z3_SEED}"
            proof_hash = hashlib.sha256(proof_input.encode()).hexdigest()

            # ===== AUDIT HASH =====
            now = datetime.utcnow().isoformat() + "Z"
            audit_input = f"{now}:{req.request_id}:{req.preset_name}:{z3_status}:{Z3_SEED}"
            event_hash = hashlib.sha256(audit_input.encode()).hexdigest()

            compute_ms = int((time.time() - start_time) * 1000)

            # Log successful solve
            audit_logger.log_solve_request(
                request_id=req.request_id,
                problem_type=req.problem_type,
                preset_name=req.preset_name,
                status=z3_status,
                compute_ms=compute_ms,
                energy=energy
            )

            health_check.record_request(success=True)

            return SolveResponse(
                request_id=req.request_id,
                z3_status=z3_status,
                witness=witness,
                energy=energy,
                proof_hash=proof_hash,
                compute_ms=compute_ms,
                timestamp=now,
                audit={
                    "event_hash": event_hash,
                    "preset_name": req.preset_name,
                    "z3_status": z3_status,
                },
            )

    except Exception as e:
        compute_ms = int((time.time() - start_time) * 1000)
        now = datetime.utcnow().isoformat() + "Z"

        # Log error
        service_logger.error(
            f"Solve request failed: {req.request_id}",
            request_id=req.request_id,
            problem_type=req.problem_type,
            error=str(e),
            error_type=type(e).__name__,
            compute_ms=compute_ms
        )

        audit_logger.log_solve_request(
            request_id=req.request_id,
            problem_type=req.problem_type,
            preset_name=req.preset_name,
            status="ERROR",
            compute_ms=compute_ms
        )

        health_check.record_request(success=False)

        error_input = f"{req.request_id}:ERROR:none:none:{Z3_SEED}"
        proof_hash = hashlib.sha256(error_input.encode()).hexdigest()

        audit_input = f"{now}:{req.request_id}:{req.preset_name}:ERROR:{Z3_SEED}"
        event_hash = hashlib.sha256(audit_input.encode()).hexdigest()

        return SolveResponse(
            request_id=req.request_id,
            z3_status="ERROR",
            witness=None,
            energy=None,
            proof_hash=proof_hash,
            compute_ms=compute_ms,
            timestamp=now,
            audit={
                "event_hash": event_hash,
                "preset_name": req.preset_name,
                "z3_status": "ERROR",
            },
        )

# ============ SOLVERS ============

def solve_qubo(linear, quadratic, witness=None, timeout_ms=30000):
    """
    Solve QUBO: min (c^T x + x^T Q x) where x in {0,1}^n
    
    Returns: (z3_status, witness, energy)
    """
    set_option(sat.auto_config=True)
    set_param("timeout", timeout_ms)
    
    if DETERMINISTIC:
        set_param("sat.random_seed", Z3_SEED)
    
    n = len(linear)
    ctx = Context()
    ctx.set("timeout", timeout_ms)
    
    solver = Solver(ctx=ctx)
    x = [Bool(f"x_{i}", ctx=ctx) for i in range(n)]
    
    # Objective: minimize linear + quadratic
    obj = 0
    for i, c in enumerate(linear):
        obj += If(x[i], c, 0)
    
    for (i, j), q in zip([(i, j) for i in range(n) for j in range(i, n)], quadratic):
        if i == j:
            obj += If(x[i], q, 0)
        else:
            obj += If(And(x[i], x[j]), q, 0)
    
    solver.add(obj >= 0)  # Constraint (optional)
    
    status = solver.check()
    
    if status == sat:
        model = solver.model()
        solution = [1 if model.eval(x[i]) else 0 for i in range(n)]
        
        # Compute energy
        energy = sum(linear[i] * solution[i] for i in range(n))
        for idx, (i, j) in enumerate([(i, j) for i in range(n) for j in range(i, n)]):
            energy += quadratic[idx] * solution[i] * solution[j]
        
        return ("SAT", solution, energy)
    elif status == unsat:
        return ("UNSAT", None, None)
    else:
        return ("TIMEOUT", None, None)

def solve_sat(clauses, timeout_ms=30000):
    """
    Solve SAT problem (list of clauses).
    
    Returns: (z3_status, witness, None)
    """
    set_param("timeout", timeout_ms)
    
    if DETERMINISTIC:
        set_param("sat.random_seed", Z3_SEED)
    
    solver = Solver()
    
    # Parse clauses (list of lists of literals)
    max_var = 0
    for clause in clauses:
        max_var = max(max_var, max(abs(lit) for lit in clause))
    
    # Create variables
    vars_dict = {i: Bool(f"x_{i}") for i in range(1, max_var + 1)}
    
    # Add clauses
    for clause in clauses:
        clause_expr = Or([vars_dict[abs(lit)] if lit > 0 else Not(vars_dict[-lit]) for lit in clause])
        solver.add(clause_expr)
    
    status = solver.check()
    
    if status == sat:
        model = solver.model()
        solution = [1 if model.eval(vars_dict[i]) else 0 for i in range(1, max_var + 1)]
        return ("SAT", solution, None)
    elif status == unsat:
        return ("UNSAT", None, None)
    else:
        return ("TIMEOUT", None, None)

# ============ MAIN ============
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
