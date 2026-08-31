from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import config
from app.security import require_api_key, validate_device_id


@pytest.mark.parametrize("device_id", ["esp32-01", "cam_2", "A1", "x" * 64])
def test_validate_device_id_accepts_plain_tokens(device_id):
    assert validate_device_id(device_id) == device_id


@pytest.mark.parametrize(
    "device_id",
    ["../../etc/passwd", "a/b", "", "x" * 65, "a b", "cam;rm -rf", "..", "."],
)
def test_validate_device_id_rejects_path_traversal_and_junk(device_id):
    with pytest.raises(HTTPException) as exc_info:
        validate_device_id(device_id)
    assert exc_info.value.status_code == 400


async def test_require_api_key_disabled_when_unset(monkeypatch):
    monkeypatch.setenv("DEVICE_API_KEY", "")
    config.get_config.cache_clear()
    await require_api_key(x_api_key=None)  # must not raise


async def test_require_api_key_rejects_missing_or_wrong_key(monkeypatch):
    monkeypatch.setenv("DEVICE_API_KEY", "expected-secret")
    config.get_config.cache_clear()

    with pytest.raises(HTTPException) as exc_info:
        await require_api_key(x_api_key=None)
    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException):
        await require_api_key(x_api_key="wrong")


async def test_require_api_key_accepts_matching_key(monkeypatch):
    monkeypatch.setenv("DEVICE_API_KEY", "expected-secret")
    config.get_config.cache_clear()
    await require_api_key(x_api_key="expected-secret")  # must not raise
