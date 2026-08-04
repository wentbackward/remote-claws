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

from remote_claws.browser.profile import (
    find_chrome_executable,
    read_channel_stamp,
    resolve_profile_dir,
    write_channel_stamp,
)
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

    @property
    def profile_dir(self) -> Path:
        """The resolved user-data directory the browser context will launch against."""
        return self._profile_dir

    # ----- startup-time check (no Playwright launch) ------------------------

    def preflight(self) -> None:
        """Validate the runtime environment before the server starts serving.

        Raises BrowserStartupError with an actionable message when the
        configured channel is 'chrome' but Chrome is not installed. We do
        this synchronously and eagerly so the operator finds out at boot,
        not on first tool call.

        Also fails fast on a channel/profile mismatch: the setup CLI seeds
        the profile with REAL Chrome, and launching Playwright's bundled
        Chromium (channel=chromium) against that Chrome-stamped profile
        crashes the browser on startup. Better to refuse at boot with a
        clear remedy than to hand the agent a crashing browser.
        """
        channel = self._config.browser_channel
        stamp = read_channel_stamp(self._profile_dir)
        if stamp is not None and stamp != channel:
            raise BrowserStartupError(
                f"browser_channel={channel!r} but the profile at "
                f"{self._profile_dir} was created by channel {stamp!r}. "
                "Mixing browser builds on one profile crashes the browser "
                "on startup. Either set REMOTE_CLAWS_BROWSER_CHANNEL to "
                f"{stamp!r}, point REMOTE_CLAWS_BROWSER_PROFILE_DIR at a "
                "fresh directory, or delete the .remote-claws-channel file "
                "in the profile directory to re-stamp it."
            )
        if channel == "chrome" and find_chrome_executable() is None:
            raise BrowserStartupError(
                "browser_channel='chrome' but Google Chrome was not found "
                "on this machine. Install Chrome from "
                "https://www.google.com/chrome/. (The bundled Chromium "
                "build via REMOTE_CLAWS_BROWSER_CHANNEL=chromium exists "
                "for CI only \u2014 it is visibly automated and will trip "
                "bot walls.)"
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
            result.append(
                {
                    "index": i,
                    "url": page.url,
                    "title": "",  # title requires await, filled by caller
                    "active": i == self._active_index,
                }
            )
        return result

    async def shutdown(self) -> None:
        from contextlib import suppress

        for page in self._pages:
            if not page.is_closed():
                with suppress(Exception):
                    await page.close()
        self._pages.clear()
        if self._context:
            with suppress(Exception):
                await self._context.close()
        if self._playwright:
            with suppress(Exception):
                await self._playwright.stop()
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
            # Stamp the profile with the channel that owns it so a later
            # channel change fails preflight instead of crashing the browser.
            # Profiles created before this mechanism get stamped on their
            # first successful launch.
            write_channel_stamp(self._profile_dir, self._config.browser_channel)
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
            except Exception as exc:
                logger.warning("Stealth application failed for new page: %s", exc)
        return page

    def _build_stealth_applier(self):
        """Resolve the per-page stealth callable once at construction time.

        Returns (apply_fn, status_string). status_string is what we log so
        operators can see at a glance whether stealth is actually active
        ('active'), disabled by config ('disabled'), or requested but the
        library is missing ('unavailable: install tf-playwright-stealth').

        tf-playwright-stealth 1.2+ exposes a module-level stealth_async();
        1.1.x exposed a Stealth class with apply_stealth_async(). Support
        both — installed 1.1.x versions in the wild must keep working.
        """
        if not self._config.browser_stealth:
            return None, "disabled"
        try:
            # tf-playwright-stealth ships under the playwright_stealth name.
            import playwright_stealth
        except ImportError:
            logger.warning(
                "browser_stealth=true but playwright_stealth is not installed; "
                "continuing without stealth patches. Run: "
                "pip install tf-playwright-stealth"
            )
            return None, "unavailable (pip install tf-playwright-stealth)"

        stealth_async = getattr(playwright_stealth, "stealth_async", None)
        if stealth_async is not None:

            async def _apply(page: Page) -> None:
                await stealth_async(page)

            return _apply, "active"

        try:
            from playwright_stealth import Stealth  # type: ignore
        except ImportError:
            logger.warning(
                "playwright_stealth is installed but exposes neither "
                "stealth_async nor the Stealth class; continuing without "
                "stealth patches."
            )
            return None, "unavailable (unsupported tf-playwright-stealth version)"
        stealth = Stealth()

        async def _apply_legacy(page: Page) -> None:
            await stealth.apply_stealth_async(page)

        return _apply_legacy, "active"
