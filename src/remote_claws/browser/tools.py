from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP, Image

from remote_claws.dispatch import Handler, run_action
from remote_claws.permissions import PermissionChecker
from remote_claws.screenshot import downscale_and_encode, make_save_path


async def h_navigate(
    app: Any,
    url: str,
    wait_until: str = "load",
    settle_ms: int = 0,
    timeout: int = 30000,
) -> str:
    import asyncio as _asyncio

    page = await app.browser.get_page()
    response = await page.goto(url, wait_until=wait_until, timeout=timeout)
    if settle_ms > 0:
        await _asyncio.sleep(settle_ms / 1000)
    status = response.status if response else "unknown"
    title = await page.title()
    return f"Navigated to {page.url} (title: {title}, status: {status})"


async def h_click(app: Any, selector: str, button: str = "left", click_count: int = 1) -> str:
    page = await app.browser.get_page()
    await page.click(selector, button=button, click_count=click_count, timeout=10000)
    return f"Clicked {selector} (button={button}, count={click_count})"


async def h_fill(app: Any, selector: str, value: str) -> str:
    page = await app.browser.get_page()
    await page.fill(selector, value, timeout=10000)
    return f"Filled {selector} with value ({len(value)} chars)"


async def h_type(app: Any, selector: str, text: str, delay: int = 0) -> str:
    page = await app.browser.get_page()
    await page.type(selector, text, delay=delay, timeout=10000)
    return f"Typed {len(text)} characters into {selector}"


async def h_press_key(app: Any, key: str) -> str:
    page = await app.browser.get_page()
    await page.keyboard.press(key)
    return f"Pressed key: {key}"


async def h_get_text(app: Any, selector: str = "body") -> str:
    page = await app.browser.get_page()
    return await page.inner_text(selector, timeout=10000)


async def h_get_html(app: Any, selector: str = "html", outer: bool = True) -> str:
    page = await app.browser.get_page()
    if outer:
        return await page.locator(selector).evaluate("el => el.outerHTML")
    return await page.inner_html(selector, timeout=10000)


async def h_eval_js(app: Any, expression: str) -> str:
    page = await app.browser.get_page()
    result = await page.evaluate(expression)
    return json.dumps(result, default=str)


async def h_screenshot(
    app: Any,
    selector: str = "",
    full_page: bool = False,
    save_to_disk: bool = False,
) -> Image:
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


async def h_wait_for(app: Any, selector: str, state: str = "visible", timeout: int = 10000) -> str:
    page = await app.browser.get_page()
    await page.wait_for_selector(selector, state=state, timeout=timeout)
    return f"Element {selector} reached state: {state}"


async def h_select_option(app: Any, selector: str, value: str) -> str:
    page = await app.browser.get_page()
    selected = await page.select_option(selector, value, timeout=10000)
    return f"Selected option: {selected}"


async def h_go_back(app: Any) -> str:
    page = await app.browser.get_page()
    await page.go_back(wait_until="domcontentloaded")
    title = await page.title()
    return f"Navigated back to {page.url} (title: {title})"


async def h_go_forward(app: Any) -> str:
    page = await app.browser.get_page()
    await page.go_forward(wait_until="domcontentloaded")
    title = await page.title()
    return f"Navigated forward to {page.url} (title: {title})"


async def h_tabs_list(app: Any) -> str:
    tabs = app.browser.list_tabs()
    for tab in tabs:
        page = app.browser._pages[tab["index"]]
        try:
            tab["title"] = await page.title()
        except Exception:
            tab["title"] = "(unknown)"
    return json.dumps(tabs, indent=2)


async def h_tab_new(app: Any, url: str = "about:blank") -> str:
    page = await app.browser.new_tab(url)
    title = await page.title()
    return f"Opened new tab: {page.url} (title: {title})"


async def h_tab_close(app: Any, index: int = -1) -> str:
    await app.browser.close_tab(index)
    remaining = len(app.browser._pages)
    return f"Closed tab {index}. {remaining} tab(s) remaining."


