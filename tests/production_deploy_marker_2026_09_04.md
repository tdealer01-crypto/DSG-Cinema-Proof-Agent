# Production deployment marker — 2026-09-04

Purpose: trigger the existing fail-closed `Deploy Cinema + Z3 Production` workflow from the current verified `main` without changing runtime behavior.

This marker intentionally lives under `tests/**`, which is already included in the production workflow path filter. Deployment success must still be established by the workflow's existing pre-deploy tests, Azure OIDC deployment steps, production Cinema→Z3 E2E/replay checks, credential-rotation checks, marketplace/CORS checks, billing/enforcement checks, and uploaded production evidence.

No runtime or compliance claim is changed by this file.
