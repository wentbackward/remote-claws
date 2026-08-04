# AGENTS.md

This file provides guidance to coding agents (Claude Code, pi, etc.) when working with code in this repository.

## What This Is

Remote Claws is an MCP (Model Context Protocol) server for remote machine control. It exposes 4 tools (39 actions) over HTTP (SSE or Streamable HTTP): `remote_browser` (Playwright), `remote_desktop` (pyautogui/pywinauto), `remote_exec` (async command execution), and `remote_files` (file transfer). Each tool takes an `action` parameter plus params, like a CLI subcommand. The `remote_` prefix disambiguates from agents' built-in local tools (browser/exec/read/write).

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

**Tool registration & dispatch**: Each module (`browser/tools.py`, `desktop/tools.py`, `exec/tools.py`, `files/tools.py`) exposes a `HANDLERS` dict (action name → module-level handler function) and a `register(mcp, permissions)` function that registers ONE tool. The tool's `action` parameter routes through `dispatch.py::run_action`, which validates required params (non-empty), filters the flat param superset down to what the handler declares, and checks action-level permissions at call time. Handlers take `app` (the lifespan AppContext) as their first parameter.

**Permission system** (`permissions.py`): Loads `permissions.json` at startup. Two-tier enforcement. Group level: `is_group_active(group)` is consulted **at registration time** — an inactive group's tool is never registered, never appears in `tools/list`, and its heavy deps (Playwright, pyautogui) are never imported. Action level: `is_action_allowed(group, action)` is consulted **at call time** by the dispatcher, because one tool per group can no longer hide individual actions from `tools/list`; a denied action returns a `permission denied` error string. Policy entries are bare action names (`navigate`, `run`, `read`); legacy pre-consolidation tool names (`browser_navigate`, `file_read`) are auto-normalized at load with a deprecation warning. Deny always supersedes allow, default is deny-all, and the policy is fixed for the life of the process.

**Browser lifecycle** (`browser/manager.py`): Owns a single persistent `BrowserContext` for the lifetime of the server. Default channel is `chrome` (system Google Chrome) launched via `launch_persistent_context(user_data_dir=…)` so cookies / logins / extensions survive restarts. Stealth patches (`tf-playwright-stealth`) are applied to each new page when `browser_stealth` is true. Lazy: Playwright and Chrome only launch on first `get_page()` call, but a synchronous `preflight()` runs at server startup to fail fast when `browser_channel=chrome` and Chrome isn't installed. `browser/profile.py` contains pure helpers (default profile dir per OS, lock detection, Chrome executable discovery) shared with the `remote-claws-browser-setup` CLI — the setup CLI launches Chrome **directly via subprocess**, not through Playwright, so no automation flags are present during interactive sign-ins. Maintains a list of `Page` objects with an active index for tab management.

**Screenshot pipeline** (`screenshot.py`): Shared by both browser and desktop tools. Raw PNG → Pillow thumbnail (LANCZOS) → JPEG encode → return as `Image(data=..., format="jpeg")`.

**Async/sync mix**: Browser and exec tools are async. Desktop and file tools are sync (FastMCP runs them in a thread automatically).

## Key Conventions

- All tools return strings (typically JSON) or MCP `Image` objects
- Permission denials return error strings, not exceptions
- File content transfers use base64 encoding
- Exec processes tracked by 8-char hex UUID in `app.processes` dict, with background coroutines streaming stdout/stderr into list buffers
- `pyautogui.FAILSAFE = True` — mouse to (0,0) aborts as safety measure
- Results are capped: `remote_files` action `list` at 500 entries, `remote_desktop` action `list_elements` at 200

## OpenClaw Skill (ClawHub)

The OpenClaw skill lives at `skills/remote-claws/SKILL.md` — folder name and frontmatter `name` must stay aligned (`remote-claws`), and `description` must stay under 160 chars. It is published to ClawHub from that folder:

```bash
npm i -g clawhub && clawhub login
clawhub skill publish ./skills/remote-claws --version <x.y.z>
```

Version/changelog are publish-time flags, never file content — do not put a version in SKILL.md. New releases are hidden until ClawHub's automated security review completes.
