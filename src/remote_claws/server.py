from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass

import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from remote_claws.auth import HashedTokenVerifier, load_token_hash
from remote_claws.config import AppConfig
from remote_claws.permissions import PermissionChecker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _diagnose_auth_source(raw_auth_values: list[str]) -> None:
    """Localise *which side* is duplicating the Authorization header.

    raw_auth_values is the list pulled directly from scope['headers']; its
    length tells us whether the wire actually carried multiple Authorization
    headers (client emitted twice) or a single value already containing a
    comma-joined pair (something upstream of us did the joining).

    For each case we then check whether the two halves are bytewise
    identical — if they are, the client knows exactly one token and is
    just sending it twice; if they differ, there are genuinely two distinct
    token sources somewhere in the client's config / env / proxy chain.
    """
    n = len(raw_auth_values)
    if n == 0:
        # Should not happen on the failing path (we got past the prefix check
        # above), but guard anyway so the diagnostic is never the thing that
        # crashes the request handler.
        logger.warning("  source: no Authorization header captured (unexpected)")
        return
    if n == 1:
        value = raw_auth_values[0]
        # Strip the leading 'Bearer ' once to compare the two halves cleanly.
        body = value[7:] if value.startswith("Bearer ") else value
        # Did the client (or an intermediate) join two values with ', '?
        if ", Bearer " in body:
            halves = body.split(", Bearer ", 1)
            same = halves[0] == halves[1]
            logger.warning(
                "  source: 1 Authorization header on the wire whose VALUE is comma-joined. "
                "halves identical=%s. This means whatever built the header value "
                "already concatenated two credentials — look in the client's config "
                "templating / env-var expansion. (A wire-level duplicate would have "
                "shown up as 2 separate headers.)",
                same,
            )
        else:
            logger.warning(
                "  source: 1 Authorization header, single value, no embedded join. "
                "Token simply doesn't match the server's hash — most likely the "
                "client is using an old token (regenerate vs. what's in client config)."
            )
        return
    # n >= 2: the client really sent the header more than once.
    unique = set(raw_auth_values)
    if len(unique) == 1:
        logger.warning(
            "  source: %d IDENTICAL Authorization headers on the wire. "
            "This is an MCP/HTTP client bug — it is emitting the same Authorization "
            "header from two code paths. Fix lives in the client (e.g. openclaw), "
            "not in remote-claws.",
            n,
        )
    else:
        logger.warning(
            "  source: %d DIFFERENT Authorization headers on the wire. "
            "There really are two distinct credential sources in the client's setup "
            "— grep its config dirs and env for both tokens to find them.",
            n,
        )


@dataclass
class AppContext:
    config: AppConfig
    # browser is None when the browser group is disabled at startup, in which
    # case Playwright is never imported. Tools in disabled groups are not
    # registered, so no tool will ever observe browser=None.
    browser: object | None
    permissions: PermissionChecker
    processes: dict  # remote_exec process tracker


def _build_permissions() -> tuple[AppConfig, PermissionChecker]:
    """Build the config + permission checker used by both registration and
    the lifespan. Kept as a single function so module import and main() can't
    drift."""
    config = AppConfig()
    permissions = PermissionChecker(
        config.permissions_file,
        enabled_groups=config.get_enabled_groups(),
    )
    return config, permissions


# Build config + permissions at import time so we can decide which tool groups
# to register before the MCP server starts answering tools/list requests.
_CONFIG, _PERMISSIONS = _build_permissions()


def _build_app_context() -> AppContext:
    """Build the process-level application context exactly once.

    Our state is process-scoped by design — one browser context, one exec
    process table — regardless of how many MCP sessions or requests the
    server handles. This matters because the MCP lifespan runs MORE than
    once per process: in stateless streamable-HTTP mode it runs per request,
    and in stateful/SSE modes it runs per client session. Building fresh
    state per run would wipe the process table on every call and let two
    sessions fight over the same Chrome profile lock.

    main() calls this eagerly before serving so environment problems (e.g.
    browser preflight) fail at boot, not on first tool call.
    """
    browser = None
    if _PERMISSIONS.is_group_active("browser"):
        # Local import: avoid pulling Playwright into memory when the browser
        # group is disabled.
        from remote_claws.browser.manager import BrowserManager, BrowserStartupError

        browser = BrowserManager(_CONFIG)
        # Validate the browser environment before we start serving. The
        # server is purposefully manually-run and non-daemon, so a hard
        # failure here is the right behaviour: the operator sees the error
        # immediately rather than discovering it through a confused agent
        # an hour into a session.
        try:
            browser.preflight()
        except BrowserStartupError as exc:
            logger.error("Browser preflight failed: %s", exc)
            raise
        # Surface the resolved browser config at boot, not on first tool
        # call — a wrong channel (e.g. a stale REMOTE_CLAWS_BROWSER_CHANNEL
        # in the shell session) is then obvious the moment the server starts.
        logger.info(
            "Browser config: channel=%s (source: %s), profile=%s, headless=%s, stealth=%s",
            _CONFIG.browser_channel,
            _CONFIG.source_of("browser_channel"),
            browser.profile_dir,
            _CONFIG.browser_headless,
            _CONFIG.browser_stealth,
        )

    logger.info("RemoteClaws starting up (host=%s, port=%s)", _CONFIG.host, _CONFIG.port)
    return AppContext(
        config=_CONFIG,
        browser=browser,
        permissions=_PERMISSIONS,
        processes={},
    )


