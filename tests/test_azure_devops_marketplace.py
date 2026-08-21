import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "marketplace" / "azure-devops"
APP_URL = "https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/app"


def test_manifest_is_paid_byol_and_uses_current_app_surface():
    manifest = json.loads((PACKAGE / "vss-extension.template.json").read_text())

    assert manifest["publisher"] == "__PUBLISHER_ID__"
    assert "Paid" in manifest["galleryFlags"]
    assert "__BYOLENFORCED" in manifest["tags"]
    assert manifest["links"]["home"]["uri"] == APP_URL
    assert manifest["public"] is False

    contribution = manifest["contributions"][0]
    assert contribution["type"] == "ms.azure-pipelines.pipeline-decorator"
    assert contribution["properties"]["template"] == "dsg-verify.yml"


def test_decorator_requires_verified_global_optimum_and_blocks_block_verdict():
    doc = yaml.safe_load((PACKAGE / "dsg-verify.yml").read_text())
    script = doc["steps"][0]["bash"]

    assert 'DSG_VERIFY_ENABLED:-false' in script
    assert '/verify/evaluate' in script
    assert 'VERIFIED_GLOBAL_OPTIMUM' in script
    assert '.verified == true' in script
    assert 'decision" = "BLOCK"' in script
    assert 'DSG_API_KEY' in script
    assert 'DSG_VERIFICATION_REQUEST_PATH' in script
