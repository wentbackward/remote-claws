from __future__ import annotations

import json
import logging
from pathlib import Path
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Group prefix mapping: tool name prefix -> group key in permissions.json
GROUP_PREFIXES = {
    "browser_": "browser",
    "desktop_": "desktop",
    "exec_": "exec",
    "file_": "files",
}


class PermissionChecker:
    def __init__(self, permissions_file: str = "permissions.json"):
        self._permissions: dict[str, dict[str, list[str]]] = {}
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

    def _get_group(self, tool_name: str) -> str | None:
        for prefix, group in GROUP_PREFIXES.items():
            if tool_name.startswith(prefix):
                return group
        return None

    def is_allowed(self, tool_name: str) -> bool:
        group = self._get_group(tool_name)
        if group is None:
            return False

        group_perms = self._permissions.get(group)
        if group_perms is None:
            return False

        deny = group_perms.get("deny", [])
        allow = group_perms.get("allow", [])

        # Deny always supersedes allow
        if tool_name in deny or "*" in deny:
            return False

        if tool_name in allow or "*" in allow:
            return True

        return False


def require_permission(checker: PermissionChecker, tool_name: str) -> Callable:
    """Decorator that checks permissions before running a tool function."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not checker.is_allowed(tool_name):
                return f"Permission denied: {tool_name} is not allowed by server policy"
            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not checker.is_allowed(tool_name):
                return f"Permission denied: {tool_name} is not allowed by server policy"
            return func(*args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
