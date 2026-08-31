from __future__ import annotations

import pytest

from app import config


def test_get_config_reads_yaml_and_defaults(monkeypatch):
    monkeypatch.delenv("DEVICE_API_KEY", raising=False)
    monkeypatch.delenv("MAX_UPLOAD_BYTES", raising=False)
    config.get_config.cache_clear()

    cfg = config.get_config()

    assert cfg.model.path.endswith(".onnx")
    assert cfg.inference.person_confidence_threshold == pytest.approx(0.65)
    assert cfg.device_api_key == ""
    assert cfg.max_upload_bytes == 5 * 1024 * 1024
    assert cfg.env == "development"


def test_get_config_picks_up_env_overrides(monkeypatch):
    monkeypatch.setenv("DEVICE_API_KEY", "abc123")
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1024")
    monkeypatch.setenv("ENV", "production")
    config.get_config.cache_clear()

    cfg = config.get_config()

    assert cfg.device_api_key == "abc123"
    assert cfg.max_upload_bytes == 1024
    assert cfg.env == "production"


def test_get_config_is_cached_until_cleared(monkeypatch):
    monkeypatch.delenv("DEVICE_API_KEY", raising=False)
    config.get_config.cache_clear()
    first = config.get_config()

    monkeypatch.setenv("DEVICE_API_KEY", "should-not-appear-yet")
    second = config.get_config()

    assert first is second
    assert second.device_api_key == ""  # still the pre-change, cached instance
