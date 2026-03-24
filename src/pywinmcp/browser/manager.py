from __future__ import annotations

import asyncio
import logging

from playwright.async_api import async_playwright, Browser, Page, Playwright

from pywinmcp.config import AppConfig

logger = logging.getLogger(__name__)


class BrowserManager:
    def __init__(self, config: AppConfig):
        self._config = config
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._pages: list[Page] = []
        self._active_index: int = 0
        self._lock = asyncio.Lock()

    async def get_page(self) -> Page:
        async with self._lock:
            if not self._pages or self._pages[self._active_index].is_closed():
                await self._ensure_browser()
                page = await self._browser.new_page()
                self._pages = [page]
                self._active_index = 0
                logger.info("Created initial browser page")
        return self._pages[self._active_index]

    async def new_tab(self, url: str = "about:blank") -> Page:
        async with self._lock:
            await self._ensure_browser()
            page = await self._browser.new_page()
            if url != "about:blank":
                await page.goto(url, wait_until="domcontentloaded")
            self._pages.append(page)
            self._active_index = len(self._pages) - 1
            return page

    async def switch_tab(self, index: int) -> Page:
        if index < 0 or index >= len(self._pages):
            raise IndexError(f"Tab index {index} out of range (0-{len(self._pages) - 1})")
        self._active_index = index
        page = self._pages[index]
        await page.bring_to_front()
        return page

    async def close_tab(self, index: int = -1) -> None:
        if index == -1:
            index = self._active_index
        if index < 0 or index >= len(self._pages):
            raise IndexError(f"Tab index {index} out of range")
        page = self._pages.pop(index)
        await page.close()
        if self._active_index >= len(self._pages):
            self._active_index = max(0, len(self._pages) - 1)

    def list_tabs(self) -> list[dict]:
        result = []
        for i, page in enumerate(self._pages):
            result.append({
                "index": i,
                "url": page.url,
                "title": "",  # title requires await, filled by caller
                "active": i == self._active_index,
            })
        return result

    async def _ensure_browser(self) -> None:
        if self._playwright is None:
            self._playwright = await async_playwright().start()
            logger.info("Playwright started")
        if self._browser is None or not self._browser.is_connected():
            launch_kwargs: dict = {
                "headless": self._config.browser_headless,
            }
            if self._config.browser_channel != "chromium":
                launch_kwargs["channel"] = self._config.browser_channel
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
            logger.info("Browser launched (headless=%s)", self._config.browser_headless)

    async def shutdown(self) -> None:
        for page in self._pages:
            if not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass
        self._pages.clear()
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        logger.info("Browser manager shut down")
