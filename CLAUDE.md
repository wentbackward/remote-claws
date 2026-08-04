# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Remote Claws is an MCP (Model Context Protocol) server for remote machine control. It exposes 39 tools over HTTP (SSE or Streamable HTTP) across four groups: browser automation (Playwright), desktop control (pyautogui/pywinauto), async command execution, and file transfer.

## Setup & Running

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .
playwright install chromium
remote-claws-setup            # generates auth token, picks transport (SSE or Streamable HTTP)
remote-claws                  # starts server on 0.0.0.0:8080
```

Agents connect to `http://<ip>:8080/sse` (SSE) or `http://<ip>:8080/mcp` (Streamable HTTP) with `Authorization: Bearer <token>`. Entry point is `remote_claws.server:main`. The server refuses to start without an auth file — run `remote-claws-setup` first.

## Configuration

Three-layer config: env vars (`REMOTE_CLAWS_` prefix) override `remote-claws.json` which overrides built-in defaults. The JSON file supports `${ENV_VAR}` and `${ENV_VAR:-default}` expansion. See `config.py`.

Key settings:
- `REMOTE_CLAWS_ALLOWED_HOSTS` (default: `*`): comma-separated trusted Host headers. Set to specific IPs when connecting over VPN/Tailscale to avoid 421 errors. `*` disables host checking.
- `REMOTE_CLAWS_PORT`, `REMOTE_CLAWS_HOST`, `REMOTE_CLAWS_BROWSER_HEADLESS`
- `REMOTE_CLAWS_BROWSER_CHANNEL` (default: `chrome`): drive system Google Chrome with a persistent profile (real fingerprint, the user's identity). Set to `chromium` to use the bundled Playwright build for testing or internal sites.
- `REMOTE_CLAWS_BROWSER_PROFILE_DIR` (default: OS-appropriate per-user path): override the dedicated Chrome user-data directory.
- `REMOTE_CLAWS_BROWSER_STEALTH` (default: `true`): apply `tf-playwright-stealth` to every page.
- `REMOTE_CLAWS_SCREENSHOT_MAX_WIDTH`, `REMOTE_CLAWS_SCREENSHOT_MAX_HEIGHT`, `REMOTE_CLAWS_SCREENSHOT_QUALITY`
- `REMOTE_CLAWS_PERMISSIONS_FILE` (default: `permissions.json`)
- `REMOTE_CLAWS_ENABLED_GROUPS` (default: `browser,desktop,exec,files`): comma-separated list of tool groups to load at startup. Groups not listed are never imported (Playwright / pyautogui are not loaded), and none of their tools are registered. Use this to keep heavy dependencies out of memory on machines that don't need them.
- `REMOTE_CLAWS_TRANSPORT` (default: `sse`): MCP transport — `sse` or `streamable-http`
- `REMOTE_CLAWS_AUTH_FILE` (default: `.remote-claws-auth.json`)
- `REMOTE_CLAWS_CONFIG_FILE` (default: `remote-claws.json`)

## Authentication

Bearer token auth via the MCP SDK's `TokenVerifier`. Run `remote-claws-setup` to generate a token — it prints the raw token once and stores only the SHA-256 hash in `.remote-claws-auth.json`. The server loads the hash at startup and the SDK validates `Authorization: Bearer <token>` on every connection. Timing-safe comparison via `hmac.compare_digest`. After writing the token, `remote-claws-setup` offers to chain into `remote-claws-browser-setup` (TTY only, skipped silently when stdin is piped).

## Architecture

**Lifespan pattern**: `server.py` creates an `AppContext` dataclass (config, browser manager, permission checker, process tracker) in `app_lifespan()`. Every tool accesses it via `ctx.request_context.lifespan_context`.

**Tool registration**: Each module (`browser/tools.py`, `desktop/tools.py`, `exec/tools.py`, `files/tools.py`) exports a `register(mcp: FastMCP)` function that decorates handlers with `@mcp.tool()`. This avoids circular imports — `server.py` creates the `mcp` instance, then calls each `register()`.

**Permission system** (`permissions.py`): Loads `permissions.json` at startup. Tool names map to groups via prefix (`browser_` → `browser`, `desktop_` → `desktop`, `exec_` → `exec`, `file_` → `files`). Deny always supersedes allow, default is deny-all. The checker is consulted **at tool registration time**, not at call time — disallowed tools are never registered with FastMCP and therefore never appear in the MCP `tools/list` response. There is no runtime re-check inside tool bodies because the policy is fixed for the life of the process. `is_group_active(group)` combines the JSON policy with the `enabled_groups` config so the lifespan can skip importing a group's heavy deps (e.g. Playwright) when the group is fully off.

**Browser lifecycle** (`browser/manager.py`): Owns a single persistent `BrowserContext` for the lifetime of the server. Default channel is `chrome` (system Google Chrome) launched via `launch_persistent_context(user_data_dir=…)` so cookies / logins / extensions survive restarts. Stealth patches (`tf-playwright-stealth`) are applied to each new page when `browser_stealth` is true. Lazy: Playwright and Chrome only launch on first `get_page()` call, but a synchronous `preflight()` runs at server startup to fail fast when `browser_channel=chrome` and Chrome isn't installed. `browser/profile.py` contains pure helpers (default profile dir per OS, lock detection, Chrome executable discovery) shared with the `remote-claws-browser-setup` CLI — the setup CLI launches Chrome **directly via subprocess**, not through Playwright, so no automation flags are present during interactive sign-ins. Maintains a list of `Page` objects with an active index for tab management.

**Screenshot pipeline** (`screenshot.py`): Shared by both browser and desktop tools. Raw PNG → Pillow thumbnail (LANCZOS) → JPEG encode → return as `Image(data=..., format="jpeg")`.

**Async/sync mix**: Browser and exec tools are async. Desktop and file tools are sync (FastMCP runs them in a thread automatically).

## Key Conventions

- All tools return strings (typically JSON) or MCP `Image` objects
- Permission denials return error strings, not exceptions
- File content transfers use base64 encoding
- Exec processes tracked by 8-char hex UUID in `app.processes` dict, with background coroutines streaming stdout/stderr into list buffers
- `pyautogui.FAILSAFE = True` — mouse to (0,0) aborts as safety measure
- Results are capped: `file_list` at 500 entries, `desktop_list_elements` at 200
