# Verification record

## Verified during assembly

- Supabase project creation returned `ACTIVE_HEALTHY`.
- Supabase audit migration applied successfully.
- Supabase database-level append/lookup/cleanup self-test passed and left no test event behind.
- Python source compilation passed in the assembly environment before the final Git tree refactor.
- Lightweight audit/auth tests passed before dependency-complete CI was available.
- Source review confirmed Android verification uses a real HTTP `POST /v1/verify` and no longer generates fake `ACCEPTED_200` / `VERIFIED_100_PERCENT` provider responses.
- Google documentation checked during assembly lists `gemini-3.6-flash` as a stable model and current agents-cli project guidance uses `google-adk[gcp]>=2.0.0,<3.0.0`.
- GitHub repository visibility was verified as `public` after publication.

## CI trigger

This verification-record update intentionally creates a normal `push` event on `main` after `.github/workflows/backend-ci.yml` already exists in the branch. The resulting GitHub Actions run, if enabled for the repository, is the first dependency-complete CI evidence for the published source snapshot.

## Not yet claimed

Until GitHub CI and external runtime checks provide evidence, this file does not claim:

- full dependency-installed pytest pass for the final commit;
- Android Gradle build pass for the final refactor;
- successful live Gemini/Vertex AI call;
- successful live Grafana MCP call;
- successful Cloud Run deployment;
- successful application-level Supabase write using a deployed service-role secret.