# Process-level singleton, built eagerly by main(). The lock is created lazily
# because asyncio primitives bind to the running loop on first use.
_APP_CONTEXT: AppContext | None = None
_BUILD_LOCK: asyncio.Lock | None = None


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Yield the process-level AppContext singleton.

    Runs per request (stateless streamable-HTTP) or per session (stateful /
    SSE) depending on transport, so it must be cheap after first build and
    must NOT tear down on exit — teardown belongs to process shutdown and is
    handled by _RunOnShutdown in main().
    """
    global _APP_CONTEXT, _BUILD_LOCK
    if _APP_CONTEXT is None:
        if _BUILD_LOCK is None:
            _BUILD_LOCK = asyncio.Lock()
        async with _BUILD_LOCK:
            if _APP_CONTEXT is None:
                _APP_CONTEXT = _build_app_context()
    yield _APP_CONTEXT


async def _shutdown_app_context() -> None:
    """Process-exit teardown: kill tracked exec processes, close the browser."""
    from contextlib import suppress

    app = _APP_CONTEXT
    if app is None:
        return
    for proc_info in app.processes.values():
        proc = proc_info.get("process")
        if proc and proc.returncode is None:
            with suppress(Exception):
                proc.kill()
    if app.browser is not None:
        await app.browser.shutdown()
    logger.info("RemoteClaws shut down")


SERVER_INSTRUCTIONS = """\
You are controlling a REMOTE machine with a graphical desktop through four \
tools: remote_browser, remote_desktop, remote_exec, remote_files.

CRITICAL: these tools act on the REMOTE machine running this server — not on \
your local environment. If you also have similarly-named local tools (browser, \
exec, read, write, ...), they are DIFFERENT tools on a DIFFERENT machine. Use \
remote_* for anything on the remote machine.

Each remote_* tool takes an `action` parameter plus params, like a CLI \
subcommand: remote_browser(action="navigate", url="https://..."). Read each \
tool's description for its action list. An unknown action returns the list of \
valid ones.

Some actions may be denied by server policy — a denied action returns \
"permission denied"; do not retry it.

## Orientation

Always orient yourself before acting: remote_desktop(action="screenshot") or \
remote_browser(action="screenshot") to see the current state. Screenshots are \
JPEG, max 1280x960.

## Choosing the Right Tool

- **Web tasks**: remote_browser. CSS selectors — reliable and \
resolution-independent. navigate → get_text → click/fill/type → screenshot \
to verify.
- **Native app tasks**: remote_desktop. screenshot → find_window → \
focus_window → click_element by name (more reliable than coordinates) or \
mouse_click at coordinates from the screenshot.
- **Shell commands**: remote_exec. run returns a process_id immediately; \
get_output (wait=true to block) reads output; send_input writes stdin; kill \
when done.
- **Files**: remote_files. Content is base64. Chunk large reads with \
offset/limit.

## Important Notes

- Desktop coordinates are absolute pixels. After any window move/resize, \
re-screenshot before clicking. Moving the mouse to (0,0) aborts (failsafe).
- browser fill clears before typing; browser type appends. To select all \
first: press_key key="Control+a". desktop type_text is ASCII-only — for \
Unicode use browser fill or eval_js.
- Processes persist until killed or server shutdown — kill when done.
- file read returns base64 — decode before interpreting.
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

# Register tool groups. A group is only imported when it is active — this
# keeps Playwright / pyautogui out of memory on machines that don't need them.
# Within an active group, only individually-permitted tools get registered, so
# the MCP tools/list response reflects the policy exactly.
if _PERMISSIONS.is_group_active("browser"):
    from remote_claws.browser.tools import register as register_browser_tools

    register_browser_tools(mcp, _PERMISSIONS)

