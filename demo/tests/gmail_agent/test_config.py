"""config startup validation — missing var names itself; paths default."""

from __future__ import annotations

import pytest

from gmail_agent import config

_REQUIRED = (
    config.ENV_ADDRESS,
    config.ENV_TOPIC,
    config.ENV_SUBSCRIPTION,
    config.ENV_ADC,
    config.ENV_CREDENTIALS_PATH,
    config.ENV_TOKEN_PATH,
)


def _clear(monkeypatch):
    for name in _REQUIRED:
        monkeypatch.delenv(name, raising=False)


def test_missing_required_var_is_named(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv(config.ENV_ADDRESS, "agent.demo@example.com")
    monkeypatch.setenv(config.ENV_TOPIC, "projects/demo/topics/gmail")
    monkeypatch.setenv(config.ENV_SUBSCRIPTION, "projects/demo/subscriptions/pull")
    # GOOGLE_APPLICATION_CREDENTIALS absent
    with pytest.raises(config.MissingConfig) as exc:
        config.load()
    assert config.ENV_ADC in str(exc.value)


def test_load_ok_paths_default(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv(config.ENV_ADDRESS, "agent.demo@example.com")
    monkeypatch.setenv(config.ENV_TOPIC, "projects/demo/topics/gmail")
    monkeypatch.setenv(config.ENV_SUBSCRIPTION, "projects/demo/subscriptions/pull")
    monkeypatch.setenv(config.ENV_ADC, "/tmp/adc.json")
    cfg = config.load()
    assert cfg.address == "agent.demo@example.com"
    assert cfg.credentials_path == config.DEFAULT_CREDENTIALS_PATH
    assert cfg.token_path == config.DEFAULT_TOKEN_PATH


def test_require_address_raises(monkeypatch):
    monkeypatch.delenv(config.ENV_ADDRESS, raising=False)
    with pytest.raises(config.MissingConfig):
        config.require_address()