HANDLERS: dict[str, Handler] = {
    "navigate": h_navigate,
    "click": h_click,
    "fill": h_fill,
    "type": h_type,
    "press_key": h_press_key,
    "get_text": h_get_text,
    "get_html": h_get_html,
    "eval_js": h_eval_js,
    "screenshot": h_screenshot,
    "wait_for": h_wait_for,
    "select_option": h_select_option,
    "go_back": h_go_back,
    "go_forward": h_go_forward,
    "tabs_list": h_tabs_list,
    "tab_new": h_tab_new,
    "tab_close": h_tab_close,
}


def register(mcp: FastMCP, permissions: PermissionChecker) -> None:
    """Register the single remote_browser tool when the browser group is active."""

    @mcp.tool()
    async def remote_browser(
        action: str,
        url: str = "",
        selector: str = "",
        value: str = "",
        text: str = "",
        key: str = "",
        expression: str = "",
        button: str = "left",
        click_count: int = 1,
        delay: int = 0,
        state: str = "visible",
        timeout: int = 10000,
        wait_until: str = "load",
        settle_ms: int = 0,
        outer: bool = True,
        full_page: bool = False,
        save_to_disk: bool = False,
        index: int = -1,
        ctx: Context = None,
    ) -> Any:
        """Control the web browser on the REMOTE machine (persistent system Chrome via
Playwright). All selectors are CSS selectors. The browser is stateful: pages,
tabs, cookies and logins persist between calls. Returns text (JSON) for most
actions, a JPEG image for screenshot.

Actions (params not listed for an action are ignored):

Navigation
  navigate url=<url> [wait_until=load] [settle_ms=0] [timeout=30000]
      Go to a URL. wait_until: commit | domcontentloaded | load | networkidle.
      settle_ms: extra pause after load (SPA hydration, anti-bot interstitials).
      Returns final URL, title, HTTP status.
  go_back | go_forward      Move through tab history. No params.

Interaction
  click selector=<css> [button=left] [click_count=1]
      Click an element. click_count=2 for double-click.
  fill selector=<css> value=<text>
      Set input/textarea value: clears first, fires change events, Unicode-safe.
  type selector=<css> text=<text> [delay=0]
      Type keystroke-by-keystroke (appends, does NOT clear). delay in ms/key.
      To select all before replacing: press_key key="Control+a" first.
  press_key key=<key>       One key or combo: "Enter", "Escape", "Tab", "Control+a".
  select_option selector=<css> value=<value-or-label>
      Choose a <select> option.

Reading
  get_text [selector=body]  Visible inner text of an element.
  get_html [selector=html] [outer=true]
      HTML markup; outer=false for innerHTML only.
  eval_js expression=<js>   Run JavaScript in the page; JSON-serialized result.
      Use this to clear a field without typing, read computed state, etc.

Waiting & capture
  wait_for selector=<css> [state=visible] [timeout=10000]
      Block until the element reaches state: visible | hidden | attached | detached.
  screenshot [selector=<css>] [full_page=false] [save_to_disk=false]
      JPEG of viewport, full page, or one element.

Tabs
  tabs_list                 All open tabs (index, url, title).
  tab_new [url=about:blank] Open a tab (becomes active).
  tab_close [index=-1]      Close a tab (-1 = current).

Unknown actions return the valid action list. Denied actions return a
permission error — do not retry them.
"""
        app = ctx.request_context.lifespan_context
        return await run_action(
            group="browser",
            handlers=HANDLERS,
            action=action,
            app=app,
            params={
                "url": url,
                "selector": selector,
                "value": value,
                "text": text,
                "key": key,
                "expression": expression,
                "button": button,
                "click_count": click_count,
                "delay": delay,
                "state": state,
                "timeout": timeout,
                "wait_until": wait_until,
                "settle_ms": settle_ms,
                "outer": outer,
                "full_page": full_page,
                "save_to_disk": save_to_disk,
                "index": index,
            },
            permissions=permissions,
        )
