"""Test server startup: transport selection, config validation, middleware."""

import json

import pytest

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


@pytest.mark.asyncio
async def test_app_lifespan_yields_process_singleton(tmp_path, monkeypatch):
    """The MCP lifespan can run per request (stateless streamable-HTTP) or per
    session (stateful/SSE). Either way it must yield the same process-level
    AppContext — a fresh one per run would wipe the exec process table and
    duplicate the browser manager."""
    from remote_claws import server

    # Deny-all permissions: no browser group, so no BrowserManager/preflight.
    checker = PermissionChecker(str(tmp_path / "missing.json"), enabled_groups=["exec"])
    monkeypatch.setattr(
        server, "_CONFIG", AppConfig(permissions_file=str(tmp_path / "p.json"), auth_file=str(tmp_path / "a.json"))
    )
    monkeypatch.setattr(server, "_PERMISSIONS", checker)
    monkeypatch.setattr(server, "_APP_CONTEXT", None)

    async with server.app_lifespan(None) as first:
        pass
    async with server.app_lifespan(None) as second:
        pass
    assert first is second
    assert first.processes == {}  # same dict object across runs
    assert first.processes is second.processes
