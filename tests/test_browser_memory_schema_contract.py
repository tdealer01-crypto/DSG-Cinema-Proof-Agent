from __future__ import annotations

from api_v1 import browser_memory


def test_browser_memory_schema_is_separate_and_indexed_for_large_context():
    sql = browser_memory.SCHEMA_SQL.lower()
    for table in (
        "dsg_browser_profiles",
        "dsg_browser_memory",
        "dsg_browser_memory_events",
        "dsg_browser_memory_summaries",
    ):
        assert f"create table if not exists {table}" in sql
    assert "using gin (to_tsvector('simple', content_text))" in sql
    assert "token_estimate integer" in sql
    assert "account_hash" in sql


def test_browser_memory_schema_never_models_raw_identity_secrets():
    sql = browser_memory.SCHEMA_SQL.lower()
    forbidden_columns = (
        "password text",
        "otp text",
        "cookie text",
        "authorization text",
        "access_token text",
        "refresh_token text",
        "api_key text",
        "card_number text",
        "cvc text",
        "cvv text",
    )
    for forbidden in forbidden_columns:
        assert forbidden not in sql


def test_active_context_is_bounded_below_stored_logical_context_scale():
    assert browser_memory.DEFAULT_ACTIVE_TOKEN_BUDGET == 32_000
    assert browser_memory.MAX_ACTIVE_TOKEN_BUDGET == 200_000
    assert browser_memory.MAX_ACTIVE_TOKEN_BUDGET < 1_000_000
