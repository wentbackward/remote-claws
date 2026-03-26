from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _expand_env_vars(value: str) -> str:
    """Replace ${VAR_NAME} or ${VAR_NAME:-default} with env var values."""
    def replacer(match: re.Match) -> str:
        var = match.group(1)
        if ":-" in var:
            name, default = var.split(":-", 1)
            return os.environ.get(name, default)
        return os.environ.get(var, match.group(0))  # leave unresolved as-is

    return re.sub(r"\$\{([^}]+)\}", replacer, value)


def _expand_recursive(obj):
    """Walk a JSON structure and expand env var references in all strings."""
    if isinstance(obj, str):
        return _expand_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _expand_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_recursive(v) for v in obj]
    return obj


def load_config_file(path: str = "remote-claws.json") -> dict:
    """Load optional JSON config file with ${ENV_VAR} expansion.

    Returns empty dict if file doesn't exist.
    """
    p = Path(path)
    if not p.exists():
        return {}
    with open(p) as f:
        raw = json.load(f)
    return _expand_recursive(raw)


class AppConfig(BaseSettings):
    """Priority (highest to lowest): env vars → config file → defaults."""

    model_config = SettingsConfigDict(env_prefix="REMOTE_CLAWS_")

    host: str = "0.0.0.0"
    port: int = 8080
    allowed_hosts: str = "*"  # comma-separated; "*" disables host checking
    browser_headless: bool = False
    browser_channel: str = "chromium"
    screenshot_max_width: int = 1280
    screenshot_max_height: int = 960
    screenshot_quality: int = 75
    screenshot_dir: str = ""
    permissions_file: str = "permissions.json"
    allowed_ips: str = ""  # comma-separated; empty = allow all (rely on token auth only)
    auth_file: str = ".remote-claws-auth.json"
    config_file: str = "remote-claws.json"  # optional JSON config overlay

    def __init__(self, **overrides):
        # Determine config file path: explicit override > env var > default
        cf = overrides.get(
            "config_file",
            os.environ.get("REMOTE_CLAWS_CONFIG_FILE", "remote-claws.json"),
        )
        file_values = load_config_file(cf)
        # File values are defaults that env vars override (pydantic-settings
        # reads env vars automatically, so we just merge file values under them)
        merged = {**file_values, **overrides}
        super().__init__(**merged)

    def get_allowed_ips(self) -> list[str]:
        """Parse allowed_ips into a list. Returns [] to disable IP filtering."""
        raw = self.allowed_ips.strip()
        if not raw:
            return []
        return [ip.strip() for ip in raw.split(",") if ip.strip()]

    def get_allowed_hosts(self) -> list[str]:
        """Parse allowed_hosts into a list. Returns ["*"] to disable checking."""
        raw = self.allowed_hosts.strip()
        if raw == "*":
            return ["*"]
        return [h.strip() for h in raw.split(",") if h.strip()]
