# Remote Claws

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
playwright install chromium
```

### Generate Auth Token

The server requires authentication. No naked endpoints.

```bash
remote-claws-setup
```

This prints a bearer token **once** — copy it now. Only the SHA-256 hash is stored on disk in `.remote-claws-auth.json`. The raw token never touches disk.

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

### Network Security

The bearer token protects against unauthorized access, but for production deployments you should also restrict network access:

- Run behind a VPN (Tailscale, WireGuard)
- Use firewall rules to whitelist agent IPs
- Put it behind a reverse proxy with TLS

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
| `REMOTE_CLAWS_ALLOWED_HOSTS` | `*` | Comma-separated trusted Host headers. Set to specific IPs/hostnames for remote access (e.g. `localhost,100.82.48.9`). `*` disables host checking. |
| `REMOTE_CLAWS_AUTH_FILE` | `.remote-claws-auth.json` | Path to auth hash file |
| `REMOTE_CLAWS_PERMISSIONS_FILE` | `permissions.json` | Path to permission policy |
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
