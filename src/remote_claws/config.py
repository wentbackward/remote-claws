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
    # Default to real Chrome so the server browses with a normal-looking
    # fingerprint and can pass the bot walls / paywalls that bundled
    # Playwright Chromium trips. Set to "chromium" to fall back to the
    # bundled test build (lightweight, repeatable, useful for internal sites
    # and CI — but visibly automated to anti-bot vendors).
    browser_channel: str = "chrome"
    # Persistent Chrome profile directory. Holds cookies, logins, extensions
    # across server restarts so the agent browses with the user's identity
    # on services they explicitly signed into via remote-claws-browser-setup.
    # Empty string = use the OS-appropriate default (see
    # remote_claws.browser.profile.default_profile_dir).
    browser_profile_dir: str = ""
    # Apply tf-playwright-stealth to every new page. Removes the residual
    # automation tells (navigator.webdriver, missing chrome.runtime, etc.)
    # that survive even when driving real Chrome via Playwright. Disable
    # only if a site is misbehaving under the patches.
    browser_stealth: bool = True
    screenshot_max_width: int = 1280
    screenshot_max_height: int = 960
    screenshot_quality: int = 75
    screenshot_dir: str = ""
    permissions_file: str = "permissions.json"
    allowed_ips: str = ""  # comma-separated; empty = allow all (rely on token auth only)
    auth_file: str = ".remote-claws-auth.json"
    config_file: str = "remote-claws.json"  # optional JSON config overlay
    # Comma-separated list of tool groups to enable at startup. A group that is
    # not listed here is never imported and none of its tools are registered,
    # regardless of permissions.json. Use this to keep heavy dependencies
    # (Playwright, pyautogui) out of memory on machines that don't need them.
    enabled_groups: str = "browser,desktop,exec,files"
    # MCP transport to expose. "sse" is the legacy transport (works with
    # Claude Desktop, openclaw, most existing clients). "streamable-http" is
    # the MCP spec 2025-03-26+ transport (Claude Code, newer SDKs). Default
    # is "sse" for backward compatibility.
    transport: str = "sse"

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

    def get_enabled_groups(self) -> list[str]:
        """Parse enabled_groups into a list of group names."""
        raw = self.enabled_groups.strip()
        if not raw:
            return []
        return [g.strip() for g in raw.split(",") if g.strip()]

    def get_allowed_hosts(self) -> list[str]:
        """Parse allowed_hosts into a list. Returns ["*"] to disable checking."""
        raw = self.allowed_hosts.strip()
        if raw == "*":
            return ["*"]
        return [h.strip() for h in raw.split(",") if h.strip()]
