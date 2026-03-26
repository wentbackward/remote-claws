from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass

import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from remote_claws.auth import HashedTokenVerifier, load_token_hash
from remote_claws.config import AppConfig
from remote_claws.browser.manager import BrowserManager
from remote_claws.permissions import PermissionChecker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    config: AppConfig
    browser: BrowserManager
    permissions: PermissionChecker
    processes: dict  # exec_run process tracker


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    config = AppConfig()
    browser = BrowserManager(config)
    permissions = PermissionChecker(config.permissions_file)
    processes: dict = {}
    logger.info("RemoteClaws starting up (host=%s, port=%s)", config.host, config.port)
    try:
        yield AppContext(config=config, browser=browser, permissions=permissions, processes=processes)
    finally:
        # Kill tracked processes
        for proc_info in processes.values():
            proc = proc_info.get("process")
            if proc and proc.returncode is None:
                try:
                    proc.kill()
                except Exception:
                    pass
        await browser.shutdown()
        logger.info("RemoteClaws shut down")


SERVER_INSTRUCTIONS = """\
You are controlling a remote machine with a graphical desktop. You have four \
tool groups: browser, desktop, exec, and files. Some tools may be disabled by \
the server's permission policy — if a tool returns "Permission denied", do not \
retry it.

## Orientation

Always orient yourself before acting. Take a desktop_screenshot or \
browser_screenshot to see the current state. Use coordinates from the screenshot \
to target clicks. Screenshots are JPEG, max 1280x960.

## Choosing the Right Tool Group

- **Web tasks**: Prefer browser_* tools. They use CSS selectors and are far more \
reliable than pixel-based desktop clicks. Use browser_navigate to open a URL, \
browser_click/fill/type to interact, browser_get_text to read content.
- **Native app tasks**: Use desktop_* tools. Take a desktop_screenshot to see the \
screen, then use desktop_mouse_click with coordinates. For Windows-specific UI, \
use desktop_find_window, desktop_list_elements, and desktop_click_element to \
target elements by name rather than coordinates.
- **Shell commands**: Use exec_run to start a process. It returns a process_id \
immediately. Poll with exec_get_output (wait=false for non-blocking, wait=true \
to block until done). For interactive programs, use exec_send_input to write to \
stdin. Always exec_list or exec_get_output to check on running processes.
- **File operations**: Use file_* tools. Content is base64-encoded. For large \
files, use file_read with offset/limit to read in chunks.

## Browser Workflow

1. browser_navigate to load the page
2. browser_get_text (selector="body") to read visible content
3. browser_screenshot if you need to see layout
4. browser_click / browser_fill / browser_type to interact
5. browser_wait_for if you need to wait for dynamic content
6. browser_eval_js for anything the other tools can't do

The browser is stateful — one active tab persists across calls. Use \
browser_tab_new / browser_tabs_list / browser_tab_close for multi-tab work.

## Desktop Workflow

1. desktop_screenshot to see the current screen
2. desktop_find_window to locate the target app
3. desktop_focus_window to bring it to front
4. desktop_screenshot again to see the focused app
5. desktop_mouse_click at the target coordinates OR desktop_click_element by name
6. desktop_type_text or desktop_press_key for keyboard input

For precision, use desktop_list_elements to enumerate UI controls by name and \
type, then desktop_click_element to click by name — this is more reliable than \
coordinate-based clicking.

## Exec Workflow

1. exec_run to start a command (returns process_id)
2. exec_get_output with wait=false to check progress, or wait=true to block
3. exec_send_input if the process needs stdin
4. exec_kill to terminate if stuck
5. exec_list to see all tracked processes

Set shell=true for commands with pipes, redirects, or shell builtins. Set \
timeout (seconds) to auto-kill long-running processes.

## Important Notes

- Desktop coordinates are absolute screen pixels. After any window move/resize, \
re-screenshot before clicking.
- pyautogui failsafe is enabled: if the mouse is moved to (0,0), operations abort.
- browser_fill clears existing content before typing. browser_type does not — \
it appends keystrokes.
- exec_run processes persist until killed or the server shuts down. Clean up with \
exec_kill when done.
- file_read returns base64. Decode it before interpreting content.
"""

mcp = FastMCP(
    "RemoteClaws",
    instructions=SERVER_INSTRUCTIONS,
    lifespan=app_lifespan,
    # Disable MCP SDK's built-in DNS rebinding protection — we're a remote
    # server by design, and we protect access via bearer token auth instead.
    # Without this, the SDK rejects any Host header that isn't localhost,
    # which breaks all remote connections (Tailscale, LAN, VPN) with 421.
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)

# Register all tool groups
from remote_claws.browser.tools import register as register_browser_tools
from remote_claws.desktop.tools import register as register_desktop_tools
from remote_claws.exec.tools import register as register_exec_tools
from remote_claws.files.tools import register as register_file_tools

register_browser_tools(mcp)
register_desktop_tools(mcp)
register_exec_tools(mcp)
register_file_tools(mcp)


def main():
    import asyncio
    import uvicorn
    from starlette.middleware import Middleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.types import ASGIApp, Receive, Scope, Send

    config = AppConfig()

    # Load auth — refuse to start without it
    try:
        token_hash = load_token_hash(config.auth_file)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    verifier = HashedTokenVerifier(token_hash)

    # Bearer token middleware
    class BearerTokenMiddleware:
        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            request = Request(scope)
            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                response = JSONResponse({"error": "Missing or invalid Authorization header"}, status_code=401)
                await response(scope, receive, send)
                return

            token = auth_header[7:]
            result = await verifier.verify_token(token)
            if result is None:
                response = JSONResponse({"error": "Invalid bearer token"}, status_code=401)
                await response(scope, receive, send)
                return

            await self.app(scope, receive, send)

    # Get the Starlette app from FastMCP SSE and wrap with middleware
    mcp.settings.host = config.host
    mcp.settings.port = config.port
    starlette_app = mcp.sse_app()

    # Host header validation — prevents 421 errors from remote connections
    allowed_hosts = config.get_allowed_hosts()
    if allowed_hosts != ["*"]:
        from starlette.middleware.trustedhost import TrustedHostMiddleware
        starlette_app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
        logger.info("Trusted hosts: %s", ", ".join(allowed_hosts))
    else:
        logger.info("Host checking disabled (allowed_hosts='*')")

    # Auth must be outermost (added last = runs first)
    starlette_app.add_middleware(BearerTokenMiddleware)

    logger.info("Auth enabled — bearer token required for all connections")

    uvicorn_config = uvicorn.Config(
        starlette_app,
        host=config.host,
        port=config.port,
        log_level="info",
    )
    server = uvicorn.Server(uvicorn_config)
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
