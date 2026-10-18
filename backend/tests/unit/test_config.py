import pytest
from app.core.config import Settings
from pydantic import ValidationError


def test_host_debug_does_not_affect_application(monkeypatch):
    monkeypatch.setenv("DEBUG", "release")
    monkeypatch.delenv("OGAFLOW_DEBUG", raising=False)
    assert Settings(_env_file=None).debug is False


@pytest.mark.parametrize("value,expected", [("true", True), ("false", False)])
def test_application_debug_boolean(monkeypatch, value, expected):
    monkeypatch.setenv("OGAFLOW_DEBUG", value)
    assert Settings(_env_file=None).debug is expected


def test_invalid_application_debug_is_rejected(monkeypatch):
    monkeypatch.setenv("OGAFLOW_DEBUG", "release")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_production_rejects_demo_mode(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("OGAFLOW_DEMO_MODE", "true")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
