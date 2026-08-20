# DSG Governance Gate — Stripe App v2.7.0

This package is the existing Stripe Marketplace app identity (`pics.dsg.governance`) moved onto the current Cinema/Z3 backend.

## Runtime path

`Stripe payment view → /stripe/evaluate on Cinema → server-side Z3 → exact proof → Stripe-native result`

The retired Control Plane is not in the runtime path.

## Safety model

- The Stripe UI never receives `CINEMA_API_SECRET` or `DSG_BACKEND_API_KEY`.
- `/stripe/evaluate` does not accept arbitrary QUBO input.
- Cinema derives a fixed 3-variable decision QUBO: `[ALLOW, REVIEW, BLOCK]`.
- A one-hot penalty enforces exactly one decision.
- A result is accepted only when the Z3 backend returns `VERIFIED_GLOBAL_OPTIMUM` with a valid proof hash and request hash.
- Missing transaction context, backend failures, malformed proof, or proof mismatch fail closed to REVIEW in the UI.
- A deterministic `context_hash` binds the Stripe transaction context and risk score to the solver request.

## UX

The UI intentionally uses Stripe UI Extension components instead of custom HTML buttons, custom colors, or a separate dashboard design. The information hierarchy is:

1. Decision badge — ALLOW / REVIEW / BLOCK
2. Plain-language reason
3. Risk level and score
4. Z3 verification status
5. Policy version
6. Short proof reference and transaction binding

Technical proof details stay secondary so the panel reads like a normal Stripe dashboard app.

## Backend binding

`stripe-app.json` is generated at package time from `stripe-app.template.json`. CI queries the current Azure Container App named `dsg-cinema-production`, then injects its HTTPS FQDN into both:

- manifest CSP `connect-src`
- `src/runtime.ts`

No retired Control Plane or Vercel API URL is allowed by the packaging gate.

## Local checks

```bash
python -m pytest tests/test_cinema_main.py
cd stripe-app
npm install --no-audit --no-fund
npm run typecheck
CINEMA_API_BASE=https://example.invalid npm run manifest:generate
```

## Marketplace identity

- App ID: `pics.dsg.governance`
- Name: `DSG Governance Gate`
- Version: `2.7.0`
- Distribution: public
- Sandbox compatible: true

This is an update to the existing app identity, not a second Marketplace app.
