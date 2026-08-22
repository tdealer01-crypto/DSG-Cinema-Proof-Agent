from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from pydantic import ValidationError

from revenue.api import ActivateRequest

html = (ROOT / "web" / "dsg-one-3d" / "index.html").read_text(encoding="utf-8")
assert 'id="btnActivateFree"' in html
assert 'id="activationNotice"' in html
assert 'activation_id: stableActivationId()' in html
assert 'display_name: "DSG ONE browser evaluation"' in html
assert 'localStorage.setItem("dsg-one-key", payload.api_key)' in html
assert 'headers["X-DSG-API-Key"] = S.key' in html

valid = ActivateRequest(channel="api", activation_id="web-test-123", display_name="DSG ONE browser evaluation")
assert valid.channel == "api"
assert valid.display_name == "DSG ONE browser evaluation"
try:
    ActivateRequest(channel="api", activation_id="web-test-123")
except ValidationError:
    pass
else:
    raise AssertionError("activation schema must reject a missing display_name")
print("ok: activation request contract and /app key wiring")
