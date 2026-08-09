from app.config import derive_aimo_cinema_token, load_settings


def test_cinema_token_is_deterministic_and_does_not_expose_root() -> None:
    first = derive_aimo_cinema_token("one-root-secret")
    second = derive_aimo_cinema_token("one-root-secret")
    assert first == second
    assert first.startswith("dsg_aimo_")
    assert "one-root-secret" not in first


def test_shared_root_configures_api_key(monkeypatch) -> None:
    monkeypatch.delenv("DSG_API_KEY", raising=False)
    monkeypatch.setenv("DSG_AIMO_ROOT_KEY", "one-root-secret")
    settings = load_settings()
    assert settings.api_key == derive_aimo_cinema_token("one-root-secret")


def test_service_key_overrides_shared_root(monkeypatch) -> None:
    monkeypatch.setenv("DSG_API_KEY", "cinema-service-key")
    monkeypatch.setenv("DSG_AIMO_ROOT_KEY", "one-root-secret")
    settings = load_settings()
    assert settings.api_key == "cinema-service-key"
