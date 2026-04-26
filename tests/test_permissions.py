"""Test permission filtering: group activation, allow/deny, default-deny."""

import json

from remote_claws.permissions import PermissionChecker


def _make_perms(data: dict) -> dict:
    """Wrap raw group->rules dict in the top-level 'permissions' key."""
    return {"permissions": data}


def test_default_deny_all(tmp_path):
    """With no permissions.json, everything is denied."""
    checker = PermissionChecker(str(tmp_path / "missing.json"), enabled_groups=["browser"])
    assert checker.is_allowed("browser_navigate") is False


def test_allow_single_tool(tmp_path):
    perms = tmp_path / "perms.json"
    perms.write_text(json.dumps(_make_perms({"browser": {"allow": ["browser_navigate"]}})))
    checker = PermissionChecker(str(perms), enabled_groups=["browser"])
    assert checker.is_allowed("browser_navigate") is True
    assert checker.is_allowed("browser_click") is False  # not listed


def test_allow_all_tools(tmp_path):
    perms = tmp_path / "perms.json"
    perms.write_text(json.dumps(_make_perms({"browser": {"allow": ["*"]}})))
    checker = PermissionChecker(str(perms), enabled_groups=["browser"])
    assert checker.is_allowed("browser_navigate") is True
    assert checker.is_allowed("browser_click") is True


def test_deny_overrides_allow(tmp_path):
    perms = tmp_path / "perms.json"
    perms.write_text(json.dumps(_make_perms({"browser": {"allow": ["*"], "deny": ["browser_navigate"]}})))
    checker = PermissionChecker(str(perms), enabled_groups=["browser"])
    assert checker.is_allowed("browser_navigate") is False
    assert checker.is_allowed("browser_click") is True


def test_deny_all(tmp_path):
    perms = tmp_path / "perms.json"
    perms.write_text(json.dumps(_make_perms({"browser": {"allow": ["*"], "deny": ["*"]}})))
    checker = PermissionChecker(str(perms), enabled_groups=["browser"])
    assert checker.is_allowed("browser_navigate") is False


def test_is_group_active_respects_enabled_groups(tmp_path):
    perms = tmp_path / "perms.json"
    perms.write_text(
        json.dumps(
            _make_perms(
                {
                    "browser": {"allow": ["*"]},
                    "exec": {"allow": ["*"]},
                }
            )
        )
    )
    checker = PermissionChecker(str(perms), enabled_groups=["browser", "exec"])
    assert checker.is_group_active("browser") is True
    assert checker.is_group_active("exec") is True
    assert checker.is_group_active("desktop") is False
    assert checker.is_group_active("files") is False


def test_is_group_inactive_when_not_in_perms(tmp_path):
    perms = tmp_path / "perms.json"
    perms.write_text(json.dumps(_make_perms({"browser": {"allow": ["*"]}})))
    checker = PermissionChecker(str(perms), enabled_groups=["browser", "desktop"])
    # desktop is enabled but has no permissions entry → inactive
    assert checker.is_group_active("desktop") is False


def test_unknown_group_always_inactive(tmp_path):
    perms = tmp_path / "perms.json"
    perms.write_text(json.dumps(_make_perms({})))
    checker = PermissionChecker(str(perms), enabled_groups=["browser"])
    assert checker.is_group_active("nonexistent_group") is False


def test_tool_prefix_mapping(tmp_path):
    """Verify tool names map to correct groups via prefix."""
    perms = tmp_path / "perms.json"
    perms.write_text(
        json.dumps(
            _make_perms(
                {
                    "exec": {"allow": ["exec_run"]},
                    "files": {"allow": ["file_read"]},
                }
            )
        )
    )
    checker = PermissionChecker(str(perms), enabled_groups=["exec", "files"])
    assert checker.is_allowed("exec_run") is True
    assert checker.is_allowed("file_read") is True
    assert checker.is_allowed("exec_kill") is False  # not allowed
