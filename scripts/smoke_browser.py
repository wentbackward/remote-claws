#!/usr/bin/env python3
"""Smoke test for the browse-as-user mode of a running remote-claws server.

Connects to the SSE endpoint with a bearer token and drives a short
real-world browsing session that exercises the persistent-Chrome /
stealth path:

  1. Open https://x.com, list visible posts on the primary column.
  2. Open https://www.bloomberg.com, scrape headlines and pick the
     first story link that looks like an article URL.
  3. Navigate the tab to that link and report where we landed.

Each step prints a one-line summary and saves a screenshot under
./smoke-screenshots/ so you can confirm visually that real Chrome (with
your logged-in profile) actually got past the paywalls / bot walls.
Step failures are reported but do not abort the run \u2014 you get a
holistic picture of what worked and what didn't.

Usage
-----
On your dev machine (NOT the Windows box):

    python -m venv .smoke-venv
    .smoke-venv/bin/activate          # or .smoke-venv\\Scripts\\activate on Windows
    pip install "mcp[cli]>=1.20"

    export REMOTE_CLAWS_URL="http://<windows-tailscale-ip>:8080/sse"
    export REMOTE_CLAWS_TOKEN="<bearer token from remote-claws-setup>"

    python scripts/smoke_browser.py

Or as flags:

    python scripts/smoke_browser.py \\
        --url http://192.168.1.42:8080/sse \\
        --token YOUR_TOKEN_HERE
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import textwrap
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from mcp import ClientSession
    from mcp.client.sse import sse_client
except ImportError:
    print(
        "ERROR: the 'mcp' package is not installed. Run:\n"
        "    pip install \"mcp[cli]>=1.20\"",
        file=sys.stderr,
    )
    sys.exit(1)


SCREENSHOT_DIR = Path("smoke-screenshots")


# ---------------------------------------------------------------------------
# small printing helpers \u2014 the operator runs this interactively, so prefer
# obvious section headers over structured logging
# ---------------------------------------------------------------------------
def banner(msg: str) -> None:
    print()
    print("=" * 72)
    print(f"  {msg}")
    print("=" * 72)


def step(num: int, msg: str) -> None:
    print(f"\n[{num}] {msg}")


def ok(msg: str) -> None:
    print(f"    \u2713 {msg}")


def warn(msg: str) -> None:
    print(f"    ! {msg}")


def fail(msg: str) -> None:
    print(f"    \u2717 {msg}")


# ---------------------------------------------------------------------------
# Tool-result decoders. The MCP SDK returns CallToolResult; we want the
# narrow slice we actually care about.
# ---------------------------------------------------------------------------
def text_of(result: Any) -> str:
    """Concatenate every TextContent in the result. Empty string when none."""
    parts = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def image_bytes_of(result: Any) -> bytes | None:
    """Return the first ImageContent payload as raw bytes, or None."""
    for item in getattr(result, "content", []) or []:
        data = getattr(item, "data", None)
        if data:
            # MCP wire format is base64 text; SDK exposes it as a str.
            return base64.b64decode(data)
    return None


def is_error(result: Any) -> bool:
    return bool(getattr(result, "isError", False))


# ---------------------------------------------------------------------------
# The driver itself
# ---------------------------------------------------------------------------
class Driver:
    """Thin wrapper around ClientSession that adds screenshot capture and
    consistent error reporting per call. Keeps the scripted flow readable."""

    def __init__(self, session: ClientSession, screenshot_dir: Path):
        self.session = session
        self.screenshot_dir = screenshot_dir
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._shot_counter = 0

    async def call(self, tool: str, **arguments: Any) -> Any:
        """Call a tool, surface errors as warnings, return the raw result."""
        try:
            result = await self.session.call_tool(tool, arguments)
        except Exception as exc:  # noqa: BLE001 \u2014 we want to keep going
            fail(f"{tool} raised {type(exc).__name__}: {exc}")
            return None
        if is_error(result):
            fail(f"{tool} returned error: {text_of(result)[:200]}")
        return result

    async def screenshot(self, label: str) -> Path | None:
        """Capture a screenshot and save it under a numbered, labelled file."""
        result = await self.call("browser_screenshot")
        if result is None:
            return None
        data = image_bytes_of(result)
        if data is None:
            warn(f"screenshot for '{label}' returned no image data")
            return None
        self._shot_counter += 1
        path = self.screenshot_dir / f"{self._shot_counter:02d}-{label}.jpg"
        path.write_bytes(data)
        ok(f"screenshot saved \u2192 {path}  ({len(data):,} bytes)")
        return path


# ---------------------------------------------------------------------------
# Scripted flow
# ---------------------------------------------------------------------------
async def run_smoke(driver: Driver) -> None:
    # ---- 0. sanity: list tools so we can confirm browser_* are registered
    step(0, "List tools to confirm browser group is active")
    tools = await driver.session.list_tools()
    names = sorted(t.name for t in tools.tools)
    browser_names = [n for n in names if n.startswith("browser_")]
    print(f"    {len(names)} tools total, {len(browser_names)} in browser group")
    if not browser_names:
        fail("no browser_* tools visible \u2014 is the browser group enabled and permitted?")
        return
    ok(f"browser tools: {', '.join(browser_names[:5])}{' ...' if len(browser_names) > 5 else ''}")

    # ---- 1. x.com
    step(1, "Open https://x.com/home and pull visible posts")
    # /home goes straight to the timeline when signed in (the bare /
    # serves a marketing splash even for logged-in users). wait_until=load
    # + a settle pause give X's SPA time to hydrate the feed before we
    # scrape — domcontentloaded fires far too early for a JS-driven app.
    nav = await driver.call(
        "browser_navigate",
        url="https://x.com/home",
        wait_until="load",
        settle_ms=4000,
    )
    if nav: ok(text_of(nav).strip())

    # Wait for either a tweet article (signed in) or the sign-in form
    # (signed out) so the script can report which it saw.
    await driver.call(
        "browser_wait_for",
        selector='article, [data-testid="loginButton"]',
        state="visible",
        timeout=20000,
    )

    posts = await driver.call(
        "browser_eval_js",
        expression=textwrap.dedent("""
            (() => {
                const articles = Array.from(document.querySelectorAll('article'));
                return articles.slice(0, 5).map(a => {
                    const text = (a.innerText || '').trim().replace(/\\s+/g, ' ');
                    return text.length > 240 ? text.slice(0, 240) + '\u2026' : text;
                });
            })()
        """).strip(),
    )
    if posts:
        try:
            items = json.loads(text_of(posts))
        except json.JSONDecodeError:
            items = []
        if items:
            ok(f"pulled {len(items)} post(s) from x.com primary column")
            for i, t in enumerate(items, 1):
                print(f"        [{i}] {t}")
        else:
            warn(
                "no post articles visible \u2014 you're likely not signed in to X "
                "in the dedicated profile. Run remote-claws-browser-setup --url "
                "https://x.com on the server to sign in."
            )
    await driver.screenshot("x-com")

    # ---- 2. bloomberg.com
    step(2, "Open https://www.bloomberg.com and scrape headlines + first story link")
    # Bloomberg sits behind a Cloudflare JS challenge that resolves itself
    # in a few seconds with real Chrome + stealth. settle_ms gives the
    # challenge time to clear before we scrape, otherwise we'd get the
    # interstitial HTML (title 'Are you a robot?', status 403).
    nav = await driver.call(
        "browser_navigate",
        url="https://www.bloomberg.com",
        wait_until="load",
        settle_ms=6000,
    )
    if nav:
        nav_text = text_of(nav).strip()
        ok(nav_text)
        if "robot" in nav_text.lower() or "status: 403" in nav_text:
            warn(
                "Cloudflare challenge appears to still be up. Check the "
                "server log for the 'Browser context launched ... stealth=...' "
                "line: stealth must say 'active'. If it says 'unavailable', "
                "run `pip install tf-playwright-stealth` on the server."
            )

    # Bloomberg's headline markup shifts; scan every anchor and pick ones
    # whose href looks like an article URL. Returns up to 8 headline+href
    # pairs and the chosen target link.
    scrape = await driver.call(
        "browser_eval_js",
        expression=textwrap.dedent("""
            (() => {
                const seen = new Set();
                const items = [];
                for (const a of document.querySelectorAll('a[href]')) {
                    const href = a.href;
                    if (!/\\/news\\/articles\\//.test(href)) continue;
                    if (seen.has(href)) continue;
                    seen.add(href);
                    const text = (a.innerText || a.textContent || '').trim().replace(/\\s+/g, ' ');
                    if (!text || text.length < 12) continue;
                    items.push({ text: text.slice(0, 200), href });
                    if (items.length >= 8) break;
                }
                return { items, target: items.length ? items[0].href : null };
            })()
        """).strip(),
    )
    target_url: str | None = None
    if scrape:
        try:
            payload = json.loads(text_of(scrape))
        except json.JSONDecodeError:
            payload = {"items": [], "target": None}
        items = payload.get("items") or []
        target_url = payload.get("target")
        if items:
            ok(f"scraped {len(items)} headline(s) from bloomberg.com")
            for i, it in enumerate(items, 1):
                print(f"        [{i}] {it['text']}")
                print(f"            {it['href']}")
        else:
            warn("no article-shaped links found on bloomberg.com landing page")
    await driver.screenshot("bloomberg-home")

    # ---- 3. follow the chosen story link in the same tab
    step(3, "Navigate the tab to the chosen story")
    if not target_url:
        fail("no target URL available; skipping story navigation")
        return
    print(f"    target: {target_url}")
    nav = await driver.call(
        "browser_navigate",
        url=target_url,
        wait_until="load",
        settle_ms=3000,
    )
    if nav: ok(text_of(nav).strip())

    # Pull a chunk of the article body so the operator can see what we got
    # (paywalled or not \u2014 the navigation itself is what we're verifying).
    body = await driver.call(
        "browser_eval_js",
        expression=textwrap.dedent("""
            (() => {
                const root = document.querySelector('article') || document.body;
                const text = (root.innerText || '').trim().replace(/\\s+/g, ' ');
                return {
                    title: document.title,
                    url: location.href,
                    excerpt: text.slice(0, 600),
                    length: text.length,
                };
            })()
        """).strip(),
    )
    if body:
        try:
            info = json.loads(text_of(body))
            ok(f"landed on: {info.get('url')}")
            print(f"        title:   {info.get('title')}")
            print(f"        body:    {info.get('length'):,} chars visible")
            excerpt = (info.get("excerpt") or "").strip()
            if excerpt:
                print("        excerpt:")
                for line in textwrap.wrap(excerpt, width=68, initial_indent="          ", subsequent_indent="          "):
                    print(line)
        except json.JSONDecodeError:
            warn("could not parse article info JSON")
    await driver.screenshot("bloomberg-story")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
@asynccontextmanager
async def open_session(url: str, token: str):
    headers = {"Authorization": f"Bearer {token}"}
    async with sse_client(url, headers=headers) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def amain(url: str, token: str) -> int:
    banner(f"remote-claws browser smoke test \u2014 {datetime.now().isoformat(timespec='seconds')}")
    print(f"  endpoint: {url}")
    print(f"  screenshots: {SCREENSHOT_DIR.resolve()}")
    try:
        async with open_session(url, token) as session:
            driver = Driver(session, SCREENSHOT_DIR)
            await run_smoke(driver)
    except Exception as exc:  # noqa: BLE001
        banner("CONNECTION FAILED")
        print(f"  {type(exc).__name__}: {exc}")
        print()
        print("  Common causes:")
        print("    \u2022 server not reachable at the URL (firewall, wrong IP, server not running)")
        print("    \u2022 bearer token wrong")
        print("    \u2022 host header rejected (set REMOTE_CLAWS_ALLOWED_HOSTS=* on the server)")
        return 2
    banner("smoke test complete")
    print(f"  Review screenshots in {SCREENSHOT_DIR.resolve()}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="smoke_browser",
        description="Smoke-test a running remote-claws server's browser tools.",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("REMOTE_CLAWS_URL"),
        help="SSE endpoint, e.g. http://1.2.3.4:8080/sse (env REMOTE_CLAWS_URL)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("REMOTE_CLAWS_TOKEN"),
        help="Bearer token from remote-claws-setup (env REMOTE_CLAWS_TOKEN)",
    )
    ns = parser.parse_args()

    if not ns.url or not ns.token:
        parser.error(
            "both --url and --token (or REMOTE_CLAWS_URL / REMOTE_CLAWS_TOKEN) are required"
        )

    sys.exit(asyncio.run(amain(ns.url, ns.token)))


if __name__ == "__main__":
    main()
