"""Each active group registers exactly one remote_* tool; inactive groups none."""

import asyncio
import json

import pytest
from mcp.server.fastmcp import FastMCP

from remote_claws.permissions import PermissionChecker


def _checker(tmp_path, groups: dict, enabled=None) -> PermissionChecker:
    perms = tmp_path / "perms.json"
    perms.write_text(json.dumps({"permissions": groups}))
    return PermissionChecker(str(perms), enabled_groups=enabled)


def _tool_names(mcp: FastMCP) -> list[str]:
    return sorted(t.name for t in asyncio.run(mcp.list_tools()))


def test_files_group_registers_remote_files(tmp_path):
    from remote_claws.files.tools import register

    mcp = FastMCP("t")
    register(mcp, _checker(tmp_path, {"files": {"allow": ["*"]}}))
    assert _tool_names(mcp) == ["remote_files"]


def test_exec_group_registers_remote_exec(tmp_path):
    from remote_claws.exec.tools import register

    mcp = FastMCP("t")
    register(mcp, _checker(tmp_path, {"exec": {"allow": ["*"]}}))
    assert _tool_names(mcp) == ["remote_exec"]


def test_browser_group_registers_remote_browser(tmp_path):
    from remote_claws.browser.tools import register

    mcp = FastMCP("t")
    register(mcp, _checker(tmp_path, {"browser": {"allow": ["*"]}}))
    assert _tool_names(mcp) == ["remote_browser"]


def test_desktop_group_registers_remote_desktop(tmp_path):
    # register() imports pyautogui, which fails on headless Linux (CI) —
    # skip there; the Windows dev/host path exercises it for real.
    try:
        import pyautogui  # noqa: F401
    except Exception:
        pytest.skip("pyautogui unavailable on this platform/display")

    from remote_claws.desktop.tools import register

    mcp = FastMCP("t")
    register(mcp, _checker(tmp_path, {"desktop": {"allow": ["*"]}}))
    assert _tool_names(mcp) == ["remote_desktop"]
