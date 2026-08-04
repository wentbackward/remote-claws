"""Shared test fixtures."""

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
    # Point the config-file overlay at a path that does not exist, so a
    # developer's local remote-claws.json in the repo root cannot leak into
    # test runs and silently flip defaults (e.g. transport).
    monkeypatch.setenv("REMOTE_CLAWS_CONFIG_FILE", "__nonexistent__.json")
