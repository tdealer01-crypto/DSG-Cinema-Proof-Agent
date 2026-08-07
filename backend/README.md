# DSG Cinema Proof Agent backend

FastAPI service combining Google ADK + Gemini, Grafana MCP production evidence, server-side Z3 verification, and proof/audit persistence.

Audit backends: `sqlite`, `firestore`, or `supabase`. No simulated provider success response is used.

Install: `python -m pip install -e '.[dev]'` then `pytest`.
Run: `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
