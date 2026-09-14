from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "api_v1" / "browserbase_live_ui.py").read_text(encoding="utf-8")


def test_azure_provider_returns_azure_named_view_route():
    assert '"embed_url": f"/remote-browser/azure/view/{viewer}"' in SOURCE
    assert '@router.get("/remote-browser/azure/view/{viewer_token}"' in SOURCE


def test_legacy_browserbase_embed_route_is_retained_for_compatibility():
    assert '@router.get("/remote-browser/browserbase/embed/{viewer_token}"' in SOURCE
