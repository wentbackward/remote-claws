from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

ALL_GROUPS: tuple[str, ...] = ("browser", "desktop", "exec", "files")

# Pre-consolidation permissions.json entries were full tool names
# (browser_navigate, exec_run, file_read, ...). Action names are now bare
# (navigate, run, read). Strip the legacy prefix at load so existing policy
# files keep working; a warning nudges operators to update the file.
LEGACY_PREFIXES: dict[str, str] = {
    "browser": "browser_",
    "desktop": "desktop_",
    "exec": "exec_",
    "files": "file_",
}


class PermissionChecker:
    """Loads the policy in permissions.json and answers two questions:

    - is_group_active(group): should this group's tool be registered at all?
      Consulted at registration time — an inactive group means the tool is
      never exposed to clients and its heavy deps are never imported.
    - is_action_allowed(group, action): may this action run? Consulted by
      the dispatcher at call time, because one tool per group can no longer
      hide individual actions from tools/list. Deny always supersedes allow.
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
        self._normalize_legacy_entries()
        logger.info("Loaded permissions from %s", path)

    def _normalize_legacy_entries(self) -> None:
        for group, rules in self._permissions.items():
            prefix = LEGACY_PREFIXES.get(group)
            if not prefix:
                continue
            for key in ("allow", "deny"):
                entries = rules.get(key) or []
                normalized = []
                for entry in entries:
                    if entry != "*" and entry.startswith(prefix):
                        stripped = entry[len(prefix) :]
                        logger.warning(
                            "permissions.json: legacy entry %r in group %r — rename to the bare action name %r",
                            entry,
                            group,
                            stripped,
                        )
                        entry = stripped
                    normalized.append(entry)
                rules[key] = normalized

    def is_group_active(self, group: str) -> bool:
        """True if the group is both enabled at startup and has a permissions
        entry that could ever permit at least one action. Used to decide
        whether to import a group's heavy dependencies and register its tool."""
        if group not in ALL_GROUPS:
            return False
        if self._enabled_groups is not None and group not in self._enabled_groups:
            return False

        group_perms = self._permissions.get(group)
        if group_perms is None:
            return False

        deny = group_perms.get("deny", []) or []
        allow = group_perms.get("allow", []) or []

        # If everything is denied wholesale, the group can't have any active action.
        if "*" in deny:
            return False
        # The group must permit at least one specific action or all actions.
        return bool(allow)

    def is_action_allowed(self, group: str, action: str) -> bool:
        """True if this action may execute. Deny entries always supersede
        allow entries. The startup ``enabled_groups`` filter, if set, blocks
        whole groups regardless of what the JSON file says."""
        if group not in ALL_GROUPS:
            return False
        if self._enabled_groups is not None and group not in self._enabled_groups:
            return False

        group_perms = self._permissions.get(group)
        if group_perms is None:
            return False

        deny = group_perms.get("deny", []) or []
        allow = group_perms.get("allow", []) or []

        if action in deny or "*" in deny:
            return False
        return bool(action in allow or "*" in allow)
