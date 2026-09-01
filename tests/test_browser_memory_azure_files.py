from __future__ import annotations

import json
from pathlib import Path

from api_v1 import browser_memory_file, browser_memory_store


def _record(account_hash: str, *, url: str, action: str = "user.navigate", title: str = "Example"):
    return browser_memory_file.record_observation(
        account_hash=account_hash,
        provider="azure_container_apps",
        logical_browser_id="azure-logical-user",
        url=url,
        title=title,
        source="USER_OBSERVED",
        actor="USER",
        action=action,
        project_id="cinema",
        importance=60,
    )


def test_file_backend_persists_sanitized_profile_memory_and_event(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DSG_BROWSER_MEMORY_STORE", str(tmp_path / "memory"))
    account = "a" * 64
    memory_id = _record(account, url="https://User:Pass@Example.COM/work?token=secret#private")
    assert memory_id and memory_id.startswith("bmf_")

    profile = json.loads((tmp_path / "memory" / "profiles" / f"{account}.json").read_text())
    assert profile["last_url"] == "https://example.com/work"
    assert "secret" not in json.dumps(profile).lower()

    memories = list((tmp_path / "memory" / "memories" / account).glob("*.json"))
    events = list((tmp_path / "memory" / "events" / account).glob("*.json"))
    assert len(memories) == 1
    assert len(events) == 1
    payload = json.loads(memories[0].read_text())
    assert payload["content"]["url"] == "https://example.com/work"
    assert payload["source"] == "USER_OBSERVED"


def test_file_backend_dedupes_memory_but_appends_provenance(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DSG_BROWSER_MEMORY_STORE", str(tmp_path / "memory"))
    account = "b" * 64
    first = _record(account, url="https://example.com/work")
    second = _record(account, url="https://example.com/work")
    assert first == second
    assert len(list((tmp_path / "memory" / "memories" / account).glob("*.json"))) == 1
    assert len(list((tmp_path / "memory" / "events" / account).glob("*.json"))) == 2


def test_file_backend_search_filters_origin_query_and_budget(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DSG_BROWSER_MEMORY_STORE", str(tmp_path / "memory"))
    account = "c" * 64
    _record(account, url="https://github.com/acme/repo", title="Cinema deployment")
    _record(account, url="https://example.com/other", title="Other work")

    result = browser_memory_file.search_context(
        account_hash=account,
        query="deployment",
        project_id="cinema",
        origin="https://github.com/path?q=ignored",
        token_budget=1000,
        limit=100,
    )
    assert result["available"] is True
    assert result["backend"] == "azure_files"
    assert result["stored_memory_count"] == 2
    assert len(result["memories"]) == 1
    assert result["memories"][0]["origin"] == "https://github.com"
    assert result["selected_token_estimate"] <= result["token_budget"]


def test_file_backend_can_account_for_logical_context_over_one_million_tokens(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DSG_BROWSER_MEMORY_STORE", str(tmp_path / "memory"))
    account = "d" * 64
    directory = tmp_path / "memory" / "memories" / account
    directory.mkdir(parents=True)
    for index in range(6):
        record = {
            "memory_id": f"bmf_{index}",
            "account_hash": account,
            "project_id": "cinema",
            "origin": "https://example.com",
            "memory_type": "navigation",
            "memory_key": f"k{index}",
            "content": {"url": f"https://example.com/{index}"},
            "content_text": "context",
            "source": "SYSTEM_OBSERVED",
            "confidence": 1.0,
            "importance": 50,
            "token_estimate": 200_000,
            "memory_hash": f"h{index}",
            "created_at": "2026-09-01T00:00:00Z",
            "updated_at": f"2026-09-01T00:00:0{index}Z",
            "expires_at": None,
        }
        (directory / f"{index}.json").write_text(json.dumps(record), encoding="utf-8")

    result = browser_memory_file.search_context(account_hash=account, token_budget=32_000)
    assert result["stored_token_estimate"] == 1_200_000
    assert result["stored_memory_count"] == 6
    # Oversized atomic memories are skipped rather than truncated, preserving
    # meaning/provenance while keeping active context within its hard budget.
    assert result["memories"] == []
    assert result["selected_token_estimate"] == 0
    assert result["selected_token_estimate"] <= result["token_budget"]


def test_store_facade_prefers_postgres_and_uses_azure_files_when_requested(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DSG_BROWSER_MEMORY_DATABASE_URL", raising=False)
    monkeypatch.delenv("DSG_REVENUE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DSG_BROWSER_MEMORY_BACKEND", raising=False)
    assert browser_memory_store.backend() == "disabled"
    assert browser_memory_store.configured() is False

    monkeypatch.setenv("DSG_BROWSER_MEMORY_BACKEND", "azure_files")
    monkeypatch.setenv("DSG_BROWSER_MEMORY_STORE", str(tmp_path / "memory"))
    assert browser_memory_store.backend() == "azure_files"
    assert browser_memory_store.configured() is True
    result = browser_memory_store.search_context(account_hash="e" * 64)
    assert result["backend"] == "azure_files"

    monkeypatch.setenv("DSG_REVENUE_DATABASE_URL", "postgresql://configured")
    assert browser_memory_store.backend() == "postgres"
