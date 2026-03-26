# Remote Claws + OpenClaw Setup Guide

Connect a **Remote Claws** MCP server (running on a Windows machine) to an OpenClaw agent. Once set up, the agent can control the remote desktop, run shell commands, automate a Chromium browser, and read/write files — exactly as a human sitting at that keyboard would.

---

## What You Need

| Item | Notes |
|------|-------|
| Windows machine | Must be reachable from your OpenClaw server (Tailscale recommended) |
| Remote Claws | Running on that Windows machine, port 3030 |
| Bearer token | From Remote Claws config |
| OpenClaw server | Linux/Mac, with Python 3 available |

---

## Step 1 — Start Remote Claws on Windows

Install and run Remote Claws on your Windows machine. It will listen on port 3030 by default.

Copy the **bearer token** from its config — you will need it in Step 3.

### Verify it's running (from Windows)

```powershell
curl http://localhost:3030/sse
# Should stream: event: endpoint / data: /messages/?session_id=...
```

---

## Step 2 — Install the Proxy Dependency on your OpenClaw Server

Remote Claws has a security check: it only accepts HTTP requests where the `Host` header is `localhost:3030`. When OpenClaw connects from a remote IP, the Host header contains that IP instead, and Remote Claws rejects it with `421 Misdirected Request`. The fix is a local proxy that rewrites the header.

On your OpenClaw server:

```bash
pip install aiohttp --break-system-packages
```

---

## Step 3 — Create the Proxy Script

Create this file at `~/workspace/scripts/remote-claws-proxy.py`.

**Replace `<MACHINE_IP>` and `<YOUR_BEARER_TOKEN>` with your actual values.**

```python
#!/usr/bin/env python3
"""
Proxy for Remote Claws MCP server.
Problem: Remote Claws rejects requests unless Host header = localhost:3030.
Fix: This proxy rewrites the Host header and injects the Bearer token.
Listens on 127.0.0.1:8765, forwards to the Windows machine.
"""

import asyncio
import aiohttp
from aiohttp import web

UPSTREAM = "http://<MACHINE_IP>:3030"   # e.g. "http://100.117.11.22:3030"
BEARER   = "<YOUR_BEARER_TOKEN>"         # from Remote Claws config

async def proxy_handler(request: web.Request) -> web.StreamResponse:
    path = request.raw_path
    upstream_url = UPSTREAM + path

    # Copy headers, rewrite Host, inject auth
    headers = dict(request.headers)
    headers["Host"] = "localhost:3030"
    headers["Authorization"] = f"Bearer {BEARER}"
    headers.pop("Content-Length", None)

    body = await request.read()
    timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=None)

    connector = aiohttp.TCPConnector()
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        async with session.request(
            method=request.method,
            url=upstream_url,
            headers=headers,
            data=body or None,
            allow_redirects=False,
        ) as upstream_resp:
            # SSE responses must be streamed — do not buffer
            if "text/event-stream" in upstream_resp.content_type:
                resp = web.StreamResponse(
                    status=upstream_resp.status,
                    headers={
                        k: v for k, v in upstream_resp.headers.items()
                        if k.lower() not in ("transfer-encoding", "content-encoding")
                    },
                )
                await resp.prepare(request)
                async for chunk in upstream_resp.content.iter_any():
                    await resp.write(chunk)
                await resp.write_eof()
                return resp
            else:
                content = await upstream_resp.read()
                return web.Response(
                    status=upstream_resp.status,
                    headers={
                        k: v for k, v in upstream_resp.headers.items()
                        if k.lower() not in ("transfer-encoding", "content-encoding", "content-length")
                    },
                    body=content,
                )

app = web.Application()
app.router.add_route("*", "/{path_info:.*}", proxy_handler)

if __name__ == "__main__":
    print(f"Remote Claws proxy listening on 127.0.0.1:8765 -> {UPSTREAM}")
    web.run_app(app, host="127.0.0.1", port=8765)
```

### Start the proxy

```bash
python3 ~/workspace/scripts/remote-claws-proxy.py &
```

### Verify it works

```bash
curl -s http://127.0.0.1:8765/sse --max-time 3
```

Expected output:

```
event: endpoint
data: /messages/?session_id=<some-id>
```

If you see `Connection refused` — the proxy isn't running. If you see `421` or `401` — check the IP and token in the script.

---

## Step 4 — Register the MCP Server in OpenClaw Config

Edit `~/.openclaw/openclaw.json` and add the `mcp` block. If the file already has content, merge carefully — do not duplicate existing keys.

```json
{
  "mcp": {
    "servers": {
      "remote-claws": {
        "url": "http://127.0.0.1:8765/sse"
      }
    }
  },
  "commands": {
    "mcp": true
  }
}
```

### Restart the gateway

```bash
openclaw gateway restart
```

The agent will now have access to all Remote Claws tools on the next turn.

---

## Step 5 — Install the Skill

The skill file tells the agent what tools are available and when to use them. Without it, a weaker model may not know Remote Claws tools exist.

### Option A — Install from ClawHub (easiest)

```bash
openclaw skills install remote-claws
```

Or from the chat:

```
/skills install remote-claws
```

### Option B — Create it manually

Create the directory and file:

```bash
mkdir -p ~/workspace/skills/remote-claws
```

Save this as `~/workspace/skills/remote-claws/SKILL.md`:

