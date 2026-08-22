from pathlib import Path
import re
import subprocess
import tempfile

html = Path(__file__).parents[1] / "web" / "dsg-one-3d" / "index.html"
text = html.read_text(encoding="utf-8")
scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", text, flags=re.S)
if not scripts:
    raise SystemExit("no inline scripts found")
with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
    handle.write("\n".join(scripts))
    path = handle.name
result = subprocess.run(["node", "--check", path], text=True, capture_output=True)
if result.returncode:
    raise SystemExit(result.stderr)
print(f"ok: checked {len(scripts)} inline script blocks")
Path(path).unlink(missing_ok=True)
