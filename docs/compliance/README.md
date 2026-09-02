# DSG Cinema Compliance System

This directory is the compliance source of truth for DSG Cinema.

## Product boundary

DSG Cinema is a hosted governed-execution runtime. It binds execution to an approved plan, checks authority and capability before execution, records evidence, and can invoke the native Z3 verifier for deterministic proof.

The compliance package distinguishes three things that must not be conflated:

1. **Technical controls** implemented by Cinema.
2. **Regulatory readiness evidence** produced from those controls.
3. **External certification or conformity assessment**, which only an applicable legal process or independent certification body can establish.

A passing DSG proof, CI run, Z3 result, or internal evidence pack is technical evidence. It is not by itself an EU AI Act conformity assessment, CE marking, ISO/IEC 42001 certification, marketplace approval, or independent audit.

## Files

- `classification.md` — AI-system / high-risk classification procedure and current preliminary position.
- `risk-register.md` — lifecycle compliance and product risk register.
- `aims.md` — Cinema AI management system scope and operating controls.
- `post-market-monitoring.md` — Article 72-style monitoring procedure for deployments where the obligation applies.
- `incident-response.md` — incident handling and regulatory escalation procedure.
- `annex-iv-mapping.md` — technical-documentation mapping to Cinema-native evidence.

## Runtime evidence sources

Cinema evidence should resolve to current runtime artifacts rather than copied Control Plane claims:

- `/health`
- `/api/v1/status`
- `/api/v1/mcp`
- approved plan and plan hash
- preflight decision (`ALLOW`, `WAITING_PERMISSION`, `BLOCK`)
- execution/evidence records
- native Z3 proof result
- production deployment workflow evidence

## Truth boundary

Compliance language must remain evidence-bounded. If a requirement is not supported by current code, procedure, test, production artifact, or external assessment, mark it `PARTIAL`, `NOT VERIFIED`, or `NOT APPLICABLE` rather than claiming compliance.