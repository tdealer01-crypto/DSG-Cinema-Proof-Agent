# Deployment boundary

These are deployment instructions, not evidence that deployment already exists.

Recommended Google Cloud shape:

```text
Internet -> Cloud Run: DSG backend
             -> Vertex AI / Gemini
             -> private official Grafana MCP service
             -> Firestore or Supabase audit backend
```

Backend environment should use `GOOGLE_GENAI_USE_VERTEXAI=true`, a real Google Cloud project/location, `GRAFANA_MCP_URL`, and secrets from a managed secret store. For Supabase use `AUDIT_BACKEND=supabase`, `SUPABASE_URL`, and a server-only `SUPABASE_SERVICE_ROLE_KEY`.

For a separately deployed official Grafana MCP service use Streamable HTTP and `--disable-write`; keep it private where practical and configure the actual allowed host/audience only after the service URL exists.

Post-deploy evidence to collect: `/health`, one real `/v1/cinema/investigate`, Grafana tool-call logs, SAT + UNSAT Z3 cases, and matching audit lookup.
