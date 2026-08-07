# Provenance

This repository was created as a separate project from the user-supplied `Compliance-ising-z3-Deterministic--real-backend.zip` during the 2026 Agentic Cinema development window.

Changes made for this repository include:

- removed simulated provider-success behavior;
- retained the Android QUBO/Ising policy-client concept but reduced the UI to the verification path used by the demo;
- added Google ADK + Gemini agent runtime;
- added official Grafana MCP integration in read-only mode;
- added a cinema-production recovery policy verified by server-side Z3;
- added SQLite, Firestore, and Supabase audit backends;
- added MIT license, CI, deployment notes, and evidence boundaries.

The staging history before the final source commit contains a SHA-verified tar snapshot of the prepared source. The final source tree intentionally omits `.bootstrap` staging files.
