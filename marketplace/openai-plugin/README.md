# DSG Verified Execution — OpenAI Plugin submission package

This directory packages the current DSG Cinema + exact Z3 verification backend as a Skills-only plugin surface.

Runtime:

`Any Agent/App → Approved Plan/Policy → Cinema /verify/evaluate → exact Z3 proof → Proof Receipt`

The plugin does not use the retired DSG Control Plane runtime and never exposes the solver credential.

## Package

Run:

```bash
./scripts/validate.sh
./scripts/package.sh
```

The package script writes `dist/dsg-verified-execution-plugin-1.0.0.zip`.

## Live endpoint binding

For local/external testing set:

```bash
export DSG_VERIFY_URL="https://<cinema-production-host>"
```

Do not hard-code an unverified production hostname. Submission should use the production endpoint only after its current deployment evidence passes.

## Claim boundary

Supported: deterministic ALLOW/REVIEW/BLOCK verification, exact Z3 `VERIFIED_GLOBAL_OPTIMUM`, proof/request/context hashes, replay/evidence metrics.

Not claimed: SOC 2, ISO certification, regulatory certification, or third-party audit completion.
