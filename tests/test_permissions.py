"""Test permission filtering: group activation, action allow/deny, default-deny."""

import json

from remote_claws.permissions import PermissionChecker


def _make_perms(data: dict) -> dict:
    """Wrap raw group->rules dict in the top-level 'permissions' key."""
    return {"permissions": data}


def _write(tmp_path, data: dict) -> str:
    perms = tmp_path / "perms.json"
    perms.write_text(json.dumps(_make_perms(data)))
    return str(perms)


def test_default_deny_all(tmp_path):
    """With no permissions.json, everything is denied."""
    checker = PermissionChecker(str(tmp_path / "missing.json"), enabled_groups=["browser"])
    assert checker.is_action_allowed("browser", "navigate") is False


def test_allow_single_action(tmp_path):
    checker = PermissionChecker(
        _write(tmp_path, {"browser": {"allow": ["navigate"]}}),
        enabled_groups=["browser"],
    )
    assert checker.is_action_allowed("browser", "navigate") is True
    assert checker.is_action_allowed("browser", "click") is False  # not listed


def test_allow_all_actions(tmp_path):
    checker = PermissionChecker(
        _write(tmp_path, {"browser": {"allow": ["*"]}}),
        enabled_groups=["browser"],
    )
    assert checker.is_action_allowed("browser", "navigate") is True
    assert checker.is_action_allowed("browser", "click") is True


def test_deny_overrides_allow(tmp_path):
    checker = PermissionChecker(
        _write(tmp_path, {"browser": {"allow": ["*"], "deny": ["eval_js"]}}),
        enabled_groups=["browser"],
    )
    assert checker.is_action_allowed("browser", "eval_js") is False
    assert checker.is_action_allowed("browser", "navigate") is True


def test_deny_star_blocks_everything(tmp_path):
    checker = PermissionChecker(
        _write(tmp_path, {"exec": {"allow": ["*"], "deny": ["*"]}}),
        enabled_groups=["exec"],
    )
    assert checker.is_action_allowed("exec", "run") is False


def test_unknown_group_denied(tmp_path):
    checker = PermissionChecker(
        _write(tmp_path, {"browser": {"allow": ["*"]}}),
        enabled_groups=["browser"],
    )
    assert checker.is_action_allowed("nosuch", "navigate") is False


def test_disabled_group_denied_even_when_allowed(tmp_path):
    checker = PermissionChecker(
        _write(tmp_path, {"browser": {"allow": ["*"]}}),
        enabled_groups=["exec"],
    )
    assert checker.is_action_allowed("browser", "navigate") is False


def test_legacy_tool_names_normalized(tmp_path):
    """Old-style entries (browser_navigate, exec_run, file_read) keep working."""
    checker = PermissionChecker(
        _write(tmp_path, {
            "browser": {"allow": ["browser_navigate"]},
            "exec": {"allow": ["*"], "deny": ["exec_kill"]},
            "files": {"allow": ["file_read"]},
        }),
        enabled_groups=["browser", "exec", "files"],
    )
    assert checker.is_action_allowed("browser", "navigate") is True
    assert checker.is_action_allowed("browser", "click") is False
    assert checker.is_action_allowed("exec", "kill") is False
    assert checker.is_action_allowed("exec", "run") is True
    assert checker.is_action_allowed("files", "read") is True
    assert checker.is_action_allowed("files", "write") is False


def test_is_group_active_unchanged(tmp_path):
    checker = PermissionChecker(
        _write(tmp_path, {"browser": {"allow": ["*"]}, "exec": {"deny": ["*"]}}),
        enabled_groups=None,
    )
    assert checker.is_group_active("browser") is True
    assert checker.is_group_active("exec") is False  # wholesale deny
    assert checker.is_group_active("desktop") is False  # no entry
    assert checker.is_group_active("nosuch") is False
