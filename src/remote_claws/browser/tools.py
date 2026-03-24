from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP, Context, Image

from remote_claws.screenshot import downscale_and_encode, make_save_path


def _get_ctx(ctx: Context):
    return ctx.request_context.lifespan_context


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def browser_navigate(url: str, ctx: Context) -> str:
        """Navigate the browser to a URL. Returns page title, final URL, and HTTP status."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_navigate"):
            return "Permission denied: browser_navigate"
        page = await app.browser.get_page()
        response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        status = response.status if response else "unknown"
        title = await page.title()
        return f"Navigated to {page.url} (title: {title}, status: {status})"

    @mcp.tool()
    async def browser_click(selector: str, button: str = "left", click_count: int = 1, ctx: Context = None) -> str:
        """Click an element by CSS selector."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_click"):
            return "Permission denied: browser_click"
        page = await app.browser.get_page()
        await page.click(selector, button=button, click_count=click_count, timeout=10000)
        return f"Clicked {selector} (button={button}, count={click_count})"

    @mcp.tool()
    async def browser_fill(selector: str, value: str, ctx: Context = None) -> str:
        """Fill an input or textarea with a value. Clears existing content first."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_fill"):
            return "Permission denied: browser_fill"
        page = await app.browser.get_page()
        await page.fill(selector, value, timeout=10000)
        return f"Filled {selector} with value ({len(value)} chars)"

    @mcp.tool()
    async def browser_type(selector: str, text: str, delay: int = 0, ctx: Context = None) -> str:
        """Type text into an element keystroke by keystroke. Use delay (ms) for slow typing."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_type"):
            return "Permission denied: browser_type"
        page = await app.browser.get_page()
        await page.type(selector, text, delay=delay, timeout=10000)
        return f"Typed {len(text)} characters into {selector}"

    @mcp.tool()
    async def browser_press_key(key: str, ctx: Context = None) -> str:
        """Press a keyboard key (e.g. 'Enter', 'Escape', 'Tab', 'Control+a')."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_press_key"):
            return "Permission denied: browser_press_key"
        page = await app.browser.get_page()
        await page.keyboard.press(key)
        return f"Pressed key: {key}"

    @mcp.tool()
    async def browser_get_text(selector: str = "body", ctx: Context = None) -> str:
        """Get the inner text content of an element."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_get_text"):
            return "Permission denied: browser_get_text"
        page = await app.browser.get_page()
        text = await page.inner_text(selector, timeout=10000)
        return text

    @mcp.tool()
    async def browser_get_html(selector: str = "html", outer: bool = True, ctx: Context = None) -> str:
        """Get HTML content of an element. Set outer=False for innerHTML only."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_get_html"):
            return "Permission denied: browser_get_html"
        page = await app.browser.get_page()
        if outer:
            html = await page.locator(selector).evaluate("el => el.outerHTML")
        else:
            html = await page.inner_html(selector, timeout=10000)
        return html

    @mcp.tool()
    async def browser_eval_js(expression: str, ctx: Context = None) -> str:
        """Evaluate JavaScript in the page context. Returns JSON-serialized result."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_eval_js"):
            return "Permission denied: browser_eval_js"
        page = await app.browser.get_page()
        result = await page.evaluate(expression)
        return json.dumps(result, default=str)

    @mcp.tool()
    async def browser_screenshot(
        selector: str = "",
        full_page: bool = False,
        save_to_disk: bool = False,
        ctx: Context = None,
    ) -> Image:
        """Take a screenshot of the page or a specific element. Returns JPEG image."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_screenshot"):
            return "Permission denied: browser_screenshot"
        page = await app.browser.get_page()
        if selector:
            raw = await page.locator(selector).screenshot()
        else:
            raw = await page.screenshot(full_page=full_page)
        save_path = make_save_path(app.config.screenshot_dir) if save_to_disk else None
        jpeg_bytes, saved = downscale_and_encode(
            raw,
            max_width=app.config.screenshot_max_width,
            max_height=app.config.screenshot_max_height,
            quality=app.config.screenshot_quality,
            save_path=save_path,
        )
        return Image(data=jpeg_bytes, format="jpeg")

    @mcp.tool()
    async def browser_wait_for(selector: str, state: str = "visible", timeout: int = 10000, ctx: Context = None) -> str:
        """Wait for an element to reach a state: 'visible', 'hidden', 'attached', 'detached'."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_wait_for"):
            return "Permission denied: browser_wait_for"
        page = await app.browser.get_page()
        await page.wait_for_selector(selector, state=state, timeout=timeout)
        return f"Element {selector} reached state: {state}"

    @mcp.tool()
    async def browser_select_option(selector: str, value: str, ctx: Context = None) -> str:
        """Select a dropdown option by value or label text."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_select_option"):
            return "Permission denied: browser_select_option"
        page = await app.browser.get_page()
        selected = await page.select_option(selector, value, timeout=10000)
        return f"Selected option: {selected}"

    @mcp.tool()
    async def browser_go_back(ctx: Context = None) -> str:
        """Navigate the browser back in history."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_go_back"):
            return "Permission denied: browser_go_back"
        page = await app.browser.get_page()
        await page.go_back(wait_until="domcontentloaded")
        title = await page.title()
        return f"Navigated back to {page.url} (title: {title})"

    @mcp.tool()
    async def browser_go_forward(ctx: Context = None) -> str:
        """Navigate the browser forward in history."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_go_forward"):
            return "Permission denied: browser_go_forward"
        page = await app.browser.get_page()
        await page.go_forward(wait_until="domcontentloaded")
        title = await page.title()
        return f"Navigated forward to {page.url} (title: {title})"

    @mcp.tool()
    async def browser_tabs_list(ctx: Context = None) -> str:
        """List all open browser tabs with their URLs and titles."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_tabs_list"):
            return "Permission denied: browser_tabs_list"
        tabs = app.browser.list_tabs()
        for tab in tabs:
            page = app.browser._pages[tab["index"]]
            try:
                tab["title"] = await page.title()
            except Exception:
                tab["title"] = "(unknown)"
        return json.dumps(tabs, indent=2)

    @mcp.tool()
    async def browser_tab_new(url: str = "about:blank", ctx: Context = None) -> str:
        """Open a new browser tab, optionally navigating to a URL."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_tab_new"):
            return "Permission denied: browser_tab_new"
        page = await app.browser.new_tab(url)
        title = await page.title()
        return f"Opened new tab: {page.url} (title: {title})"

    @mcp.tool()
    async def browser_tab_close(index: int = -1, ctx: Context = None) -> str:
        """Close a browser tab by index (-1 = current tab)."""
        app = _get_ctx(ctx)
        if not app.permissions.is_allowed("browser_tab_close"):
            return "Permission denied: browser_tab_close"
        await app.browser.close_tab(index)
        remaining = len(app.browser._pages)
        return f"Closed tab {index}. {remaining} tab(s) remaining."
