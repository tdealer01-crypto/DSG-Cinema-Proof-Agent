# Hybrid CI test matrix

Required before merge:

- deterministic replay: same input and seed -> same candidate and hashes;
- SAT path: annealing candidate -> real Z3 SAT -> proof hash -> audit event;
- UNSAT path: impossible constraints -> no false verified claim;
- existing backend tests remain green;
- ADK/FastAPI/MCP imports remain green;
- Google-only AI-provider boundary remains green.
