# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Remote Claws is an MCP (Model Context Protocol) server for remote machine control. It exposes 39 tools over SSE/HTTP across four groups: browser automation (Playwright), desktop control (pyautogui/pywinauto), async command execution, and file transfer.

## Setup & Running

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .
playwright install chromium
remote-claws-setup            # generates auth token (shown once) and saves hash
remote-claws                  # starts SSE server on 0.0.0.0:8080
```

Agents connect to `http://<ip>:8080/sse` with `Authorization: Bearer <token>`. Entry point is `remote_claws.server:main`. The server refuses to start without an auth file — run `remote-claws-setup` first.

## Configuration

All config via environment variables with `REMOTE_CLAWS_` prefix (Pydantic Settings in `config.py`):
- `REMOTE_CLAWS_PORT`, `REMOTE_CLAWS_HOST`, `REMOTE_CLAWS_BROWSER_HEADLESS`, `REMOTE_CLAWS_BROWSER_CHANNEL`
- `REMOTE_CLAWS_SCREENSHOT_MAX_WIDTH`, `REMOTE_CLAWS_SCREENSHOT_MAX_HEIGHT`, `REMOTE_CLAWS_SCREENSHOT_QUALITY`
- `REMOTE_CLAWS_PERMISSIONS_FILE` (default: `permissions.json`)
- `REMOTE_CLAWS_AUTH_FILE` (default: `.remote-claws-auth.json`)

## Authentication

Bearer token auth via the MCP SDK's `TokenVerifier`. Run `remote-claws-setup` to generate a token — it prints the raw token once and stores only the SHA-256 hash in `.remote-claws-auth.json`. The server loads the hash at startup and the SDK validates `Authorization: Bearer <token>` on every connection. Timing-safe comparison via `hmac.compare_digest`.

## Architecture

**Lifespan pattern**: `server.py` creates an `AppContext` dataclass (config, browser manager, permission checker, process tracker) in `app_lifespan()`. Every tool accesses it via `ctx.request_context.lifespan_context`.

**Tool registration**: Each module (`browser/tools.py`, `desktop/tools.py`, `exec/tools.py`, `files/tools.py`) exports a `register(mcp: FastMCP)` function that decorates handlers with `@mcp.tool()`. This avoids circular imports — `server.py` creates the `mcp` instance, then calls each `register()`.

**Permission system** (`permissions.py`): Loads `permissions.json` at startup. Tool names map to groups via prefix (`browser_` → `browser`, `desktop_` → `desktop`, `exec_` → `exec`, `file_` → `files`). Deny always supersedes allow, default is deny-all. Every tool checks `app.permissions.is_allowed(tool_name)` inline before executing.

**Browser lifecycle** (`browser/manager.py`): Lazy singleton — Playwright and Chromium only launch on first `get_page()` call. Uses `asyncio.Lock` to prevent double-launch. Maintains a list of `Page` objects with an active index for tab management.

**Screenshot pipeline** (`screenshot.py`): Shared by both browser and desktop tools. Raw PNG → Pillow thumbnail (LANCZOS) → JPEG encode → return as `Image(data=..., format="jpeg")`.

**Async/sync mix**: Browser and exec tools are async. Desktop and file tools are sync (FastMCP runs them in a thread automatically).

## Key Conventions

- All tools return strings (typically JSON) or MCP `Image` objects
- Permission denials return error strings, not exceptions
- File content transfers use base64 encoding
- Exec processes tracked by 8-char hex UUID in `app.processes` dict, with background coroutines streaming stdout/stderr into list buffers
- `pyautogui.FAILSAFE = True` — mouse to (0,0) aborts as safety measure
- Results are capped: `file_list` at 500 entries, `desktop_list_elements` at 200
