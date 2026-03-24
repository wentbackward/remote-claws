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


mcp = FastMCP(
    "PyWinMCP",
    instructions="Remote Windows PC control server. Provides browser automation via Playwright, desktop control via pyautogui/pywinauto, async command execution, and file transfer.",
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
