from __future__ import annotations

from fastapi import APIRouter, FastAPI

# Compliance readiness is a management/evidence surface, not part of the exact
# independent-verification OpenAPI contract under /api/v1.
router = APIRouter(prefix="/compliance", tags=["compliance"])

_ITEMS = (
    {
        "id": 1,
        "title": "General description and intended purpose",
        "status": "COVERED",
        "evidence": ["README.md", "docs/API_V1_CONTRACT.md", "docs/compliance/classification.md"],
    },
    {
        "id": 2,
        "title": "Version and update history",
        "status": "COVERED",
        "evidence": ["git history", ".github/workflows/deploy-cinema-production.yml"],
    },
    {
        "id": 3,
        "title": "Architecture and technical specifications",
        "status": "COVERED",
        "evidence": ["api_v1", "openapi/dsg-one-v1.yaml", "z3_main.py"],
    },
    {
        "id": 4,
        "title": "Monitoring, functioning, and control mechanisms",
        "status": "COVERED",
        "evidence": ["/health", "/api/v1/status", "preflight/evidence/proof records"],
    },
    {
        "id": 5,
        "title": "Input, output, and data specifications",
        "status": "PARTIAL",
        "evidence": ["API/MCP schemas"],
        "gap": "deployment-specific data inventory and classification",
    },
    {
        "id": 6,
        "title": "Human oversight measures",
        "status": "COVERED",
        "evidence": ["plan approval", "WAITING_PERMISSION", "plan-bound remote authority"],
    },
    {
        "id": 7,
        "title": "Accuracy, robustness, and cybersecurity evidence",
        "status": "PARTIAL",
        "evidence": ["deterministic gates", "fail-closed behavior", "native Z3", "CI/tests"],
        "gap": "versioned target metrics and lifecycle cybersecurity evaluation",
    },
    {
        "id": 8,
        "title": "Post-market monitoring",
        "status": "PARTIAL",
        "evidence": ["docs/compliance/post-market-monitoring.md"],
        "gap": "recurring production monitoring reports and metrics baseline",
    },
    {
        "id": 9,
        "title": "Incident reporting and corrective action",
        "status": "PARTIAL",
        "evidence": ["docs/compliance/incident-response.md"],
        "gap": "recorded drill and CAPA operating evidence",
    },
)


def _summary() -> dict[str, int | float]:
    covered = sum(item["status"] == "COVERED" for item in _ITEMS)
    partial = sum(item["status"] == "PARTIAL" for item in _ITEMS)
    total = len(_ITEMS)
    return {
        "total": total,
        "covered": covered,
        "partial": partial,
        "not_verified": total - covered - partial,
        "coverage_percent": round(covered / total * 100, 1),
    }


@router.get("/status")
def compliance_status():
    return {
        "product": "DSG Cinema",
        "certification_status": "NOT_CERTIFIED",
        "eu_ai_act_classification": "USE_CASE_ASSESSMENT_REQUIRED",
        "iso_42001": "AIMS_DOCUMENTED_EXTERNAL_CERTIFICATION_NOT_ESTABLISHED",
        "annex_iv": _summary(),
        "truth_boundary": {
            "z3_is_conformity_assessment": False,
            "internal_proof_is_external_certification": False,
            "universal_annex_iii_high_risk_claim": False,
        },
    }


@router.get("/annex-iv")
def annex_iv_evidence():
    return {
        "product": "DSG Cinema",
        "status": "READINESS_MAPPING",
        "summary": _summary(),
        "items": list(_ITEMS),
        "note": "Technical evidence mapping only; not a declaration of conformity or certification.",
    }


def install(app: FastAPI) -> None:
    app.include_router(router)
