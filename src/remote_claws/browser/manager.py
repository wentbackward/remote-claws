from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from remote_claws.browser.profile import find_chrome_executable, resolve_profile_dir
from remote_claws.config import AppConfig

logger = logging.getLogger(__name__)


class BrowserStartupError(RuntimeError):
    """Raised when the browser group cannot be brought up. Surfaced at server
    startup so the operator gets an actionable error before any agent
    connects, rather than a confusing tool-call failure later."""


class BrowserManager:
    """Owns a single persistent Chrome browser context for the lifetime of
    the server.

    The context is launched against a dedicated user-data directory so
    cookies, logins and extensions persist across server restarts. Stealth
    patches are applied per-page so the residual automation tells that
    survive even when driving real Chrome are masked.
    """

    def __init__(self, config: AppConfig):
        self._config = config
        self._profile_dir: Path = resolve_profile_dir(config.browser_profile_dir)
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._pages: list[Page] = []
        self._active_index: int = 0
        self._lock = asyncio.Lock()
        self._stealth_apply, self._stealth_status = self._build_stealth_applier()

    # ----- startup-time check (no Playwright launch) ------------------------

    def preflight(self) -> None:
        """Validate the runtime environment before the server starts serving.

        Raises BrowserStartupError with an actionable message when the
        configured channel is 'chrome' but Chrome is not installed. We do
        this synchronously and eagerly so the operator finds out at boot,
        not on first tool call.
        """
        if self._config.browser_channel == "chrome":
            if find_chrome_executable() is None:
                raise BrowserStartupError(
                    "browser_channel='chrome' but Google Chrome was not found "
                    "on this machine. Install Chrome from "
                    "https://www.google.com/chrome/, or set "
                    "REMOTE_CLAWS_BROWSER_CHANNEL=chromium to use the "
                    "bundled Playwright build (test mode \u2014 will be flagged "
                    "by anti-bot vendors)."
                )

    # ----- public surface used by tools (unchanged) -------------------------

    async def get_page(self) -> Page:
        async with self._lock:
            if not self._pages or self._pages[self._active_index].is_closed():
                await self._ensure_context()
                page = await self._new_page_with_stealth()
                self._pages = [page]
                self._active_index = 0
                logger.info("Created initial browser page")
        return self._pages[self._active_index]

    async def new_tab(self, url: str = "about:blank") -> Page:
        async with self._lock:
            await self._ensure_context()
            page = await self._new_page_with_stealth()
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

    async def shutdown(self) -> None:
        for page in self._pages:
            if not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass
        self._pages.clear()
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        logger.info("Browser manager shut down")

    # ----- internals --------------------------------------------------------

    async def _ensure_context(self) -> None:
        if self._playwright is None:
            self._playwright = await async_playwright().start()
            logger.info("Playwright started")
        if self._context is None:
            launch_kwargs: dict = {
                "user_data_dir": str(self._profile_dir),
                "headless": self._config.browser_headless,
            }
            # Only set channel when the user picked a real browser channel.
            # Passing channel="chromium" makes Playwright look for an installed
            # Chromium binary instead of using its bundled one, which is the
            # opposite of what most people expect.
            if self._config.browser_channel and self._config.browser_channel != "chromium":
                launch_kwargs["channel"] = self._config.browser_channel
            self._context = await self._playwright.chromium.launch_persistent_context(**launch_kwargs)
            logger.info(
                "Browser context launched (channel=%s, profile=%s, headless=%s, stealth=%s)",
                self._config.browser_channel,
                self._profile_dir,
                self._config.browser_headless,
                self._stealth_status,
            )

    async def _new_page_with_stealth(self) -> Page:
        assert self._context is not None
        page = await self._context.new_page()
        if self._stealth_apply is not None:
            try:
                await self._stealth_apply(page)
            except Exception as exc:  # noqa: BLE001 \u2014 stealth must never break a tool call
                logger.warning("Stealth application failed for new page: %s", exc)
        return page

    def _build_stealth_applier(self):
        """Resolve the per-page stealth callable once at construction time.

        Returns (apply_fn, status_string). status_string is what we log so
        operators can see at a glance whether stealth is actually active
        ('active'), disabled by config ('disabled'), or requested but the
        library is missing ('unavailable: install tf-playwright-stealth').
        """
        if not self._config.browser_stealth:
            return None, "disabled"
        try:
            # tf-playwright-stealth ships under the playwright_stealth name
            # and exposes a Stealth class with apply_stealth_async().
            from playwright_stealth import Stealth  # type: ignore
        except ImportError:
            logger.warning(
                "browser_stealth=true but playwright_stealth is not installed; "
                "continuing without stealth patches. Run: "
                "pip install tf-playwright-stealth"
            )
            return None, "unavailable (pip install tf-playwright-stealth)"
        stealth = Stealth()

        async def _apply(page: Page) -> None:
            await stealth.apply_stealth_async(page)

        return _apply, "active"
