from __future__ import annotations

import json
import logging
from pathlib import Path
from collections.abc import Iterable

logger = logging.getLogger(__name__)

# Group prefix mapping: tool name prefix -> group key in permissions.json.
# This is the single source of truth for which groups exist.
GROUP_PREFIXES: dict[str, str] = {
    "browser_": "browser",
    "desktop_": "desktop",
    "exec_": "exec",
    "file_": "files",
}

ALL_GROUPS: tuple[str, ...] = tuple(GROUP_PREFIXES.values())


class PermissionChecker:
    """Loads the policy in permissions.json and answers two questions:

    - is_allowed(tool_name): is this specific tool permitted?
    - is_group_active(group): could any tool in this group ever be permitted?

    The checker is evaluated at tool registration time, so disallowed tools are
    never exposed to clients. There is no runtime re-check — the policy is
    fixed for the lifetime of the process.
    """

    def __init__(
        self,
        permissions_file: str = "permissions.json",
        enabled_groups: Iterable[str] | None = None,
    ):
        self._permissions: dict[str, dict[str, list[str]]] = {}
        # None means "no startup-level group filter" (every group is enabled
        # subject to permissions). An explicit iterable narrows it.
        self._enabled_groups: set[str] | None = None if enabled_groups is None else {g for g in enabled_groups}
        self._load(permissions_file)

    def _load(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            logger.warning("Permissions file %s not found — defaulting to deny-all", path)
            return
        with open(p) as f:
            data = json.load(f)
        self._permissions = data.get("permissions", {})
        logger.info("Loaded permissions from %s", path)

    def _group_for(self, tool_name: str) -> str | None:
        for prefix, group in GROUP_PREFIXES.items():
            if tool_name.startswith(prefix):
                return group
        return None

    def is_group_active(self, group: str) -> bool:
        """True if the group is both enabled at startup and has a permissions
        entry that could ever permit at least one tool. Used to decide whether
        to import a group's heavy dependencies and call its register()."""
        if group not in ALL_GROUPS:
            return False
        if self._enabled_groups is not None and group not in self._enabled_groups:
            return False

        group_perms = self._permissions.get(group)
        if group_perms is None:
            return False

        deny = group_perms.get("deny", []) or []
        allow = group_perms.get("allow", []) or []

        # If everything is denied wholesale, the group can't have any active tool.
        if "*" in deny:
            return False
        # The group must permit at least one specific tool or all tools.
        return bool(allow)

    def is_allowed(self, tool_name: str) -> bool:
        """True if this specific tool may be exposed.

        Deny entries always supersede allow entries. The startup
        ``enabled_groups`` filter, if set, hides whole groups regardless of
        what the JSON file says.
        """
        group = self._group_for(tool_name)
        if group is None:
            return False
        if self._enabled_groups is not None and group not in self._enabled_groups:
            return False

        group_perms = self._permissions.get(group)
        if group_perms is None:
            return False

        deny = group_perms.get("deny", []) or []
        allow = group_perms.get("allow", []) or []

        if tool_name in deny or "*" in deny:
            return False
        return bool(tool_name in allow or "*" in allow)
