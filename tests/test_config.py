"""Test config loading: defaults, env vars, JSON file, priority."""

import json

from remote_claws.config import AppConfig, load_config_file


def test_defaults():
    cfg = AppConfig()
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8080
    assert cfg.transport == "sse"
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
