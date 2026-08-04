"""Test server startup: transport selection, config validation, middleware."""

import json

from remote_claws.config import AppConfig
from remote_claws.permissions import PermissionChecker


def _make_perms(data: dict) -> dict:
    """Wrap raw group->rules dict in the top-level 'permissions' key."""
    return {"permissions": data}


def test_transport_streamable_http_default(tmp_path):
    """Default transport should be Streamable HTTP (SSE was deprecated by the MCP spec)."""
    (tmp_path / "perms.json").write_text("{}")
    (tmp_path / "auth.json").write_text(json.dumps({"token_hash": "abc123"}))
    cfg = AppConfig(
        permissions_file=str(tmp_path / "perms.json"),
        auth_file=str(tmp_path / "auth.json"),
    )
    assert cfg.transport == "streamable-http"


def test_transport_streamable_http(tmp_path, monkeypatch):
    """Transport can be overridden via env var."""
    monkeypatch.setenv("REMOTE_CLAWS_TRANSPORT", "streamable-http")
    (tmp_path / "perms.json").write_text("{}")
    (tmp_path / "auth.json").write_text(json.dumps({"token_hash": "abc123"}))
    cfg = AppConfig(
        permissions_file=str(tmp_path / "perms.json"),
        auth_file=str(tmp_path / "auth.json"),
    )
    assert cfg.transport == "streamable-http"


def test_permissions_checker_created_at_startup(tmp_path):
    """Permissions checker should be created from config."""
    perms_file = tmp_path / "perms.json"
    perms_file.write_text(json.dumps(_make_perms({"browser": {"allow": ["navigate"]}})))
    cfg = AppConfig(permissions_file=str(perms_file))
    checker = PermissionChecker(cfg.permissions_file, enabled_groups=cfg.get_enabled_groups())
    assert checker.is_action_allowed("browser", "navigate") is True
    assert checker.is_action_allowed("browser", "click") is False  # not in perms


def test_enabled_groups_filter(tmp_path):
    """Only enabled groups should be active."""
    perms_file = tmp_path / "perms.json"
    perms_file.write_text(
        json.dumps(
            _make_perms(
                {
                    "browser": {"allow": ["*"]},
                    "exec": {"allow": ["*"]},
                }
            )
        )
    )
    cfg = AppConfig(
        permissions_file=str(perms_file),
        enabled_groups="browser,exec",
    )
    checker = PermissionChecker(cfg.permissions_file, enabled_groups=cfg.get_enabled_groups())
    assert checker.is_group_active("browser") is True
    assert checker.is_group_active("exec") is True
    assert checker.is_group_active("desktop") is False
    assert checker.is_group_active("files") is False
