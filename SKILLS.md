# SKILLS.md — Remote Claws Capabilities

## What This Server Provides

Remote Claws gives an AI agent full control of a remote desktop machine — the same kind of control a human sitting at the keyboard and screen would have. It is an MCP server that exposes **4 tools covering 39 actions** over SSE/HTTP: `remote_browser`, `remote_desktop`, `remote_exec`, `remote_files`. Each tool takes an `action` parameter plus that action's params, like a CLI subcommand.

The `remote_` prefix is deliberate: these tools act on the **remote** machine. If the agent also has local tools named `browser`, `exec`, `read`, or `write`, those are different tools on a different machine.

## Skill: Remote Desktop Control

**You can see the screen.** `remote_desktop(action="screenshot")` captures the full desktop or a region. Images are returned as compressed JPEG, suitable for vision-capable models to interpret and act on.

**You can use the mouse and keyboard.** Click, double-click, drag, scroll, type text, press hotkeys — anything a human can do with a mouse and keyboard. Target actions by screen coordinates (from screenshots) or by UI element names (more reliable for Windows apps).

**You can inspect Windows UI elements.** `remote_desktop(action="list_elements", ...)` enumerates buttons, text fields, checkboxes, and other controls within any window by name and type, without relying on screenshots. `click_element` and `get_element_text` act by element name for precision that doesn't depend on screen resolution or theme.

## Skill: Browser Automation

**You can control the system Chrome browser with a persistent profile.** `remote_browser(action="navigate", url=...)`, `click`, `fill`, `get_text`, `eval_js`, `screenshot` — all interactions use CSS selectors, no coordinate guessing required.

**The browser is persistent and stateful.** Pages stay loaded between calls. Open multiple tabs (`tab_new`, `tabs_list`, `tab_close`), switch between them, and maintain sessions (cookies, local storage) across a multi-step workflow.

**You can extract structured data.** Read text content (`get_text`), HTML markup (`get_html`), or run JavaScript (`eval_js`) to pull data from the DOM. Combined with navigation and form-filling, you can automate any web-based workflow end to end.

## Skill: Command Execution

**You can run any command on the machine.** `remote_exec(action="run", command=...)` executes programs, scripts, shell commands — anything the host OS can run. Commands start asynchronously; check back with `get_output`, send interactive input with `send_input`, or `kill` them.

**You can drive interactive programs.** Start a process, send lines to its stdin, read its stdout/stderr as it runs. This handles REPLs, installers, CLI tools that prompt for input, and long-running scripts.

## Skill: File Transfer

**You can read and write files on the machine.** `remote_files(action="read" | "write", ...)` transfers content as base64 in both directions. Read in chunks with offset/limit for large files. `list` directories, check metadata with `info`, `move`, rename, or `delete`.

## Combining Skills

These skills compose naturally. Examples of compound workflows:

- **Install and configure software**: `remote_exec(action="run", ...)` an installer, `send_input` for interactive prompts, then `remote_desktop(action="screenshot")` to verify UI state.
- **Web scraping with file output**: `remote_browser(action="navigate", ...)` to sites, `get_text` to extract data, `remote_files(action="write", ...)` to save results.
- **Automate a native app**: `remote_desktop(action="find_window", ...)` to locate it, `list_elements` to discover controls, `click_element` to interact, `screenshot` to verify results.
- **Build and test code**: `remote_files(action="write", ...)` source files, `remote_exec(action="run", ...)` a build command, `get_output` to check for errors, `remote_browser(action="navigate", ...)` to a local dev server to verify.
- **Monitor a process**: `remote_exec(action="run", ...)` a long-running task, periodically `get_output` to check progress, `remote_desktop(action="screenshot")` to see if a GUI has changed.

## Connection

The server runs on the target machine and listens for MCP clients over SSE/HTTP. Default endpoint: `http://<machine-ip>:8080/sse`. All tools are available to any connected agent, subject to the permission policy configured in `permissions.json`.

## Limitations

- Desktop coordinates are absolute pixels. After window moves or resolution changes, take a fresh screenshot before clicking.
- `remote_desktop(action="type_text", ...)` only supports ASCII. For Unicode text, use `remote_browser(action="fill", ...)` (which handles Unicode natively) or clipboard-based approaches.
- Screenshots are JPEG at max 1280x960. Fine detail (small text, icons) may require a zoomed-in region screenshot.
- File transfers are base64 — there is overhead for very large files. Use chunked reads (offset/limit) to manage memory.
- The browser is Chrome/Chromium only. Firefox and WebKit are not available.
- The server requires bearer token authentication. For additional protection, use IP allowlisting and run behind a VPN (Tailscale, WireGuard).
