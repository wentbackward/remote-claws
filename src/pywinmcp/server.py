from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from pywinmcp.config import AppConfig
from pywinmcp.browser.manager import BrowserManager
from pywinmcp.permissions import PermissionChecker

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
    logger.info("PyWinMCP starting up (host=%s, port=%s)", config.host, config.port)
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
        logger.info("PyWinMCP shut down")


SERVER_INSTRUCTIONS = """\
You are controlling a remote Windows PC with a graphical desktop. You have four \
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
    "PyWinMCP",
    instructions=SERVER_INSTRUCTIONS,
    lifespan=app_lifespan,
)

# Register all tool groups
from pywinmcp.browser.tools import register as register_browser_tools
from pywinmcp.desktop.tools import register as register_desktop_tools
from pywinmcp.exec.tools import register as register_exec_tools
from pywinmcp.files.tools import register as register_file_tools

register_browser_tools(mcp)
register_desktop_tools(mcp)
register_exec_tools(mcp)
register_file_tools(mcp)


def main():
    config = AppConfig()
    mcp.settings.host = config.host
    mcp.settings.port = config.port
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
