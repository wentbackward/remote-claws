"""Shared test fixtures."""

import json

import pytest


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """Ensure tests run with a clean environment — no leaked REMOTE_CLAWS_ vars."""
    monkeypatch.delenv("REMOTE_CLAWS_HOST", raising=False)
    monkeypatch.delenv("REMOTE_CLAWS_PORT", raising=False)
    monkeypatch.delenv("REMOTE_CLAWS_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("REMOTE_CLAWS_BROWSER_CHANNEL", raising=False)
    monkeypatch.delenv("REMOTE_CLAWS_BROWSER_STEALTH", raising=False)
    monkeypatch.delenv("REMOTE_CLAWS_ENABLED_GROUPS", raising=False)
    monkeypatch.delenv("REMOTE_CLAWS_TRANSPORT", raising=False)
    monkeypatch.delenv("REMOTE_CLAWS_CONFIG_FILE", raising=False)


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace with a permissions.json and auth file."""
    perms = tmp_path / "permissions.json"
    perms.write_text(json.dumps({"browser_navigate": "allow", "exec_run": "deny"}))
    auth = tmp_path / ".remote-claws-auth.json"
    auth.write_text(json.dumps({"token_hash": "fake_hash_for_testing"}))
    return tmp_path


@pytest.fixture
def sample_token():
    """A deterministic test token (not cryptographically secure, just for tests)."""
    return "a" * 64
