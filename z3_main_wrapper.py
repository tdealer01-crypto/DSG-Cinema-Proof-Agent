"""Production entrypoint that extends the existing Z3 service without changing its core."""

from main import app, require_auth
from z3_exact_topk import install_exact_topk

install_exact_topk(app, require_auth)
