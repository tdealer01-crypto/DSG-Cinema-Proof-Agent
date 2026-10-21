from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "api_v1" / "browserbase_live_ui.py").read_text(encoding="utf-8")


def test_self_hosted_provider_issues_canonical_aws_viewer_route():
    assert '"embed_url": f"/remote-browser/self-hosted/view/{viewer}"' in SOURCE
    assert '@router.get("/remote-browser/self-hosted/view/{viewer_token}"' in SOURCE
    assert '@router.get("/remote-browser/self-hosted/view/{viewer_token}/snapshot"' in SOURCE
    assert '@router.post("/remote-browser/self-hosted/view/{viewer_token}/action"' in SOURCE
    assert "/remote-browser/self-hosted/view/${{token}}/action" in SOURCE
    assert "/remote-browser/self-hosted/view/${{token}}/snapshot" in SOURCE


def test_historical_route_remains_a_same_origin_alias_not_an_azure_backend():
    assert '@router.get("/remote-browser/azure/view/{viewer_token}"' in SOURCE
    assert '@router.get("/remote-browser/azure/view/{viewer_token}/snapshot"' in SOURCE
    assert '@router.post("/remote-browser/azure/view/{viewer_token}/action"' in SOURCE


def test_legacy_browserbase_embed_route_is_retained_for_compatibility():
    assert '@router.get("/remote-browser/browserbase/embed/{viewer_token}"' in SOURCE
