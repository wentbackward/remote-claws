# Tool Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse remote-claws' 39 MCP tools into 4 action-dispatch tools (`remote_browser`, `remote_desktop`, `remote_exec`, `remote_files`) to fix agent tool overload and local/remote tool-name confusion.

**Architecture:** One MCP tool per group. Each tool takes `action: str` plus a flat set of optional params; a shared dispatcher (`dispatch.py`) routes to module-level handler functions, validates required params, and enforces action-level permissions at runtime. Group-level permission gating stays at registration time (a denied group = tool never registered). Docstrings become CLI-style man pages — the primary guidance surface for the LLM.

**Tech Stack:** Python 3.11+, mcp[cli] FastMCP, pytest, ruff.

**Key decisions (validated before planning):**
- FastMCP rejects `-> str | Image` union returns (pydantic can't schema `Image`). Tools with screenshot actions annotate `-> Any`; FastMCP's `_convert_to_content` correctly emits `TextContent` for `str` and `ImageContent` for `Image` at runtime. Pure-text tools keep `-> str`.
- No backward-compat tool aliases (would defeat the purpose). `permissions.json` legacy entries (`browser_navigate`) ARE auto-normalized to bare action names (`navigate`) at load with a deprecation warning — zero-downtime policy migration.
- OpenClaw namespaces MCP tools as `remote-claws__<name>`; our `remote_*` names compose safely with any client's prefixing scheme.
- Empty-string param values count as "missing" for required params. Documented workaround for clearing an input: `eval_js`.

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `src/remote_claws/dispatch.py` | **Create** | Action routing, param validation, runtime permission check |
| `src/remote_claws/permissions.py` | Modify | `is_action_allowed(group, action)`, legacy entry normalization |
| `src/remote_claws/files/tools.py` | Rewrite | `remote_files` tool + 6 module-level handlers |
| `src/remote_claws/exec/tools.py` | Rewrite | `remote_exec` tool + 5 handlers |
| `src/remote_claws/browser/tools.py` | Rewrite | `remote_browser` tool + 16 handlers |
| `src/remote_claws/desktop/tools.py` | Rewrite | `remote_desktop` tool + 12 handlers; imports move to module top |
| `src/remote_claws/server.py` | Modify | `SERVER_INSTRUCTIONS` rewrite |
| `tests/test_dispatch.py` | **Create** | Dispatcher unit tests |
| `tests/test_permissions.py` | Rewrite | Action-level policy + legacy normalization |
| `tests/test_files_tools.py` | **Create** | File handler tests (real tmp files) |
| `tests/test_exec_tools.py` | **Create** | Exec handler tests (real subprocesses) |
| `tests/test_tool_registration.py` | **Create** | FastMCP registration gating per group |
| `tests/test_server.py` | Modify | Drop `is_allowed` usage |
| `scripts/smoke_browser.py` | Modify | Call `remote_browser` with `action` param |
| `TOOLS.md` | Rewrite | 4-tool action reference |
| `README.md` | Modify | Counts, permission format, examples |
| `CLAUDE.md` | Modify | Two-tier permission model, tool count |
| `SKILLS.md` | Rewrite | Capability overview with new names |
| `openclaw/SKILL.md` | Rewrite | OpenClaw skill + local/remote disambiguation rule |
| `remote-claws-openclaw-setup-guide.md` | Modify | "39 tools" → "4 tools" |

Action inventory (39): browser = navigate, click, fill, type, press_key, get_text, get_html, eval_js, screenshot, wait_for, select_option, go_back, go_forward, tabs_list, tab_new, tab_close (16). desktop = screenshot, mouse_click, mouse_move, mouse_drag, type_text, press_key, scroll, find_window, focus_window, list_elements, click_element, get_element_text (12). exec = run, get_output, send_input, kill, list (5). files = write, read, list, delete, move, info (6).

---

### Task 1: Shared dispatch helper

**Files:**
- Create: `src/remote_claws/dispatch.py`
- Test: `tests/test_dispatch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dispatch.py
"""Test the action dispatcher: routing, validation, permission checks."""

import json

import pytest

from remote_claws.dispatch import run_action


class _AllowAll:
    def is_action_allowed(self, group, action):
        return True


class _DenyAll:
    def is_action_allowed(self, group, action):
        return False


def _h_ping(app):
    return "pong"


def _h_greet(app, name: str):
    return f"hi {name}"


async def _h_async(app, value: str = "default"):
    return f"async:{value}"


_HANDLERS = {"ping": _h_ping, "greet": _h_greet, "async_": _h_async}


@pytest.mark.asyncio
async def test_routes_to_sync_handler():
    result = await run_action(
        group="g", handlers=_HANDLERS, action="ping",
        app=None, params={}, permissions=_AllowAll(),
    )
    assert result == "pong"


@pytest.mark.asyncio
async def test_routes_to_async_handler_and_filters_params():
    result = await run_action(
        group="g", handlers=_HANDLERS, action="async_",
        app=None, params={"value": "x", "unrelated": "ignored"},
        permissions=_AllowAll(),
    )
    assert result == "async:x"


@pytest.mark.asyncio
async def test_unknown_action_returns_valid_list():
    result = await run_action(
        group="g", handlers=_HANDLERS, action="nope",
        app=None, params={}, permissions=_AllowAll(),
    )
    data = json.loads(result)
    assert "unknown action" in data["error"]
    assert data["valid_actions"] == ["async_", "greet", "ping"]


@pytest.mark.asyncio
async def test_denied_action_returns_error_string():
    result = await run_action(
        group="browser", handlers=_HANDLERS, action="ping",
        app=None, params={}, permissions=_DenyAll(),
    )
    assert json.loads(result)["error"] == "permission denied: browser:ping"


@pytest.mark.asyncio
async def test_missing_required_param_rejected():
    for bad in ({}, {"name": ""}, {"name": None}):
        result = await run_action(
            group="g", handlers=_HANDLERS, action="greet",
            app=None, params=bad, permissions=_AllowAll(),
        )
        assert "requires params: name" in json.loads(result)["error"]


@pytest.mark.asyncio
async def test_app_is_injected():
    seen = {}

    def h_capture(app):
        seen["app"] = app
        return "ok"

    await run_action(
        group="g", handlers={"cap": h_capture}, action="cap",
        app="SENTINEL", params={}, permissions=_AllowAll(),
    )
    assert seen["app"] == "SENTINEL"


@pytest.mark.asyncio
async def test_non_string_result_passes_through_untouched():
    sentinel = object()

    def h_obj(app):
        return sentinel

    result = await run_action(
        group="g", handlers={"obj": h_obj}, action="obj",
        app=None, params={}, permissions=_AllowAll(),
    )
    assert result is sentinel
```

Add to `pyproject.toml` (needed for `@pytest.mark.asyncio`):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dispatch.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'remote_claws.dispatch'`

- [ ] **Step 3: Implement the dispatcher**

```python
# src/remote_claws/dispatch.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dispatch.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/remote_claws/dispatch.py tests/test_dispatch.py pyproject.toml
git commit -m "feat: add shared action dispatcher for consolidated tools"
```

---

### Task 2: Action-level permissions + legacy normalization

**Files:**
- Modify: `src/remote_claws/permissions.py`
- Test: `tests/test_permissions.py` (rewrite)

- [ ] **Step 1: Rewrite the failing tests**

Replace `tests/test_permissions.py` entirely:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_permissions.py -q`
Expected: FAIL — `AttributeError: 'PermissionChecker' object has no attribute 'is_action_allowed'`

- [ ] **Step 3: Rewrite permissions.py**

Replace the whole file:

```python
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
                        stripped = entry[len(prefix):]
                        logger.warning(
                            "permissions.json: legacy entry %r in group %r — "
                            "rename to the bare action name %r",
                            entry, group, stripped,
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
```

- [ ] **Step 4: Run tests — but note test_server.py also uses the old API**

Run: `.venv/Scripts/python.exe -m pytest tests/test_permissions.py -q`
Expected: 9 passed

Then fix `tests/test_server.py`'s `test_permissions_checker_created_at_startup` — replace its body:

```python
def test_permissions_checker_created_at_startup(tmp_path):
    """Permissions checker should be created from config."""
    perms_file = tmp_path / "perms.json"
    perms_file.write_text(json.dumps(_make_perms({"browser": {"allow": ["navigate"]}})))
    cfg = AppConfig(permissions_file=str(perms_file))
    checker = PermissionChecker(cfg.permissions_file, enabled_groups=cfg.get_enabled_groups())
    assert checker.is_action_allowed("browser", "navigate") is True
    assert checker.is_action_allowed("browser", "click") is False  # not in perms
```

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/remote_claws/permissions.py tests/test_permissions.py tests/test_server.py
git commit -m "feat: action-level permission checks with legacy entry normalization"
```

---

### Task 3: `remote_files` tool

**Files:**
- Rewrite: `src/remote_claws/files/tools.py`
- Test: `tests/test_files_tools.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_tools.py
"""Test file action handlers against real files in tmp_path."""

import base64
import json
from types import SimpleNamespace

import pytest

from remote_claws.dispatch import run_action
from remote_claws.files.tools import HANDLERS


class _AllowAll:
    def is_action_allowed(self, group, action):
        return True


async def _call(action: str, **params):
    full = {"path": "", "content_base64": "", "make_dirs": True, "offset": 0,
            "limit": 0, "pattern": "*", "recursive": False, "src": "", "dst": ""}
    full.update(params)
    # files handlers ignore app; SimpleNamespace documents that explicitly
    return await run_action(group="files", handlers=HANDLERS, action=action,
                            app=SimpleNamespace(), params=full, permissions=_AllowAll())


@pytest.mark.asyncio
async def test_write_then_read_roundtrip(tmp_path):
    target = str(tmp_path / "sub" / "hello.txt")
    payload = base64.b64encode(b"hello world").decode()

    write_result = json.loads(await _call("write", path=target, content_base64=payload))
    assert write_result["status"] == "written"
    assert write_result["bytes"] == 11

    read_result = json.loads(await _call("read", path=target))
    assert base64.b64decode(read_result["content_base64"]) == b"hello world"
    assert read_result["size"] == 11


@pytest.mark.asyncio
async def test_read_with_offset_and_limit(tmp_path):
    target = tmp_path / "data.bin"
    target.write_bytes(b"0123456789")
    result = json.loads(await _call("read", path=str(target), offset=2, limit=4))
    assert base64.b64decode(result["content_base64"]) == b"2345"
    assert result["bytes_read"] == 4


@pytest.mark.asyncio
async def test_read_missing_file(tmp_path):
    result = json.loads(await _call("read", path=str(tmp_path / "nope.txt")))
    assert "File not found" in result["error"]


@pytest.mark.asyncio
async def test_list_with_pattern(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.log").write_text("b")
    result = json.loads(await _call("list", path=str(tmp_path), pattern="*.txt"))
    assert [r["path"].endswith("a.txt") for r in result] == [True]


@pytest.mark.asyncio
async def test_move_and_info_and_delete(tmp_path):
    src = tmp_path / "old.txt"
    src.write_text("x")
    dst = tmp_path / "newdir" / "new.txt"

    move_result = json.loads(await _call("move", src=str(src), dst=str(dst)))
    assert move_result["status"] == "moved"
    assert dst.exists() and not src.exists()

    info = json.loads(await _call("info", path=str(dst)))
    assert info["exists"] is True and info["is_dir"] is False

    delete = json.loads(await _call("delete", path=str(dst)))
    assert delete["status"] == "deleted"
    assert not dst.exists()


@pytest.mark.asyncio
async def test_write_requires_content(tmp_path):
    result = json.loads(await _call("write", path=str(tmp_path / "x.txt")))
    assert "requires params: content_base64" in result["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_files_tools.py -q`
Expected: FAIL — `ImportError: cannot import name 'HANDLERS' from 'remote_claws.files.tools'`

- [ ] **Step 3: Rewrite files/tools.py**

```python
from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from remote_claws.dispatch import Handler, run_action
from remote_claws.permissions import PermissionChecker


def h_write(app: Any, path: str, content_base64: str, make_dirs: bool = True) -> str:
    data = base64.b64decode(content_base64)
    p = Path(path)
    if make_dirs:
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return json.dumps({"status": "written", "path": str(p.resolve()), "bytes": len(data)})


def h_read(app: Any, path: str, offset: int = 0, limit: int = 0) -> str:
    p = Path(path)
    if not p.exists():
        return json.dumps({"error": f"File not found: {path}"})

    file_size = p.stat().st_size
    with open(p, "rb") as f:
        if offset > 0:
            f.seek(offset)
        data = f.read(limit) if limit > 0 else f.read()

    return json.dumps({
        "path": str(p.resolve()),
        "size": file_size,
        "offset": offset,
        "bytes_read": len(data),
        "content_base64": base64.b64encode(data).decode(),
    })


def h_list(app: Any, path: str = ".", pattern: str = "*", recursive: bool = False) -> str:
    p = Path(path)
    if not p.exists():
        return json.dumps({"error": f"Path not found: {path}"})

    entries = list(p.rglob(pattern)) if recursive else list(p.glob(pattern))

    results = []
    for entry in entries[:500]:  # cap results
        try:
            stat = entry.stat()
            results.append({
                "path": str(entry),
                "is_dir": entry.is_dir(),
                "size": stat.st_size if not entry.is_dir() else None,
                "modified": stat.st_mtime,
            })
        except OSError:
            continue
    return json.dumps(results, indent=2)


def h_delete(app: Any, path: str) -> str:
    p = Path(path)
    if not p.exists():
        return json.dumps({"error": f"Not found: {path}"})

    if p.is_dir():
        p.rmdir()
    else:
        p.unlink()
    return json.dumps({"status": "deleted", "path": str(p.resolve())})


def h_move(app: Any, src: str, dst: str) -> str:
    src_p = Path(src)
    if not src_p.exists():
        return json.dumps({"error": f"Source not found: {src}"})

    dst_p = Path(dst)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src_p), str(dst_p))
    return json.dumps({"status": "moved", "src": str(src_p.resolve()), "dst": str(dst_p.resolve())})


def h_info(app: Any, path: str) -> str:
    p = Path(path)
    if not p.exists():
        return json.dumps({"exists": False, "path": path})

    stat = p.stat()
    return json.dumps({
        "exists": True,
        "path": str(p.resolve()),
        "is_dir": p.is_dir(),
        "size": stat.st_size,
        "modified": stat.st_mtime,
        "created": stat.st_ctime,
    })


HANDLERS: dict[str, Handler] = {
    "write": h_write,
    "read": h_read,
    "list": h_list,
    "delete": h_delete,
    "move": h_move,
    "info": h_info,
}


def register(mcp: FastMCP, permissions: PermissionChecker) -> None:
    """Register the single remote_files tool when the files group is active."""

    @mcp.tool()
    async def remote_files(
        action: str,
        path: str = "",
        content_base64: str = "",
        make_dirs: bool = True,
        offset: int = 0,
        limit: int = 0,
        pattern: str = "*",
        recursive: bool = False,
        src: str = "",
        dst: str = "",
        ctx: Context = None,
    ) -> str:
        """Read and write files on the REMOTE machine. Binary content is base64-encoded.

Actions (params not listed for an action are ignored):

  read path=<path> [offset=0] [limit=0]
      Return file content as {path, size, offset, bytes_read, content_base64}.
      limit=0 reads the whole file; use offset/limit to chunk large files.
  write path=<path> content_base64=<b64> [make_dirs=true]
      Write decoded bytes to path; creates parent dirs when make_dirs.
  list [path=.] [pattern=*] [recursive=false]
      Glob listing with {path, is_dir, size, modified}. Capped at 500 entries.
  delete path=<path>
      Delete a file or EMPTY directory.
  move src=<path> dst=<path>
      Move/rename; creates destination parent dirs.
  info path=<path>
      {exists, is_dir, size, modified, created}.

Unknown actions return the valid action list. Denied actions return a
permission error — do not retry them.
"""
        app = ctx.request_context.lifespan_context
        return await run_action(
            group="files",
            handlers=HANDLERS,
            action=action,
            app=app,
            params={
                "path": path,
                "content_base64": content_base64,
                "make_dirs": make_dirs,
                "offset": offset,
                "limit": limit,
                "pattern": pattern,
                "recursive": recursive,
                "src": src,
                "dst": dst,
            },
            permissions=permissions,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_files_tools.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/remote_claws/files/tools.py tests/test_files_tools.py
git commit -m "feat: consolidate files group into remote_files action tool"
```

---

### Task 4: `remote_exec` tool

**Files:**
- Rewrite: `src/remote_claws/exec/tools.py`
- Test: `tests/test_exec_tools.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_exec_tools.py
"""Test exec action handlers with real subprocesses."""

import json
import sys
from types import SimpleNamespace

import pytest

from remote_claws.dispatch import run_action
from remote_claws.exec.tools import HANDLERS


class _AllowAll:
    def is_action_allowed(self, group, action):
        return True


@pytest.fixture
def app():
    return SimpleNamespace(processes={})


async def _call(app, action: str, **params):
    full = {"command": "", "args": None, "cwd": None, "timeout": 0, "shell": False,
            "process_id": "", "wait": False, "input_text": ""}
    full.update(params)
    return await run_action(group="exec", handlers=HANDLERS, action=action,
                            app=app, params=full, permissions=_AllowAll())


@pytest.mark.asyncio
async def test_run_and_get_output(app):
    started = json.loads(await _call(app, "run", command=sys.executable,
                                     args=["-c", "print('hello'); import sys; print('oops', file=sys.stderr)"]))
    proc_id = started["process_id"]
    assert started["status"] == "running"

    out = json.loads(await _call(app, "get_output", process_id=proc_id, wait=True, timeout=15))
    assert out["running"] is False
    assert out["exit_code"] == 0
    assert "hello" in out["stdout"]
    assert "oops" in out["stderr"]


@pytest.mark.asyncio
async def test_list_shows_tracked_process(app):
    started = json.loads(await _call(app, "run", command=sys.executable, args=["-c", "pass"]))
    listed = json.loads(await _call(app, "list"))
    assert any(p["process_id"] == started["process_id"] for p in listed)
    out = json.loads(await _call(app, "get_output", process_id=started["process_id"], wait=True, timeout=15))
    assert out["exit_code"] == 0


@pytest.mark.asyncio
async def test_send_input_roundtrip(app):
    started = json.loads(await _call(app, "run", command=sys.executable,
                                     args=["-c", "line = input(); print(f'got:{line}')"]))
    proc_id = started["process_id"]
    sent = json.loads(await _call(app, "send_input", process_id=proc_id, input_text="ping"))
    assert sent["status"] == "input sent"
    out = json.loads(await _call(app, "get_output", process_id=proc_id, wait=True, timeout=15))
    assert "got:ping" in out["stdout"]


@pytest.mark.asyncio
async def test_kill_running_process(app):
    started = json.loads(await _call(app, "run", command=sys.executable,
                                     args=["-c", "import time; time.sleep(60)"]))
    proc_id = started["process_id"]
    killed = json.loads(await _call(app, "kill", process_id=proc_id))
    assert killed["status"] == "killed"
    assert killed["exit_code"] is not None


@pytest.mark.asyncio
async def test_unknown_process_id(app):
    result = json.loads(await _call(app, "get_output", process_id="deadbeef"))
    assert "No process found" in result["error"]


@pytest.mark.asyncio
async def test_shell_mode(app):
    started = json.loads(await _call(app, "run", command="echo shelled", shell=True))
    out = json.loads(await _call(app, "get_output", process_id=started["process_id"], wait=True, timeout=15))
    assert "shelled" in out["stdout"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_exec_tools.py -q`
Expected: FAIL — `ImportError: cannot import name 'HANDLERS'`

- [ ] **Step 3: Rewrite exec/tools.py**

Handler bodies are lifted verbatim from the current implementations, with `_get_ctx(ctx)` replaced by the injected `app`:

```python
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from remote_claws.dispatch import Handler, run_action
from remote_claws.permissions import PermissionChecker


async def h_run(
    app: Any,
    command: str,
    args: list[str] | None = None,
    cwd: str | None = None,
    timeout: int = 0,
    shell: bool = False,
) -> str:
    process_id = uuid.uuid4().hex[:8]
    stdout_buf: list[str] = []
    stderr_buf: list[str] = []

    if shell:
        proc = await asyncio.create_subprocess_shell(
            command if not args else f"{command} {' '.join(args)}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    else:
        cmd_list = [command] + (args or [])
        proc = await asyncio.create_subprocess_exec(
            *cmd_list,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

    app.processes[process_id] = {
        "process": proc,
        "command": command,
        "args": args or [],
        "stdout": stdout_buf,
        "stderr": stderr_buf,
        "timeout": timeout,
    }

    async def _read_stream(stream, buf):
        while True:
            line = await stream.readline()
            if not line:
                break
            buf.append(line.decode(errors="replace"))

    asyncio.create_task(_read_stream(proc.stdout, stdout_buf))
    asyncio.create_task(_read_stream(proc.stderr, stderr_buf))

    if timeout > 0:

        async def _auto_kill():
            await asyncio.sleep(timeout)
            if proc.returncode is None:
                proc.kill()

        asyncio.create_task(_auto_kill())

    return json.dumps({"process_id": process_id, "pid": proc.pid, "status": "running"})


async def h_get_output(app: Any, process_id: str, wait: bool = False, timeout: int = 30) -> str:
    proc_info = app.processes.get(process_id)
    if not proc_info:
        return json.dumps({"error": f"No process found with id: {process_id}"})

    proc = proc_info["process"]

    if wait and proc.returncode is None:
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

    # Small delay to let readers catch up
    await asyncio.sleep(0.1)

    return json.dumps({
        "process_id": process_id,
        "running": proc.returncode is None,
        "exit_code": proc.returncode,
        "stdout": "".join(proc_info["stdout"]),
        "stderr": "".join(proc_info["stderr"]),
    })


async def h_send_input(app: Any, process_id: str, input_text: str) -> str:
    proc_info = app.processes.get(process_id)
    if not proc_info:
        return json.dumps({"error": f"No process found with id: {process_id}"})

    proc = proc_info["process"]
    if proc.returncode is not None:
        return json.dumps({"error": "Process has already exited"})

    proc.stdin.write((input_text + "\n").encode())
    await proc.stdin.drain()
    return json.dumps({"status": "input sent", "process_id": process_id})


async def h_kill(app: Any, process_id: str) -> str:
    proc_info = app.processes.get(process_id)
    if not proc_info:
        return json.dumps({"error": f"No process found with id: {process_id}"})

    proc = proc_info["process"]
    if proc.returncode is not None:
        return json.dumps({"status": "already exited", "exit_code": proc.returncode})

    proc.kill()
    await proc.wait()
    return json.dumps({"status": "killed", "process_id": process_id, "exit_code": proc.returncode})


async def h_list(app: Any) -> str:
    result = []
    for pid, info in app.processes.items():
        proc = info["process"]
        result.append({
            "process_id": pid,
            "command": info["command"],
            "args": info["args"],
            "running": proc.returncode is None,
            "exit_code": proc.returncode,
            "pid": proc.pid,
        })
    return json.dumps(result, indent=2)


HANDLERS: dict[str, Handler] = {
    "run": h_run,
    "get_output": h_get_output,
    "send_input": h_send_input,
    "kill": h_kill,
    "list": h_list,
}


def register(mcp: FastMCP, permissions: PermissionChecker) -> None:
    """Register the single remote_exec tool when the exec group is active."""

    @mcp.tool()
    async def remote_exec(
        action: str,
        command: str = "",
        args: list[str] | None = None,
        cwd: str | None = None,
        timeout: int = 0,
        shell: bool = False,
        process_id: str = "",
        wait: bool = False,
        input_text: str = "",
        ctx: Context = None,
    ) -> str:
        """Run commands on the REMOTE machine. Processes are asynchronous: run returns
a process_id immediately; poll with get_output.

Actions (params not listed for an action are ignored):

  run command=<cmd> [args=["..."]] [cwd=<dir>] [timeout=0] [shell=false]
      Start a process; returns {process_id, pid, status}. shell=true runs via the
      system shell (pipes, redirects, builtins). timeout>0 auto-kills after N sec.
  get_output process_id=<id> [wait=false] [timeout=30]
      Accumulated stdout/stderr, running flag, exit code. wait=true blocks until
      the process exits or timeout elapses.
  send_input process_id=<id> input_text=<line>
      Write a line to stdin (newline appended automatically).
  kill process_id=<id>
      Terminate a running process.
  list
      All tracked processes with status.

Processes persist until killed or server shutdown — kill them when done.
"""
        app = ctx.request_context.lifespan_context
        return await run_action(
            group="exec",
            handlers=HANDLERS,
            action=action,
            app=app,
            params={
                "command": command,
                "args": args,
                "cwd": cwd,
                "timeout": timeout,
                "shell": shell,
                "process_id": process_id,
                "wait": wait,
                "input_text": input_text,
            },
            permissions=permissions,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_exec_tools.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/remote_claws/exec/tools.py tests/test_exec_tools.py
git commit -m "feat: consolidate exec group into remote_exec action tool"
```

---

### Task 5: `remote_browser` tool

**Files:**
- Rewrite: `src/remote_claws/browser/tools.py`
- Test: `tests/test_tool_registration.py` (shared with Task 6)

Note: browser handlers require a live BrowserManager, so handler-level unit tests are out of scope; correctness is covered by dispatch tests, registration tests, and `scripts/smoke_browser.py` (Task 8).

- [ ] **Step 1: Write the failing registration test**

```python
# tests/test_tool_registration.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tool_registration.py -q`
Expected: FAIL — files/exec pass after Tasks 3–4; browser/desktop fail (`remote_browser`/`remote_desktop` missing)

- [ ] **Step 3: Rewrite browser/tools.py**

Handler bodies are the current tool bodies with `_get_ctx(ctx)` → `app` and the `@expose` wrappers removed. Full file:

```python
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP, Image

from remote_claws.dispatch import Handler, run_action
from remote_claws.permissions import PermissionChecker
from remote_claws.screenshot import downscale_and_encode, make_save_path


async def h_navigate(
    app: Any,
    url: str,
    wait_until: str = "load",
    settle_ms: int = 0,
    timeout: int = 30000,
) -> str:
    import asyncio as _asyncio

    page = await app.browser.get_page()
    response = await page.goto(url, wait_until=wait_until, timeout=timeout)
    if settle_ms > 0:
        await _asyncio.sleep(settle_ms / 1000)
    status = response.status if response else "unknown"
    title = await page.title()
    return f"Navigated to {page.url} (title: {title}, status: {status})"


async def h_click(app: Any, selector: str, button: str = "left", click_count: int = 1) -> str:
    page = await app.browser.get_page()
    await page.click(selector, button=button, click_count=click_count, timeout=10000)
    return f"Clicked {selector} (button={button}, count={click_count})"


async def h_fill(app: Any, selector: str, value: str) -> str:
    page = await app.browser.get_page()
    await page.fill(selector, value, timeout=10000)
    return f"Filled {selector} with value ({len(value)} chars)"


async def h_type(app: Any, selector: str, text: str, delay: int = 0) -> str:
    page = await app.browser.get_page()
    await page.type(selector, text, delay=delay, timeout=10000)
    return f"Typed {len(text)} characters into {selector}"


async def h_press_key(app: Any, key: str) -> str:
    page = await app.browser.get_page()
    await page.keyboard.press(key)
    return f"Pressed key: {key}"


async def h_get_text(app: Any, selector: str = "body") -> str:
    page = await app.browser.get_page()
    return await page.inner_text(selector, timeout=10000)


async def h_get_html(app: Any, selector: str = "html", outer: bool = True) -> str:
    page = await app.browser.get_page()
    if outer:
        return await page.locator(selector).evaluate("el => el.outerHTML")
    return await page.inner_html(selector, timeout=10000)


async def h_eval_js(app: Any, expression: str) -> str:
    page = await app.browser.get_page()
    result = await page.evaluate(expression)
    return json.dumps(result, default=str)


async def h_screenshot(
    app: Any,
    selector: str = "",
    full_page: bool = False,
    save_to_disk: bool = False,
) -> Image:
    page = await app.browser.get_page()
    if selector:
        raw = await page.locator(selector).screenshot()
    else:
        raw = await page.screenshot(full_page=full_page)
    save_path = make_save_path(app.config.screenshot_dir) if save_to_disk else None
    jpeg_bytes, saved = downscale_and_encode(
        raw,
        max_width=app.config.screenshot_max_width,
        max_height=app.config.screenshot_max_height,
        quality=app.config.screenshot_quality,
        save_path=save_path,
    )
    return Image(data=jpeg_bytes, format="jpeg")


async def h_wait_for(app: Any, selector: str, state: str = "visible", timeout: int = 10000) -> str:
    page = await app.browser.get_page()
    await page.wait_for_selector(selector, state=state, timeout=timeout)
    return f"Element {selector} reached state: {state}"


async def h_select_option(app: Any, selector: str, value: str) -> str:
    page = await app.browser.get_page()
    selected = await page.select_option(selector, value, timeout=10000)
    return f"Selected option: {selected}"


async def h_go_back(app: Any) -> str:
    page = await app.browser.get_page()
    await page.go_back(wait_until="domcontentloaded")
    title = await page.title()
    return f"Navigated back to {page.url} (title: {title})"


async def h_go_forward(app: Any) -> str:
    page = await app.browser.get_page()
    await page.go_forward(wait_until="domcontentloaded")
    title = await page.title()
    return f"Navigated forward to {page.url} (title: {title})"


async def h_tabs_list(app: Any) -> str:
    tabs = app.browser.list_tabs()
    for tab in tabs:
        page = app.browser._pages[tab["index"]]
        try:
            tab["title"] = await page.title()
        except Exception:
            tab["title"] = "(unknown)"
    return json.dumps(tabs, indent=2)


async def h_tab_new(app: Any, url: str = "about:blank") -> str:
    page = await app.browser.new_tab(url)
    title = await page.title()
    return f"Opened new tab: {page.url} (title: {title})"


async def h_tab_close(app: Any, index: int = -1) -> str:
    await app.browser.close_tab(index)
    remaining = len(app.browser._pages)
    return f"Closed tab {index}. {remaining} tab(s) remaining."


HANDLERS: dict[str, Handler] = {
    "navigate": h_navigate,
    "click": h_click,
    "fill": h_fill,
    "type": h_type,
    "press_key": h_press_key,
    "get_text": h_get_text,
    "get_html": h_get_html,
    "eval_js": h_eval_js,
    "screenshot": h_screenshot,
    "wait_for": h_wait_for,
    "select_option": h_select_option,
    "go_back": h_go_back,
    "go_forward": h_go_forward,
    "tabs_list": h_tabs_list,
    "tab_new": h_tab_new,
    "tab_close": h_tab_close,
}


def register(mcp: FastMCP, permissions: PermissionChecker) -> None:
    """Register the single remote_browser tool when the browser group is active."""

    @mcp.tool()
    async def remote_browser(
        action: str,
        url: str = "",
        selector: str = "",
        value: str = "",
        text: str = "",
        key: str = "",
        expression: str = "",
        button: str = "left",
        click_count: int = 1,
        delay: int = 0,
        state: str = "visible",
        timeout: int = 10000,
        wait_until: str = "load",
        settle_ms: int = 0,
        outer: bool = True,
        full_page: bool = False,
        save_to_disk: bool = False,
        index: int = -1,
        ctx: Context = None,
    ) -> Any:
        """Control the web browser on the REMOTE machine (persistent system Chrome via
Playwright). All selectors are CSS selectors. The browser is stateful: pages,
tabs, cookies and logins persist between calls. Returns text (JSON) for most
actions, a JPEG image for screenshot.

Actions (params not listed for an action are ignored):

Navigation
  navigate url=<url> [wait_until=load] [settle_ms=0] [timeout=30000]
      Go to a URL. wait_until: commit | domcontentloaded | load | networkidle.
      settle_ms: extra pause after load (SPA hydration, anti-bot interstitials).
      Returns final URL, title, HTTP status.
  go_back | go_forward      Move through tab history. No params.

Interaction
  click selector=<css> [button=left] [click_count=1]
      Click an element. click_count=2 for double-click.
  fill selector=<css> value=<text>
      Set input/textarea value: clears first, fires change events, Unicode-safe.
  type selector=<css> text=<text> [delay=0]
      Type keystroke-by-keystroke (appends, does NOT clear). delay in ms/key.
      To select all before replacing: press_key key="Control+a" first.
  press_key key=<key>       One key or combo: "Enter", "Escape", "Tab", "Control+a".
  select_option selector=<css> value=<value-or-label>
      Choose a <select> option.

Reading
  get_text [selector=body]  Visible inner text of an element.
  get_html [selector=html] [outer=true]
      HTML markup; outer=false for innerHTML only.
  eval_js expression=<js>   Run JavaScript in the page; JSON-serialized result.
      Use this to clear a field without typing, read computed state, etc.

Waiting & capture
  wait_for selector=<css> [state=visible] [timeout=10000]
      Block until the element reaches state: visible | hidden | attached | detached.
  screenshot [selector=<css>] [full_page=false] [save_to_disk=false]
      JPEG of viewport, full page, or one element.

Tabs
  tabs_list                 All open tabs (index, url, title).
  tab_new [url=about:blank] Open a tab (becomes active).
  tab_close [index=-1]      Close a tab (-1 = current).

Unknown actions return the valid action list. Denied actions return a
permission error — do not retry them.
"""
        app = ctx.request_context.lifespan_context
        return await run_action(
            group="browser",
            handlers=HANDLERS,
            action=action,
            app=app,
            params={
                "url": url,
                "selector": selector,
                "value": value,
                "text": text,
                "key": key,
                "expression": expression,
                "button": button,
                "click_count": click_count,
                "delay": delay,
                "state": state,
                "timeout": timeout,
                "wait_until": wait_until,
                "settle_ms": settle_ms,
                "outer": outer,
                "full_page": full_page,
                "save_to_disk": save_to_disk,
                "index": index,
            },
            permissions=permissions,
        )
```

Note on the `-> Any` annotation: FastMCP cannot schema `str | Image` unions (pydantic error) and validates `-> str` returns (rejecting `Image`). `-> Any` skips output validation; FastMCP's `_convert_to_content` emits `TextContent` for strings and `ImageContent` for `Image`. Verified against mcp 1.x before planning.

- [ ] **Step 4: Run registration test for browser**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tool_registration.py -q -k browser`
Expected: 1 passed (desktop still failing — next task)

- [ ] **Step 5: Commit**

```bash
git add src/remote_claws/browser/tools.py tests/test_tool_registration.py
git commit -m "feat: consolidate browser group into remote_browser action tool"
```

---

### Task 6: `remote_desktop` tool

**Files:**
- Rewrite: `src/remote_claws/desktop/tools.py`

- [ ] **Step 1: Rewrite desktop/tools.py**

Changes vs. current: handlers become module-level `h_*` functions taking `app`. **pyautogui/pywinauto imports stay lazy (inside the functions that use them), exactly as the current code does** — `import pyautogui` at module top fails on headless Linux, and CI runs on ubuntu-latest. `pyautogui.FAILSAFE = True` stays in `register()`. Coordinate params are typed `int | None` in the tool signature so the dispatcher can reject omitted coordinates (distinguishing "omitted" from a legitimate `0`).

```python
from __future__ import annotations

import io
import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP, Image

from remote_claws.dispatch import Handler, run_action
from remote_claws.permissions import PermissionChecker
from remote_claws.screenshot import downscale_and_encode, make_save_path


def h_screenshot(app: Any, region: list[int] | None = None, save_to_disk: bool = False) -> Image:
    import pyautogui

    if region and len(region) == 4:
        pil_img = pyautogui.screenshot(region=tuple(region))
    else:
        pil_img = pyautogui.screenshot()
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    save_path = make_save_path(app.config.screenshot_dir) if save_to_disk else None
    jpeg_bytes, saved = downscale_and_encode(
        buf.getvalue(),
        max_width=app.config.screenshot_max_width,
        max_height=app.config.screenshot_max_height,
        quality=app.config.screenshot_quality,
        save_path=save_path,
    )
    return Image(data=jpeg_bytes, format="jpeg")


def h_mouse_click(app: Any, x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    import pyautogui

    pyautogui.click(x=x, y=y, button=button, clicks=clicks)
    return f"Clicked at ({x}, {y}) button={button} clicks={clicks}"


def h_mouse_move(app: Any, x: int, y: int, duration: float = 0.2) -> str:
    import pyautogui

    pyautogui.moveTo(x=x, y=y, duration=duration)
    return f"Moved mouse to ({x}, {y})"


def h_mouse_drag(
    app: Any, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5
) -> str:
    import pyautogui

    pyautogui.moveTo(start_x, start_y)
    pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration)
    return f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})"


def h_type_text(app: Any, text: str, interval: float = 0.02) -> str:
    import pyautogui

    pyautogui.typewrite(text, interval=interval)
    return f"Typed {len(text)} characters"


def h_press_key(app: Any, keys: str) -> str:
    import pyautogui

    key_list = [k.strip() for k in keys.split("+")]
    if len(key_list) == 1:
        pyautogui.press(key_list[0])
    else:
        pyautogui.hotkey(*key_list)
    return f"Pressed: {keys}"


def h_scroll(app: Any, x: int, y: int, clicks: int = 3, direction: str = "down") -> str:
    import pyautogui

    amount = clicks if direction == "up" else -clicks
    pyautogui.scroll(amount, x=x, y=y)
    return f"Scrolled {direction} {clicks} clicks at ({x}, {y})"


def _find_window(title_substr: str):
    """Return the first UIA window whose title contains the substring, or None."""
    from pywinauto import Desktop

    desktop = Desktop(backend="uia")
    for win in desktop.windows():
        if title_substr.lower() in win.window_text().lower():
            return win
    return None


def h_find_window(app: Any, title: str = "", class_name: str = "") -> str:
    from pywinauto import Desktop

    desktop = Desktop(backend="uia")
    results = []
    for win in desktop.windows():
        win_title = win.window_text()
        win_class = win.class_name()
        if title and title.lower() not in win_title.lower():
            continue
        if class_name and class_name.lower() not in win_class.lower():
            continue
        results.append({
            "title": win_title,
            "class_name": win_class,
            "rectangle": {
                "left": win.rectangle().left,
                "top": win.rectangle().top,
                "right": win.rectangle().right,
                "bottom": win.rectangle().bottom,
            },
        })
    return json.dumps(results, indent=2)


def h_focus_window(app: Any, title: str) -> str:
    win = _find_window(title)
    if win is None:
        return f"No window found matching: {title}"
    win.set_focus()
    return f"Focused window: {win.window_text()}"


def h_list_elements(
    app: Any, window_title: str, control_type: str = "", max_depth: int = 4
) -> str:
    target = _find_window(window_title)
    if target is None:
        return f"No window found matching: {window_title}"

    elements = []
    for child in target.descendants(depth=max_depth):
        ct = child.element_info.control_type
        if control_type and ct != control_type:
            continue
        elements.append({
            "name": child.element_info.name,
            "control_type": ct,
            "automation_id": child.element_info.automation_id,
        })
    return json.dumps(elements[:200], indent=2)  # cap at 200


def h_click_element(
    app: Any, window_title: str, element_name: str, control_type: str = ""
) -> str:
    target = _find_window(window_title)
    if target is None:
        return f"No window found matching: {window_title}"
    target.set_focus()

    for child in target.descendants():
        if child.element_info.name == element_name:
            if control_type and child.element_info.control_type != control_type:
                continue
            child.click_input()
            return f"Clicked element: {element_name}"
    return f"Element not found: {element_name}"


def h_get_element_text(
    app: Any, window_title: str, element_name: str, control_type: str = ""
) -> str:
    target = _find_window(window_title)
    if target is None:
        return f"No window found matching: {window_title}"

    for child in target.descendants():
        if child.element_info.name == element_name:
            if control_type and child.element_info.control_type != control_type:
                continue
            try:
                return child.window_text()
            except Exception:
                return child.element_info.name
    return f"Element not found: {element_name}"


HANDLERS: dict[str, Handler] = {
    "screenshot": h_screenshot,
    "mouse_click": h_mouse_click,
    "mouse_move": h_mouse_move,
    "mouse_drag": h_mouse_drag,
    "type_text": h_type_text,
    "press_key": h_press_key,
    "scroll": h_scroll,
    "find_window": h_find_window,
    "focus_window": h_focus_window,
    "list_elements": h_list_elements,
    "click_element": h_click_element,
    "get_element_text": h_get_element_text,
}


def register(mcp: FastMCP, permissions: PermissionChecker) -> None:
    """Register the single remote_desktop tool when the desktop group is active."""

    import pyautogui

    # Keep failsafe enabled — moving mouse to (0,0) aborts
    pyautogui.FAILSAFE = True

    @mcp.tool()
    async def remote_desktop(
        action: str,
        region: list[int] | None = None,
        save_to_disk: bool = False,
        x: int | None = None,
        y: int | None = None,
        start_x: int | None = None,
        start_y: int | None = None,
        end_x: int | None = None,
        end_y: int | None = None,
        button: str = "left",
        clicks: int = 1,
        duration: float = 0.2,
        text: str = "",
        interval: float = 0.02,
        keys: str = "",
        direction: str = "down",
        title: str = "",
        class_name: str = "",
        window_title: str = "",
        element_name: str = "",
        control_type: str = "",
        max_depth: int = 4,
        ctx: Context = None,
    ) -> Any:
        """Control the REMOTE machine's desktop: mouse, keyboard, screenshots, and
Windows UI automation. Coordinates are absolute screen pixels. Returns text for
most actions, a JPEG image for screenshot. Moving the mouse to (0,0) aborts
(pyautogui failsafe).

Workflow: screenshot first, act, re-screenshot to verify. Prefer element-name
actions over coordinates when possible — coordinates break when windows move.

Actions (params not listed for an action are ignored):

Capture
  screenshot [region=[x,y,w,h]] [save_to_disk=false]
      JPEG of the full screen or a region.

Mouse
  mouse_click x=<px> y=<px> [button=left] [clicks=1]      clicks=2 = double-click
  mouse_move x=<px> y=<px> [duration=0.2]
  mouse_drag start_x=<px> start_y=<px> end_x=<px> end_y=<px> [duration=0.5]
  scroll x=<px> y=<px> [clicks=3] [direction=down]        direction: up | down

Keyboard (acts at current focus)
  type_text text=<text> [interval=0.02]   ASCII only.
  press_key keys=<combo>                  "enter", "ctrl+c", "alt+tab", "win"

Windows UI automation (targets controls by NAME — resolution-independent)
  find_window [title=<substr>] [class_name=<substr>]
      List visible windows with title, class, rectangle.
  focus_window title=<substr>             Bring matching window to foreground.
  list_elements window_title=<substr> [control_type=<type>] [max_depth=4]
      Enumerate controls (Button, Edit, ...) with name/automation_id. Cap 200.
  click_element window_title=<substr> element_name=<name> [control_type=<type>]
  get_element_text window_title=<substr> element_name=<name> [control_type=<type>]

Unknown actions return the valid action list. Denied actions return a
permission error — do not retry them.
"""
        app = ctx.request_context.lifespan_context
        return await run_action(
            group="desktop",
            handlers=HANDLERS,
            action=action,
            app=app,
            params={
                "region": region,
                "save_to_disk": save_to_disk,
                "x": x,
                "y": y,
                "start_x": start_x,
                "start_y": start_y,
                "end_x": end_x,
                "end_y": end_y,
                "button": button,
                "clicks": clicks,
                "duration": duration,
                "text": text,
                "interval": interval,
                "keys": keys,
                "direction": direction,
                "title": title,
                "class_name": class_name,
                "window_title": window_title,
                "element_name": element_name,
                "control_type": control_type,
                "max_depth": max_depth,
            },
            permissions=permissions,
        )
```

- [ ] **Step 2: Run registration tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tool_registration.py -q`
Expected: 4 passed

- [ ] **Step 3: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass (the desktop registration test skips on headless Linux CI; module import of desktop/tools stays light — pyautogui/pywinauto load lazily inside handlers and register())

- [ ] **Step 4: Commit**

```bash
git add src/remote_claws/desktop/tools.py
git commit -m "feat: consolidate desktop group into remote_desktop action tool"
```

---

### Task 7: Server instructions rewrite

**Files:**
- Modify: `src/remote_claws/server.py` (SERVER_INSTRUCTIONS only — registration wiring is unchanged)

- [ ] **Step 1: Replace SERVER_INSTRUCTIONS**

```python
SERVER_INSTRUCTIONS = """\
You are controlling a REMOTE machine with a graphical desktop through four \
tools: remote_browser, remote_desktop, remote_exec, remote_files.

CRITICAL: these tools act on the REMOTE machine running this server — not on \
your local environment. If you also have similarly-named local tools (browser, \
exec, read, write, ...), they are DIFFERENT tools on a DIFFERENT machine. Use \
remote_* for anything on the remote machine.

Each remote_* tool takes an `action` parameter plus params, like a CLI \
subcommand: remote_browser(action="navigate", url="https://..."). Read each \
tool's description for its action list. An unknown action returns the list of \
valid ones.

Some actions may be denied by server policy — a denied action returns \
"permission denied"; do not retry it.

## Orientation

Always orient yourself before acting: remote_desktop(action="screenshot") or \
remote_browser(action="screenshot") to see the current state. Screenshots are \
JPEG, max 1280x960.

## Choosing the Right Tool

- **Web tasks**: remote_browser. CSS selectors — reliable and \
resolution-independent. navigate → get_text → click/fill/type → screenshot \
to verify.
- **Native app tasks**: remote_desktop. screenshot → find_window → \
focus_window → click_element by name (more reliable than coordinates) or \
mouse_click at coordinates from the screenshot.
- **Shell commands**: remote_exec. run returns a process_id immediately; \
get_output (wait=true to block) reads output; send_input writes stdin; kill \
when done.
- **Files**: remote_files. Content is base64. Chunk large reads with \
offset/limit.

## Important Notes

- Desktop coordinates are absolute pixels. After any window move/resize, \
re-screenshot before clicking. Moving the mouse to (0,0) aborts (failsafe).
- browser fill clears before typing; browser type appends. To select all \
first: press_key key="Control+a". desktop type_text is ASCII-only — for \
Unicode use browser fill or eval_js.
- Processes persist until killed or server shutdown — kill when done.
- file read returns base64 — decode before interpreting.
"""
```

- [ ] **Step 2: Verify the module still imports and tests pass**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add src/remote_claws/server.py
git commit -m "feat: rewrite server instructions around four remote_* action tools"
```

---

### Task 8: Smoke script + repo permissions.json

**Files:**
- Modify: `scripts/smoke_browser.py`
- Check: `permissions.json` (tracked; uses `"*"` everywhere — no change needed, but verify)

- [ ] **Step 1: Update smoke_browser.py call sites**

Every `await self.call("<browser_tool>", ...)` becomes `await self.call("remote_browser", {"action": "<action>", ...})`. Specific edits:

1. Tool-listing sanity check (~line 170): replace
   ```python
   browser_names = [n for n in names if n.startswith("browser_")]
   ```
   with
   ```python
   browser_names = [n for n in names if n == "remote_browser"]
   ```
   and update the failure message to `"remote_browser not visible — is the browser group enabled and permitted?"`.
2. Every call site: `browser_navigate` → action `"navigate"`, `browser_wait_for` → `"wait_for"`, `browser_eval_js` → `"eval_js"`, `browser_screenshot` → `"screenshot"`, `browser_get_text` → `"get_text"`, `browser_click` → `"click"`, etc. Arguments pass through unchanged (param names are identical).

- [ ] **Step 2: Verify permissions.json needs no changes**

Run: `git diff permissions.json` and confirm content uses only `"*"` entries (compatible with the new format unchanged).

- [ ] **Step 3: Commit**

```bash
git add scripts/smoke_browser.py
git commit -m "chore: update smoke script for remote_browser action dispatch"
```

---

### Task 9: TOOLS.md rewrite

**Files:**
- Rewrite: `TOOLS.md`

- [ ] **Step 1: Write the new TOOLS.md**

Structure: intro, then one section per tool with an action table (Action | Params | Description) mirroring the docstrings in Tasks 3–6. Every action from the inventory must appear exactly once. Table content is derived mechanically from the HANDLERS dicts and docstrings written in Tasks 3–6 — do not paraphrase parameter defaults differently than the code.

The intro content (verbatim):

```markdown
# TOOLS.md — Remote Claws Tool Reference

Remote Claws exposes **4 MCP tools** covering 39 actions. Each tool takes an
`action` parameter plus that action's params, like a CLI subcommand:

```
remote_browser(action="navigate", url="https://example.com")
```

An unknown action returns a JSON error listing the valid actions. Params not
listed for an action are ignored. Required params must be non-empty.

## Permissions

`permissions.json` gates at two levels:

- **Group level (registration time):** if a group is disabled or fully denied,
  its tool is never registered and never appears in `tools/list`.
- **Action level (call time):** `allow`/`deny` entries are bare action names
  per group; deny always wins. A denied action returns
  `{"error": "permission denied: <group>:<action>"}`.

Legacy entries using old tool names (`browser_navigate`, `file_read`) are
auto-normalized to bare action names at load, with a deprecation warning in
the server log.

```

Then one `## remote_browser` / `## remote_desktop` / `## remote_exec` / `## remote_files` section each, with the action tables.

- [ ] **Step 2: Commit**

```bash
git add TOOLS.md
git commit -m "docs: rewrite TOOLS.md for consolidated remote_* tools"
```

---

### Task 10: README + CLAUDE.md + setup guide

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `remote-claws-openclaw-setup-guide.md`

- [ ] **Step 1: README updates**
- Tool table: "16/12/5/6 tools" rows → one row per group: `remote_browser` (16 actions), `remote_desktop` (12), `remote_exec` (5), `remote_files` (6). Header line "39 tools over MCP" → "4 tools (39 actions) over MCP".
- Permission Policy section: example JSON entries become bare action names — e.g. `"desktop": { "allow": ["*"], "deny": ["click_element"] }`, `"exec": { "allow": ["run", "get_output", "list"], "deny": [] }`, `"files": { "allow": ["read", "list", "info"], "deny": [] }`. Add a note: legacy tool-name entries (`browser_navigate`) are auto-normalized at load with a warning.
- Any inline usage examples referencing `browser_navigate` etc. → `remote_browser(action="navigate", ...)`.

- [ ] **Step 2: CLAUDE.md updates**
- First paragraph: "39 tools" → "4 tools (39 actions)".
- Permission system paragraph: describe the two-tier model — group gating at registration time; action-level allow/deny enforced by the dispatcher at call time (returns error strings); legacy prefixed entries normalized at load.
- Key conventions: update the entry about tool naming if present.

- [ ] **Step 3: Setup guide updates**
- "access to all 39 Remote Claws tools" → "access to the 4 Remote Claws tools (39 actions)".

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md remote-claws-openclaw-setup-guide.md
git commit -m "docs: update README, CLAUDE.md, setup guide for tool consolidation"
```

---

### Task 11: SKILLS.md + openclaw/SKILL.md

**Files:**
- Rewrite: `SKILLS.md`
- Rewrite: `openclaw/SKILL.md`

Note: after merge, the user publishes `openclaw/SKILL.md` to the OpenClaw skills repository (ClawHub) — out of scope for this repo.

- [ ] **Step 1: Rewrite SKILLS.md**

Keep the capability-prose structure (it's good) but replace every old tool name with the new call shape, and add the remote/local disambiguation note:

- Intro: "exposes 4 tools (39 actions) over SSE/HTTP: remote_browser, remote_desktop, remote_exec, remote_files. Each takes an action parameter, like a CLI subcommand."
- "Skill: Remote Desktop Control": `remote_desktop(action="screenshot")`, `mouse_click`, `list_elements`, `click_element`, `get_element_text`.
- "Skill: Browser Automation": `remote_browser(action="navigate" | "click" | "fill" | "get_text" | "eval_js" | "screenshot" | ...)`.
- "Skill: Command Execution": `remote_exec(action="run" | "get_output" | "send_input" | "kill" | "list")`.
- "Skill: File Transfer": `remote_files(action="read" | "write" | "list" | "move" | "delete" | "info")`.
- "Combining Skills" examples: rewrite each compound workflow with the new call shapes.
- Limitations section: update `desktop_type_text`→`remote_desktop(action="type_text")`, `browser_fill`→`remote_browser(action="fill")`.

- [ ] **Step 2: Rewrite openclaw/SKILL.md**

Complete new content:

```markdown
---
name: remote-claws
description: "Full remote desktop control of a machine via Remote Claws MCP. Use when asked to: take a screenshot of the remote desktop; click, type, or drag with the mouse/keyboard on the remote machine; run commands or scripts on it; automate the browser on the remote machine; read or write files on the remote machine."
homepage: https://github.com/wentbackward/remote-claws
---

# Remote Claws — Remote Machine Control

Controls a remote machine over MCP. Four tools, each taking an `action`
parameter (like a CLI subcommand): `remote_browser`, `remote_desktop`,
`remote_exec`, `remote_files`. Read each tool's description for its action
list — an unknown action returns the valid list.

## CRITICAL: Remote vs Local

The `remote_*` tools act on the REMOTE machine. OpenClaw's built-in `browser`,
`exec`, `read`/`write`/`edit` act on the LOCAL gateway machine. They are
different machines — never substitute one for the other. If the user says
"on Windows", "on the remote machine", or names the remote host, you MUST use
`remote_*` tools.

## Strategy

1. **Screenshot first.** `remote_desktop(action="screenshot")` before clicking
   or typing; use the returned coordinates to target actions. Re-screenshot
   after actions — windows move, dialogs appear.
2. **Prefer remote_browser for web tasks.** CSS selectors are
   resolution-independent. Only fall back to `remote_desktop` for things the
   browser can't reach (native dialogs, file pickers).
3. **Prefer element names over coordinates.** `remote_desktop(action=
   "click_element", ...)` targets controls by name — survives window moves.
4. **Exec is async.** `remote_exec(action="run", ...)` returns a process_id;
   poll with `action="get_output"` (wait=true blocks), `action="send_input"`
   for stdin, `action="kill"` when done.
5. **Denied actions are final.** A "permission denied" result means server
   policy — do not retry.

## Common actions

- Desktop: screenshot, mouse_click, mouse_move, mouse_drag, scroll,
  type_text (ASCII only), press_key, find_window, focus_window,
  list_elements, click_element, get_element_text
- Browser: navigate, click, fill (clears first, Unicode-safe), type
  (appends), press_key, get_text, get_html, eval_js, screenshot, wait_for,
  select_option, go_back, go_forward, tabs_list, tab_new, tab_close
- Exec: run, get_output, send_input, kill, list
- Files: read (base64, offset/limit for chunks), write (base64), list,
  delete, move, info
```

- [ ] **Step 3: Commit**

```bash
git add SKILLS.md openclaw/SKILL.md
git commit -m "docs: rewrite skill files for remote_* tools with local/remote disambiguation"
```

---

### Task 12: Final verification

- [ ] **Step 1: Full test suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass (~30 tests)

- [ ] **Step 2: Lint and format**

Run: `.venv/Scripts/python.exe -m ruff format src/ tests/ scripts/` then `.venv/Scripts/python.exe -m ruff check src tests scripts`
Expected: no errors (CI runs both `ruff check` and `ruff format --check` — format first, then verify the check is clean, and commit any formatting churn before proceeding)

- [ ] **Step 3: Grep for stale tool names**

Run: `grep -rn "browser_navigate\|desktop_screenshot\|exec_run\|file_read" src/ scripts/ tests/ *.md openclaw/ | grep -v "legacy\|LEGACY\|normaliz"`
Expected: no hits outside legacy-normalization code/comments and the docs' migration notes

- [ ] **Step 4: Import check**

Run: `.venv/Scripts/python.exe -c "from remote_claws import server; print('import OK')"`
Expected: `import OK` plus normal startup log lines (server module imports config/permissions at import time; must not crash)

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: final cleanup for tool consolidation" --allow-empty
```

---

## Self-Review Notes

- **Spec coverage:** 4 tools ✓ (Tasks 3–6), dispatcher ✓ (Task 1), action-level permissions + legacy migration ✓ (Task 2), instructions ✓ (Task 7), smoke script ✓ (Task 8), all docs incl. both SKILL files ✓ (Tasks 9–11), verification ✓ (Task 12).
- **Breaking changes:** old tool names disappear (no aliases — deliberate). permissions.json old entries auto-migrate with warnings. Agent clients (openclaw configs, Claude Desktop/Code registrations) need no changes — same URL/token; only the exposed tool list changes.
- **Known trade-off:** action-level denies are runtime errors, not hidden tools (the tool can't partially hide its own docstring). Documented in CLAUDE.md (Task 10).