```markdown
---
name: remote-claws
description: "Full remote desktop control of a Windows machine via Remote Claws MCP. Use when asked to: take screenshots of the remote desktop; click, type, or drag with mouse/keyboard; run commands or scripts on the Windows machine; automate a Chromium browser on the remote machine; read or write files on the remote machine."
---

# Remote Claws — Remote Desktop Control

Controls a Windows machine over MCP/SSE. All tools are provided by the
remote-claws MCP server registered in openclaw.json.

## Before using any tool

Check the proxy is running:
  curl -s http://127.0.0.1:8765/sse --max-time 3

If no output, start it:
  python3 ~/workspace/scripts/remote-claws-proxy.py &

## Tool Groups

### Desktop (mouse, keyboard, screenshots)
- desktop_screenshot        — capture full screen or region [x, y, width, height]
- desktop_mouse_click       — left/right/middle click at x, y
- desktop_mouse_move        — move cursor to x, y
- desktop_mouse_drag        — drag from start_x,start_y to end_x,end_y
- desktop_type_text         — type ASCII text at current focus (ASCII only)
- desktop_press_key         — press key or combo: "enter", "ctrl+c", "alt+f4"
- desktop_scroll            — scroll at x,y; direction "up" or "down"
- desktop_find_window       — find windows by title or class_name substring
- desktop_focus_window      — bring window to foreground by title substring
- desktop_list_elements     — list UI controls (buttons, fields) inside a window
- desktop_click_element     — click a named UI element (more reliable than coords)
- desktop_get_element_text  — read the value of a named UI element

### Browser (Chromium via Playwright — use CSS selectors)
- browser_navigate          — go to a URL; returns title, final URL, status
- browser_click             — click element by CSS selector
- browser_fill              — set input value (handles Unicode, triggers change)
- browser_type              — type keystroke-by-keystroke (appends, does not clear)
- browser_press_key         — key press e.g. "Enter", "Control+a"
- browser_get_text          — extract visible text from element (default: body)
- browser_get_html          — get HTML markup of element
- browser_eval_js           — run JavaScript in page context
- browser_screenshot        — screenshot page or element
- browser_wait_for          — wait for element: visible/hidden/attached/detached
- browser_select_option     — select a <select> dropdown option by value or label
- browser_go_back / browser_go_forward
- browser_tabs_list / browser_tab_new / browser_tab_close

### Exec (run commands on Windows, async)
- exec_run                  — start command; returns process_id immediately
- exec_get_output           — read stdout/stderr; set wait=true to block
- exec_send_input           — send a line to stdin of a running process
- exec_kill                 — terminate a process
- exec_list                 — list all tracked processes

### Files (base64 encoded)
- file_write                — write base64 content to a path
- file_read                 — read file as base64 (use offset/limit for large files)
- file_list                 — list directory; supports glob patterns, recursive
- file_delete               — delete file or empty directory
- file_move                 — move or rename file/directory
- file_info                 — get size, created, modified timestamps

## Notes
- Screenshots are JPEG max 1280x960. Take a fresh one before clicking after
  windows move — coordinates are absolute pixels.
- desktop_type_text is ASCII only. For Unicode, use browser_fill or paste via
  clipboard: exec_run powershell with Set-Clipboard, then desktop_press_key ctrl+v
- File content is base64 for binary safety. Decode after reading.
```

---

## Step 6 — Keep the Proxy Alive

The proxy process will die if the server restarts. Add a keepalive check.

### Via OpenClaw cron (chat command)

Ask your agent:

> "Add a cron job every 5 minutes to check if the Remote Claws proxy is running at 127.0.0.1:8765, and restart it if not."

### Or add it to openclaw.json directly

```json
{
  "cron": {
    "jobs": [
      {
        "name": "remote-claws-proxy-keepalive",
        "schedule": { "kind": "every", "everyMs": 300000 },
        "payload": {
          "kind": "agentTurn",
          "message": "Run: curl -s http://127.0.0.1:8765/sse --max-time 3. If it fails, run: python3 ~/workspace/scripts/remote-claws-proxy.py &",
          "timeoutSeconds": 30
        },
        "delivery": { "mode": "none" }
      }
    ]
  }
}
```

---

## Testing

Once everything is running, ask your agent:

> "Take a screenshot of my Windows desktop."

Then:

> "Open Notepad and type 'Hello World'."

If the screenshot comes back and Notepad opens, you're fully operational.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `421 Misdirected Request` | Proxy not running | Start `remote-claws-proxy.py &` |
| `Connection refused` on port 8765 | Proxy crashed | Restart proxy |
| `401 Unauthorized` | Wrong bearer token | Check `BEARER` in proxy script |
| Tools not available to agent | MCP config not loaded | Restart OpenClaw gateway |
| `desktop_type_text` drops chars | Non-ASCII input | Use clipboard method or `browser_fill` |
| Screenshot coords wrong after click | Window moved | Take fresh screenshot first |

---

## Security Notes

- The proxy binds to `127.0.0.1` only — it is not exposed to the network.
- Use **Tailscale** or a VPN between your OpenClaw server and the Windows machine. Do not expose port 3030 to the public internet.
- The bearer token is hardcoded in the proxy script. Keep the file permissions tight (`chmod 600`) and do not commit it to a public repo.
- Remote Claws has no further auth beyond the token. Anyone who can reach port 3030 on the Windows machine has full desktop control.