if _PERMISSIONS.is_group_active("desktop"):
    from remote_claws.desktop.tools import register as register_desktop_tools

    register_desktop_tools(mcp, _PERMISSIONS)

if _PERMISSIONS.is_group_active("exec"):
    from remote_claws.exec.tools import register as register_exec_tools

    register_exec_tools(mcp, _PERMISSIONS)

if _PERMISSIONS.is_group_active("files"):
    from remote_claws.files.tools import register as register_file_tools

    register_file_tools(mcp, _PERMISSIONS)

logger.info(
    "Active tool groups: %s",
    ", ".join(g for g in ("browser", "desktop", "exec", "files") if _PERMISSIONS.is_group_active(g)) or "(none)",
)


def main():
    import argparse
    import uvicorn
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.types import ASGIApp, Receive, Scope, Send

    # Argv overrides for the two settings people most often want to change
    # ad-hoc (host/port). Env vars and the JSON config file are still the
    # canonical configuration; argv just wins when present so users don't
    # have to remember REMOTE_CLAWS_PORT for a one-off run.
    parser = argparse.ArgumentParser(
        prog="remote-claws",
        description="Run the Remote Claws MCP server.",
    )
    parser.add_argument(
        "--host",
        help="Bind address (overrides REMOTE_CLAWS_HOST / config.host).",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Listen port (overrides REMOTE_CLAWS_PORT / config.port).",
    )
    args = parser.parse_args()

    config = _CONFIG
    if args.host is not None:
        config.host = args.host
    if args.port is not None:
        config.port = args.port

    # Load auth — refuse to start without it
    try:
        token_hash = load_token_hash(config.auth_file)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    verifier = HashedTokenVerifier(token_hash)

    # Build the process-level app context eagerly so configuration problems
    # (e.g. browser preflight failures) abort startup here, before we begin
    # serving — not on the first tool call an agent makes.
    global _APP_CONTEXT
    _APP_CONTEXT = _build_app_context()

    # ASGI wrapper that runs app-context teardown after the wrapped app has
    # completed its own shutdown. The MCP lifespan cannot own teardown: in
    # stateless streamable-HTTP mode it runs per request, so its exit would
    # kill tracked processes and the browser after every call.
    class _RunOnShutdown:
        def __init__(self, app: ASGIApp, teardown) -> None:
            self.app = app
            self._teardown = teardown

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "lifespan":
                await self.app(scope, receive, send)
                return

            async def send_wrapper(message):
                if message["type"] == "lifespan.shutdown.complete":
                    await self._teardown()
                await send(message)

            await self.app(scope, receive, send_wrapper)

    # Bearer token middleware
    class BearerTokenMiddleware:
        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            # Pull every Authorization header straight from the ASGI scope
            # so we can tell the difference between
            #   * one header sent twice on the wire (client bug — e.g. the
            #     MCP client emits the header from two code paths) — the
            #     ASGI spec preserves duplicates as separate entries.
            #   * one header whose value already contains a comma-joined
            #     pair (something upstream of us did the joining — a proxy,
            #     or the client built the value that way itself).
            # Starlette's Request.headers.get() collapses duplicates with
            # ', ' which loses this signal, so we look at scope["headers"]
            # directly.
            raw_auth_values: list[str] = [
                v.decode("latin-1") for k, v in scope.get("headers", []) if k.lower() == b"authorization"
            ]
            request = Request(scope)
            client = scope.get("client")
            client_ip = client[0] if client else "unknown"
            path = scope.get("path", "?")
            method = scope.get("method", "?")
            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                # Log a small prefix so the operator can see what the client
                # actually sent (most common cause: the client config
                # already includes 'Bearer ' so the wire value ends up as
                # something like 'Basic ...' or just the raw token).
                preview = auth_header[:20] if auth_header else "(empty)"
                logger.warning(
                    "AUTH FAILURE — ip=%s method=%s path=%s — "
                    "header does not start with 'Bearer '. Got prefix=%r (length=%d)",
                    client_ip,
                    method,
                    path,
                    preview,
                    len(auth_header),
                )
                response = JSONResponse({"error": "Missing or invalid Authorization header"}, status_code=401)
                await response(scope, receive, send)
                return

            token = auth_header[7:]
            result = await verifier.verify_token(token)
            if result is None:
                # Diagnostic: prefix + suffix + a few telltales.
                # remote-claws-setup mints 48 random bytes → 64-char base64url
                # token, so any other length signals a copy-paste accident:
                # truncation, double 'Bearer ' prefix, JWT (has dots),
                # trailing newline/whitespace, two tokens concatenated, etc.
                # We only log a short prefix and suffix — the remaining ~34
                # chars preserve enough entropy that this is not a meaningful
                # disclosure to anyone with access to the server log.
                EXPECTED_LEN = 64
                head = token[:20] if token else "(empty)"
                tail = token[-10:] if len(token) > 30 else ""
                tells = []
                if "." in token:
                    tells.append("contains '.' (looks like a JWT)")
                if "Bearer" in token:
                    tells.append("contains the word 'Bearer' inside the token")
                if any(c.isspace() for c in token):
                    tells.append("contains whitespace/newline")
                if len(token) == 2 * EXPECTED_LEN:
                    tells.append("length is exactly 2x expected (pasted twice?)")
                logger.warning(
                    "AUTH FAILURE — ip=%s method=%s path=%s — "
                    "token did not match. head=%r tail=%r length=%d expected=%d%s",
                    client_ip,
                    method,
                    path,
                    head,
                    tail,
                    len(token),
                    EXPECTED_LEN,
                    (" [" + "; ".join(tells) + "]") if tells else "",
                )
                _diagnose_auth_source(raw_auth_values)
                response = JSONResponse({"error": "Invalid bearer token"}, status_code=401)
                await response(scope, receive, send)
                return

            await self.app(scope, receive, send)

    # Source IP allowlist middleware — drops connections before any other processing
    class IPAllowlistMiddleware:
        def __init__(self, app: ASGIApp, allowed_ips: list[str]) -> None:
            self.app = app
            self.allowed_ips = set(allowed_ips)

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "http":
                client = scope.get("client")
                client_ip = client[0] if client else None
                if client_ip not in self.allowed_ips:
                    logger.warning("Rejected connection from %s (not in allowed_ips)", client_ip)
                    response = JSONResponse(
                        {"error": "Forbidden — source IP not allowed"},
                        status_code=403,
                    )
                    await response(scope, receive, send)
                    return
            await self.app(scope, receive, send)

    # Pick the transport — SSE (legacy, works with Claude Desktop, openclaw)
    # or streamable-HTTP (MCP spec 2025-03-26+, works with Claude Code and
    # newer SDKs). Only one at a time; the SDK's streamable-HTTP manager
    # requires run() to be called first and we're not using that pattern.
    mcp.settings.host = config.host
    mcp.settings.port = config.port

    if config.transport == "streamable-http":
        logger.info("Transport: streamable-HTTP (MCP spec 2025-03-26+)")
        # Run the MCP session layer statelessly. All of our real state lives
        # in AppContext (browser manager, process table), not in MCP sessions.
        # Stateful sessions are held in server memory, so every server restart
        # bricked every connected client with 404 "Session not found" until
        # the client re-initialized. Stateless requests are self-contained.
        mcp.settings.stateless_http = True
        starlette_app = mcp.streamable_http_app()
    else:
        logger.info("Transport: SSE (legacy)")
        starlette_app = mcp.sse_app()

    # Host header validation
    allowed_hosts = config.get_allowed_hosts()
    if allowed_hosts != ["*"]:
        from starlette.middleware.trustedhost import TrustedHostMiddleware

        starlette_app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
        logger.info("Trusted hosts: %s", ", ".join(allowed_hosts))
    else:
        logger.info("Host checking disabled (allowed_hosts='*')")

    # Bearer token auth
    starlette_app.add_middleware(BearerTokenMiddleware)

    # IP allowlist — outermost layer (added last = runs first)
    allowed_ips = config.get_allowed_ips()
    if allowed_ips:
        starlette_app.add_middleware(IPAllowlistMiddleware, allowed_ips=allowed_ips)
        logger.info("IP allowlist enabled: %s", ", ".join(allowed_ips))

    logger.info("Auth enabled — bearer token required for all connections")

    # Outermost wrapper: runs app-context teardown after the app shuts down.
    final_app = _RunOnShutdown(starlette_app, _shutdown_app_context)

    uvicorn_config = uvicorn.Config(
        final_app,
        host=config.host,
        port=config.port,
        log_level="info",
    )
    server = uvicorn.Server(uvicorn_config)
    # uvicorn handles SIGINT internally and shuts itself down cleanly, but on
    # Python 3.11+ asyncio.run() re-raises the KeyboardInterrupt afterwards,
    # which would otherwise dump a full traceback over the operator's clean
    # shutdown log. Catch it and exit quietly — the server is purposefully
    # interactive and Ctrl+C is the documented way to stop it.
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        logger.info("Interrupted — exiting.")


if __name__ == "__main__":
    main()
