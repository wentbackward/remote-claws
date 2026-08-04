"""Action dispatch machinery shared by all four tool groups.

Each group exposes ONE MCP tool (remote_browser, remote_desktop, remote_exec,
remote_files). The tool's `action` parameter selects a handler from a plain
dict; this module routes the call, validates required params, and enforces
action-level permissions at runtime.

Handlers are module-level functions whose first parameter is `app` (the
lifespan AppContext). Remaining parameters declare what the action needs:
params without defaults are required (and must be non-empty strings when
provided); params with defaults are optional. The dispatcher passes only the
params a handler actually declares, so each group's MCP tool can accept one
flat superset of optional params.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import Any, Protocol


class ActionPolicy(Protocol):
    """The slice of PermissionChecker the dispatcher needs (kept structural
    so tests can stub it without a permissions file)."""

    def is_action_allowed(self, group: str, action: str) -> bool: ...


Handler = Callable[..., Any]


def _error(**fields: Any) -> str:
    return json.dumps(fields)


async def run_action(
    *,
    group: str,
    handlers: dict[str, Handler],
    action: str,
    app: Any,
    params: dict[str, Any],
    permissions: ActionPolicy,
) -> Any:
    """Route one consolidated-tool call to its action handler.

    Never raises for user-facing problems: unknown actions, denied actions,
    and missing required params all return a JSON error string the agent can
    read and recover from. Handler return values (str or mcp Image) pass
    through untouched.
    """
    handler = handlers.get(action)
    if handler is None:
        return _error(
            error=f"unknown action {action!r}",
            valid_actions=sorted(handlers),
        )

    if not permissions.is_action_allowed(group, action):
        return _error(error=f"permission denied: {group}:{action}")

    sig = inspect.signature(handler)
    missing = [
        name
        for name, p in sig.parameters.items()
        if name != "app"
        and p.default is inspect.Parameter.empty
        and (params.get(name) is None or params.get(name) == "")
    ]
    if missing:
        return _error(
            error=f"action {action!r} requires params: {', '.join(missing)}",
        )

    accepted = {k: v for k, v in params.items() if k in sig.parameters}
    result = handler(app, **accepted)
    if inspect.isawaitable(result):
        result = await result
    return result
