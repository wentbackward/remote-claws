"""Test config loading: defaults, env vars, JSON file, priority."""

import json

from remote_claws.config import AppConfig, load_config_file


def test_defaults():
    cfg = AppConfig()
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8080
    assert cfg.transport == "streamable-http"
    assert cfg.browser_channel == "chrome"
    assert cfg.browser_stealth is True
    assert cfg.enabled_groups == "browser,desktop,exec,files"


def test_env_var_override(monkeypatch):
    monkeypatch.setenv("REMOTE_CLAWS_PORT", "9999")
    monkeypatch.setenv("REMOTE_CLAWS_HOST", "127.0.0.1")
    monkeypatch.setenv("REMOTE_CLAWS_TRANSPORT", "streamable-http")
    cfg = AppConfig()
    assert cfg.port == 9999
    assert cfg.host == "127.0.0.1"
    assert cfg.transport == "streamable-http"


def test_json_file_override(tmp_path):
    config_file = tmp_path / "my-config.json"
    config_file.write_text(json.dumps({"port": 7777, "transport": "streamable-http"}))
    cfg = AppConfig(config_file=str(config_file))
    assert cfg.port == 7777
    assert cfg.transport == "streamable-http"


def test_env_var_beats_config_file(tmp_path, monkeypatch):
    """Documented priority is env > file > default. Regression test: file
    values are passed as init kwargs, which pydantic-settings ranks above
    env vars — the merge must suppress file values when the env var is set."""
    config_file = tmp_path / "c.json"
    config_file.write_text(json.dumps({"port": 8080}))
    monkeypatch.setenv("REMOTE_CLAWS_PORT", "9999")
    cfg = AppConfig(config_file=str(config_file))
    assert cfg.port == 9999


def test_explicit_override_beats_env(tmp_path, monkeypatch):
    monkeypatch.setenv("REMOTE_CLAWS_PORT", "9999")
    cfg = AppConfig(config_file=str(tmp_path / "missing.json"), port=1234)
    assert cfg.port == 1234


def test_source_of_provenance(tmp_path, monkeypatch):
    config_file = tmp_path / "c.json"
    config_file.write_text(json.dumps({"browser_channel": "chromium"}))
    monkeypatch.setenv("REMOTE_CLAWS_PORT", "9999")
    cfg = AppConfig(config_file=str(config_file), host="1.2.3.4")
    assert cfg.source_of("host") == "explicit override"
    assert cfg.source_of("port") == "env var REMOTE_CLAWS_PORT"
    assert cfg.source_of("browser_channel") == f"config file {config_file}"
    assert cfg.source_of("browser_stealth") == "default"


def test_env_var_expansion_in_file(tmp_path):
    config_file = tmp_path / "exp.json"
    config_file.write_text(json.dumps({"port": "${MY_TEST_PORT:-5555}"}))
    cfg = AppConfig(config_file=str(config_file))
    assert cfg.port == 5555  # default from expansion


def test_env_var_expansion_with_real_var(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_TEST_PORT", "6666")
    config_file = tmp_path / "exp.json"
    config_file.write_text(json.dumps({"port": "${MY_TEST_PORT:-5555}"}))
    cfg = AppConfig(config_file=str(config_file))
    assert cfg.port == 6666  # env var used


def test_load_missing_config_returns_empty():
    assert load_config_file("/nonexistent/path.json") == {}


def test_get_enabled_groups():
    cfg = AppConfig(enabled_groups="browser,exec")
    assert cfg.get_enabled_groups() == ["browser", "exec"]


def test_get_enabled_groups_empty():
    cfg = AppConfig(enabled_groups="")
    assert cfg.get_enabled_groups() == []


def test_get_allowed_hosts_wildcard():
    cfg = AppConfig(allowed_hosts="*")
    assert cfg.get_allowed_hosts() == ["*"]


def test_get_allowed_hosts_specific():
    cfg = AppConfig(allowed_hosts="localhost, 10.0.0.1")
    assert cfg.get_allowed_hosts() == ["localhost", "10.0.0.1"]


def test_get_allowed_ips_empty():
    cfg = AppConfig(allowed_ips="")
    assert cfg.get_allowed_ips() == []


def test_get_allowed_ips_populated():
    cfg = AppConfig(allowed_ips="192.168.1.1, 10.0.0.1")
    assert cfg.get_allowed_ips() == ["192.168.1.1", "10.0.0.1"]
