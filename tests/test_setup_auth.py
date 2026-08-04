"""Test interactive transport configuration in remote-claws-setup."""

import json
import sys
from types import SimpleNamespace

import pytest

from remote_claws import setup_auth


def _stdin(isatty: bool):
    """Replace sys.stdin wholesale — under pytest it is a restricted object
    whose attributes cannot be monkeypatched individually."""
    return SimpleNamespace(isatty=lambda: isatty)


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """Point AppConfig at a temp config file and make stdin interactive."""
    cfg = tmp_path / "remote-claws.json"
    monkeypatch.setenv("REMOTE_CLAWS_CONFIG_FILE", str(cfg))
    monkeypatch.setattr(sys, "stdin", _stdin(True))
    return cfg


def _run_with_answers(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(it))
    setup_auth._configure_transport()


def test_first_run_writes_transport(config_dir, monkeypatch):
    _run_with_answers(monkeypatch, ["2"])  # pick SSE
    assert json.loads(config_dir.read_text())["transport"] == "sse"


def test_first_run_enter_defaults_to_streamable_http(config_dir, monkeypatch):
    _run_with_answers(monkeypatch, [""])
    assert json.loads(config_dir.read_text())["transport"] == "streamable-http"


def test_existing_transport_keep_by_default(config_dir, monkeypatch):
    config_dir.write_text(json.dumps({"transport": "streamable-http"}))
    _run_with_answers(monkeypatch, ["n"])  # decline "Change it?"
    assert json.loads(config_dir.read_text())["transport"] == "streamable-http"


def test_existing_transport_can_be_changed(config_dir, monkeypatch):
    config_dir.write_text(json.dumps({"transport": "streamable-http"}))
    _run_with_answers(monkeypatch, ["y", "2"])  # change, then pick SSE
    assert json.loads(config_dir.read_text())["transport"] == "sse"


def test_existing_transport_enter_keeps_current(config_dir, monkeypatch):
    config_dir.write_text(json.dumps({"transport": "sse"}))
    _run_with_answers(monkeypatch, ["y", ""])  # change, then accept displayed default
    assert json.loads(config_dir.read_text())["transport"] == "sse"


def test_non_interactive_never_writes(config_dir, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _stdin(False))
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": pytest.fail("input() must not be called when stdin is not a TTY"),
    )
    setup_auth._configure_transport()
    assert not config_dir.exists()


def test_preserves_other_config_keys(config_dir, monkeypatch):
    config_dir.write_text(json.dumps({"host": "192.168.1.5", "transport": "sse"}))
    _run_with_answers(monkeypatch, ["y", "1"])  # switch to streamable-http
    data = json.loads(config_dir.read_text())
    assert data == {"host": "192.168.1.5", "transport": "streamable-http"}
