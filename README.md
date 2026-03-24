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

```bash
remote-claws
```

The server starts on `0.0.0.0:8080` by default. Agents connect to `http://<your-ip>:8080/sse` with the bearer token.

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

### Any MCP Client

Remote Claws works with any MCP-compliant client. Connect to the SSE endpoint and pass the bearer token:

```
URL:    http://YOUR_IP:8080/sse
Header: Authorization: Bearer YOUR_TOKEN_HERE
```

## Configuration

All settings are configured via environment variables with the `REMOTE_CLAWS_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `REMOTE_CLAWS_HOST` | `0.0.0.0` | Bind address |
| `REMOTE_CLAWS_PORT` | `8080` | Listen port |
| `REMOTE_CLAWS_AUTH_FILE` | `.remote-claws-auth.json` | Path to auth hash file |
| `REMOTE_CLAWS_PERMISSIONS_FILE` | `permissions.json` | Path to permission policy |
| `REMOTE_CLAWS_BROWSER_HEADLESS` | `false` | Run Chromium headless |
| `REMOTE_CLAWS_BROWSER_CHANNEL` | `chromium` | Browser to use |
| `REMOTE_CLAWS_SCREENSHOT_MAX_WIDTH` | `1280` | Max screenshot width |
| `REMOTE_CLAWS_SCREENSHOT_MAX_HEIGHT` | `960` | Max screenshot height |
| `REMOTE_CLAWS_SCREENSHOT_QUALITY` | `75` | JPEG quality (1-100) |
| `REMOTE_CLAWS_SCREENSHOT_DIR` | *(empty)* | Directory to save screenshots (when `save_to_disk=true`) |

## How It Works

The server embeds comprehensive instructions that tell connected agents how to use the tools effectively — which tool group to pick, recommended workflows, and important gotchas. Agents receive these instructions automatically when they connect via MCP.

**Browser tools** use Playwright with CSS selectors — reliable and resolution-independent. The browser launches lazily on first use and stays open across tool calls.

**Desktop tools** use pyautogui for mouse/keyboard and pywinauto for Windows UI element targeting. Agents can click by screen coordinates (from screenshots) or by element name (more reliable).

**Exec tools** are fully async — start a process, do other work, check back for output, send input if interactive.

**Screenshots** are downscaled to JPEG and returned inline so vision-capable models can see and act on them.

## License

MIT
