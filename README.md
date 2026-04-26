# Remote Claws

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io)
[![GitHub](https://img.shields.io/github/stars/wentbackward/remote-claws?style=social)](https://github.com/wentbackward/remote-claws)

An MCP server that gives AI agents full control of a remote desktop machine — browser automation, mouse/keyboard, command execution, and file transfer. Deploy it on a PC, connect your agent, and let it work.

## What It Does

Remote Claws exposes 39 tools over MCP (Model Context Protocol) via SSE/HTTP:

| Group | Tools | What It Controls |
|-------|-------|-----------------|
| **Browser** | 16 tools | Navigate, click, fill forms, read text, run JS, take page screenshots — via Playwright (Chromium) |
| **Desktop** | 12 tools | Mouse clicks, keyboard input, window management, UI element inspection — via pyautogui + pywinauto |
| **Exec** | 5 tools | Start processes, stream stdout/stderr, send stdin, kill — fully async |
| **Files** | 6 tools | Read, write, list, move, delete files — base64 transfer with chunked reads |

See [TOOLS.md](TOOLS.md) for the complete tool reference and [SKILLS.md](SKILLS.md) for a high-level capability overview.

## Quick Start

```bash
git clone https://github.com/wentbackward/remote-claws.git
cd remote-claws
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -e .
playwright install chromium  # bundled test build, used as a fallback
```

### Browser Mode — Real Chrome with Your Identity

The browser group defaults to **driving the system-installed Google Chrome with a dedicated persistent profile**, not the bundled Playwright Chromium. This is what lets the agent browse like you do: signed into your subscriptions, past the bot walls, with your adblocker, with your cookies. Bundled Chromium is still available as a channel for testing and internal sites where the test fingerprint is fine.

Install Chrome from <https://www.google.com/chrome/> if you don't already have it. Then seed the profile:

```bash
remote-claws-browser-setup
# or jump straight to a site to log into:
remote-claws-browser-setup --url https://nytimes.com
```

Chrome opens on a dedicated profile (under `%LOCALAPPDATA%\RemoteClaws\chrome-profile` on Windows, `~/.local/share/remote-claws/chrome-profile` on Linux, `~/Library/Application Support/RemoteClaws/chrome-profile` on macOS). Sign into the services you want the agent to access, install your adblocker, accept cookie banners, then close the window. Sessions persist across server restarts. Run it again any time to add more services.

The profile is **deliberately separate from your normal Chrome profile**. You opt services in by signing into them inside the dedicated profile — no risk of the agent finding your bank session because it shares your daily Chrome.

To fall back to the bundled test Chromium (e.g. CI, internal testing, sites where stealth Chrome causes friction):

```bash
REMOTE_CLAWS_BROWSER_CHANNEL=chromium remote-claws
```

The server will hard-fail at startup if `browser_channel=chrome` (the default) and Chrome isn't installed. This is intentional — the server is manually-run and non-daemon, so you find out at boot, not three tool-calls into a session.

### Smoke-testing a running server

`scripts/smoke_browser.py` connects to a running server over SSE and drives a short real-world browsing session (X.com posts, Bloomberg headlines, follow a story link). It saves a screenshot per step under `./smoke-screenshots/` so you can visually confirm that the persistent Chrome profile is signed in and that paywalls / bot walls aren't blocking you.

```bash
pip install "mcp[cli]>=1.20"
export REMOTE_CLAWS_URL="http://<windows-ip>:8080/sse"
export REMOTE_CLAWS_TOKEN="<bearer token>"
python scripts/smoke_browser.py
```

### Generate Auth Token

The server requires authentication. No naked endpoints.

```bash
remote-claws-setup
```

This prints a bearer token **once** — copy it now. Only the SHA-256 hash is stored on disk in `.remote-claws-auth.json`. The raw token never touches disk. The setup script also offers to chain into `remote-claws-browser-setup` so you can seed the profile in one go.

### Start the Server

The server runs in the **foreground** — keep the terminal open while agents are connected. There is no background/service mode yet; this keeps things simple and visible while the project stabilizes.

```bash
# Activate the venv first (every new terminal session)
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS

remote-claws
```

The server starts on `0.0.0.0:8080` by default. Agents connect to `http://<your-ip>:8080/sse` with the bearer token. You'll see tool calls logged in the terminal as agents use them.

## Security

### Authentication

Every connection requires a bearer token in the `Authorization` header. The server:

1. Stores only a SHA-256 hash of the token (never the raw token)
2. Uses timing-safe comparison (`hmac.compare_digest`) to prevent timing attacks
3. Refuses to start if no auth file exists
4. Returns 401 for missing, malformed, or invalid tokens

To rotate the token, run `remote-claws-setup` again.

### Permission Policy

`permissions.json` controls which tools are available. Each tool group (`browser`, `desktop`, `exec`, `files`) has `allow` and `deny` lists. **Deny always supersedes allow.**

```json
{
  "permissions": {
    "browser": { "allow": ["*"], "deny": [] },
    "desktop": { "allow": ["*"], "deny": ["desktop_click_element"] },
    "exec":    { "allow": ["exec_run", "exec_get_output", "exec_list"], "deny": [] },
    "files":   { "allow": ["file_read", "file_list", "file_info"], "deny": [] }
  }
}
```

Use `"*"` to allow/deny an entire group. Omitting a group denies it entirely.

Disallowed tools are not registered with the MCP server, so they don't show up in `tools/list` at all — the agent simply doesn't see them. There is no "permission denied" runtime error to chew through.

### Disabling Whole Tool Groups at Startup

For a stricter cut-off, set `enabled_groups` to skip a group entirely. Disabled groups are never imported, so heavy dependencies (Playwright for `browser`, pyautogui for `desktop`) stay out of memory:

```bash
REMOTE_CLAWS_ENABLED_GROUPS="exec,files" remote-claws
```

Or in `remote-claws.json`:
```json
{ "enabled_groups": "exec,files" }
```

A group is active only when it appears in `enabled_groups` **and** its `permissions.json` entry permits at least one tool. The `enabled_groups` filter is applied first, so a missing group can't be re-enabled by the policy file.

### IP Allowlist

Lock the server to specific source IPs. Connections from any other IP are rejected with 403 before auth is even checked:

```bash
REMOTE_CLAWS_ALLOWED_IPS="100.82.48.9,100.106.2.100" remote-claws
```

Or in `remote-claws.json`:
```json
{ "allowed_ips": "100.82.48.9,100.106.2.100" }
```

When empty (the default), IP filtering is disabled and access relies on bearer token auth alone.

### Defense in Depth

The server has three independent security layers, outermost first:

1. **IP allowlist** — rejects connections from unknown IPs (403, before any processing)
2. **Bearer token** — rejects unauthenticated requests (401, timing-safe hash comparison)
3. **Permission policy** — restricts which tools are available (per-tool granularity)

For production, also consider:
- Run behind a VPN (Tailscale, WireGuard) for encrypted transport
- Use firewall rules as an additional network-level gate
- Put behind a reverse proxy with TLS for encryption in transit

## Connecting Agents

### Claude Desktop

Add to your Claude Desktop config (`%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "remote-claws": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://YOUR_IP:8080/sse",
        "--header",
        "Authorization:${REMOTE_CLAWS_TOKEN}"
      ],
      "env": {
        "REMOTE_CLAWS_TOKEN": "Bearer YOUR_TOKEN_HERE"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add remote-claws \
  --transport sse \
  --url http://YOUR_IP:8080/sse \
  --header "Authorization: Bearer YOUR_TOKEN_HERE"
```

### LangChain / LangGraph

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

async with MultiServerMCPClient(
    {
        "remote-claws": {
            "url": "http://YOUR_IP:8080/sse",
            "transport": "sse",
            "headers": {
                "Authorization": "Bearer YOUR_TOKEN_HERE"
            }
        }
    }
) as client:
    tools = client.get_tools()
    # Use tools with your LangGraph agent
```

### OpenAI Agents SDK

```python
from agents import Agent
from agents.mcp import MCPServerSse

mcp = MCPServerSse(
    url="http://YOUR_IP:8080/sse",
    headers={"Authorization": "Bearer YOUR_TOKEN_HERE"},
)

agent = Agent(
    name="desktop-controller",
    mcp_servers=[mcp],
)
```

### n8n

1. Add an **MCP Client Tool** node to your workflow
2. Set the URL to `http://YOUR_IP:8080/sse`
3. Add a custom header: `Authorization: Bearer YOUR_TOKEN_HERE`
4. The node auto-discovers all 39 tools

### OpenClaw

Add to `~/.openclaw/openclaw.json`:

```json
{
  "mcp": {
    "servers": {
      "remote-claws": {
        "url": "http://YOUR_IP:8080/sse",
        "headers": {
          "Authorization": "Bearer YOUR_TOKEN_HERE"
        }
      }
    }
  }
}
```

Then restart the gateway: `openclaw gateway restart`

For a detailed walkthrough including skill installation and troubleshooting, see [remote-claws-openclaw-setup-guide.md](remote-claws-openclaw-setup-guide.md).

### Any MCP Client

Remote Claws works with any MCP-compliant client. Connect to the SSE endpoint and pass the bearer token:

```
URL:    http://YOUR_IP:8080/sse
Header: Authorization: Bearer YOUR_TOKEN_HERE
```

## Configuration

### Config File (`remote-claws.json`)

Drop a `remote-claws.json` in the working directory to set defaults. Every setting from the env var table below can be set here. Values support `${ENV_VAR}` expansion and `${ENV_VAR:-default}` fallback:

```json
{
  "host": "192.168.1.50",
  "port": 9090,
  "allowed_hosts": "localhost,${TAILSCALE_IP:-127.0.0.1}",
  "browser_headless": false,
  "screenshot_quality": 85,
  "auth_file": "${HOME}/.remote-claws-auth.json"
}
```

Copy `remote-claws.example.json` as a starting point:
```bash
cp remote-claws.example.json remote-claws.json
```

You can also use a `.env` file alongside it — pydantic-settings reads `.env` files automatically.

### Environment Variables

Env vars override the config file. All use the `REMOTE_CLAWS_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `REMOTE_CLAWS_HOST` | `0.0.0.0` | Bind address |
| `REMOTE_CLAWS_PORT` | `8080` | Listen port |
| `REMOTE_CLAWS_ALLOWED_IPS` | *(empty)* | Comma-separated source IPs allowed to connect. Empty = no IP filtering (rely on token auth). Checked before auth. |
| `REMOTE_CLAWS_ALLOWED_HOSTS` | `*` | Comma-separated trusted Host headers. `*` disables host checking. |
| `REMOTE_CLAWS_AUTH_FILE` | `.remote-claws-auth.json` | Path to auth hash file |
| `REMOTE_CLAWS_PERMISSIONS_FILE` | `permissions.json` | Path to permission policy |
| `REMOTE_CLAWS_ENABLED_GROUPS` | `browser,desktop,exec,files` | Tool groups loaded at startup. Groups not listed are not imported and expose no tools. |
| `REMOTE_CLAWS_BROWSER_CHANNEL` | `chrome` | Which browser to drive. `chrome` = system Google Chrome (real fingerprint, persistent profile). `chromium` = bundled Playwright build (lightweight, repeatable, visibly automated). |
| `REMOTE_CLAWS_BROWSER_PROFILE_DIR` | OS default | Override the Chrome user-data directory. Empty = OS-appropriate default. |
| `REMOTE_CLAWS_BROWSER_STEALTH` | `true` | Apply tf-playwright-stealth patches to every page. Disable only if a site misbehaves under them. |
| `REMOTE_CLAWS_BROWSER_HEADLESS` | `false` | Run Chrome headless. Strongly discouraged when `browser_channel=chrome` — anti-bot vendors fingerprint headless rendering. |
| `REMOTE_CLAWS_BROWSER_HEADLESS` | `false` | Run Chromium headless |
| `REMOTE_CLAWS_BROWSER_CHANNEL` | `chromium` | Browser to use |
| `REMOTE_CLAWS_SCREENSHOT_MAX_WIDTH` | `1280` | Max screenshot width |
| `REMOTE_CLAWS_SCREENSHOT_MAX_HEIGHT` | `960` | Max screenshot height |
| `REMOTE_CLAWS_SCREENSHOT_QUALITY` | `75` | JPEG quality (1-100) |
| `REMOTE_CLAWS_SCREENSHOT_DIR` | *(empty)* | Directory to save screenshots (when `save_to_disk=true`) |
| `REMOTE_CLAWS_CONFIG_FILE` | `remote-claws.json` | Path to the JSON config file |

### Priority

Highest wins: **env vars** → **config file** → **built-in defaults**

### Troubleshooting: 421 Errors

If agents connecting over a VPN or remote IP get `421 Misdirected Request`, the server is rejecting the `Host` header. Fix:

```bash
# Allow your Tailscale IP
REMOTE_CLAWS_ALLOWED_HOSTS="localhost,127.0.0.1,100.82.48.9" remote-claws

# Or disable host checking entirely (if you trust your network)
REMOTE_CLAWS_ALLOWED_HOSTS="*" remote-claws
```

Or set it in `remote-claws.json`:
```json
{ "allowed_hosts": "localhost,127.0.0.1,100.82.48.9" }
```

## How It Works

The server embeds comprehensive instructions that tell connected agents how to use the tools effectively — which tool group to pick, recommended workflows, and important gotchas. Agents receive these instructions automatically when they connect via MCP.

**Browser tools** use Playwright with CSS selectors — reliable and resolution-independent. The browser launches lazily on first use and stays open across tool calls.

**Desktop tools** use pyautogui for mouse/keyboard and pywinauto for Windows UI element targeting. Agents can click by screen coordinates (from screenshots) or by element name (more reliable).

**Exec tools** are fully async — start a process, do other work, check back for output, send input if interactive.

**Screenshots** are downscaled to JPEG and returned inline so vision-capable models can see and act on them.

## License

MIT
