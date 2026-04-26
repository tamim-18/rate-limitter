"""Settings loads, reads env, and rejects invalid values at construction."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from rate_limiter.config import Settings, get_settings


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Construct with no .env present; defaults match what main.py expects."""
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    s = Settings()
    assert s.environment == "development"
    assert s.log_level == "INFO"
    assert s.default_algorithm == "token_bucket"
    assert s.default_rate_limit == 100
    assert s.default_window_seconds == 60
    assert s.docs_enabled is True
    assert s.json_logs is False


def test_settings_reads_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Env vars override defaults; production flips docs_enabled and json_logs."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    get_settings.cache_clear()
    s = Settings()
    assert s.environment == "production"
    assert s.log_level == "WARNING"
    assert s.docs_enabled is False
    assert s.json_logs is True


def test_settings_rejects_invalid_log_level(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Typo in LOG_LEVEL fails at startup, not mid-request."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOG_LEVEL", "INFOO")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        Settings()


def test_settings_rejects_invalid_algorithm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Unknown algorithm name is caught by pydantic before reaching the factory."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEFAULT_ALGORITHM", "magic_bucket")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        Settings()
