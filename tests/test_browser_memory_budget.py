from __future__ import annotations

from api_v1 import browser_memory_store


def test_provider_boundary_skips_single_oversized_memory(monkeypatch):
    monkeypatch.delenv("DSG_BROWSER_MEMORY_DATABASE_URL", raising=False)
    monkeypatch.delenv("DSG_REVENUE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DSG_BROWSER_MEMORY_BACKEND", "azure_files")
    monkeypatch.setattr(
        browser_memory_store.azure_files,
        "search_context",
        lambda **_kwargs: {
            "available": True,
            "backend": "azure_files",
            "stored_memory_count": 1,
            "stored_token_estimate": 1_200_000,
            "selected_token_estimate": 200_000,
            "token_budget": 32_000,
            "memories": [
                {
                    "memory_id": "oversized",
                    "token_estimate": 200_000,
                    "content": {"url": "https://example.com"},
                }
            ],
        },
    )

    result = browser_memory_store.search_context(
        account_hash="a" * 64,
        token_budget=32_000,
    )

    assert result["stored_token_estimate"] == 1_200_000
    assert result["token_budget"] == 32_000
    assert result["selected_token_estimate"] == 0
    assert result["memories"] == []
    assert result["active_context_bounded"] is True


def test_provider_boundary_never_exceeds_cumulative_budget(monkeypatch):
    monkeypatch.delenv("DSG_BROWSER_MEMORY_DATABASE_URL", raising=False)
    monkeypatch.delenv("DSG_REVENUE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DSG_BROWSER_MEMORY_BACKEND", "azure_files")
    monkeypatch.setattr(
        browser_memory_store.azure_files,
        "search_context",
        lambda **_kwargs: {
            "available": True,
            "backend": "azure_files",
            "stored_memory_count": 4,
            "stored_token_estimate": 40_000,
            "memories": [
                {"memory_id": "a", "token_estimate": 9_000},
                {"memory_id": "b", "token_estimate": 9_000},
                {"memory_id": "c", "token_estimate": 20_000},
                {"memory_id": "d", "token_estimate": 10_000},
            ],
        },
    )

    result = browser_memory_store.search_context(
        account_hash="b" * 64,
        token_budget=28_000,
    )

    assert [item["memory_id"] for item in result["memories"]] == ["a", "b", "d"]
    assert result["selected_token_estimate"] == 28_000
    assert result["selected_token_estimate"] <= result["token_budget"]


def test_provider_boundary_clamps_requested_budget(monkeypatch):
    monkeypatch.delenv("DSG_BROWSER_MEMORY_DATABASE_URL", raising=False)
    monkeypatch.delenv("DSG_REVENUE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DSG_BROWSER_MEMORY_BACKEND", raising=False)

    result = browser_memory_store.search_context(
        account_hash="c" * 64,
        token_budget=9_999_999,
    )

    assert result["available"] is False
    assert result["backend"] == "disabled"
    assert result["token_budget"] == browser_memory_store.MAX_ACTIVE_TOKEN_BUDGET
    assert result["selected_token_estimate"] == 0
    assert result["active_context_bounded"] is True
