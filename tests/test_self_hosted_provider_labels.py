"""Compatibility and truth boundary for AWS self-hosted Cinema metadata.

This test does NOT assert a signed browser connect/execute E2E.
"""
from api_v1 import azure_local_browser, shared_browser


def test_aws_self_hosted_mode_uses_neutral_public_labels(monkeypatch):
    monkeypatch.setenv("DSG_BROWSER_PROVIDER", "self_hosted")
    assert azure_local_browser.configured() is True
    assert azure_local_browser.self_hosted_mode() is True
    assert azure_local_browser.public_provider() == "self_hosted_playwright"
    assert azure_local_browser.public_backend() == "self_hosted"
    assert shared_browser.provider() == "self_hosted_playwright"

    result = azure_local_browser._public_metadata(
        "a" * 64, {"browser_session_id": "existing-id", "last_pages": []},
        connected=True,
    )
    assert result["provider"] == "self_hosted_playwright"
    assert result["backend"] == "self_hosted"
    # Never change persistent internal session bindings as part of a UI label fix.
    assert azure_local_browser.BACKEND_VALUE == "azure_local"


def test_legacy_mode_and_existing_viewer_tokens_remain_compatible(monkeypatch):
    monkeypatch.setenv("DSG_BROWSER_PROVIDER", "azure_local")
    assert azure_local_browser.public_provider() == "azure_container_apps"
    assert azure_local_browser.public_backend() == "azure_local"
    assert shared_browser.provider() == "azure_container_apps"
    for value in ("self_hosted_playwright", "azure_container_apps"):
        assert azure_local_browser.is_local_provider(value) is True
    assert azure_local_browser.is_local_provider("browserbase") is False
