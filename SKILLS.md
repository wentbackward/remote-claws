# SKILLS.md — Remote Claws Capabilities

## What This Server Provides

Remote Claws gives an AI agent full control of a remote desktop machine — the same kind of control a human sitting at the keyboard and screen would have. It is an MCP server that exposes tools over SSE/HTTP.

## Skill: Remote Desktop Control

**You can see the screen.** Take screenshots of the entire desktop or specific regions. Images are returned as compressed JPEG, suitable for vision-capable models to interpret and act on.

**You can use the mouse and keyboard.** Click, double-click, drag, scroll, type text, press hotkeys — anything a human can do with a mouse and keyboard. Target actions by screen coordinates (from screenshots) or by UI element names (more reliable for Windows apps).

**You can inspect Windows UI elements.** Enumerate buttons, text fields, checkboxes, and other controls within any window by name and type, without relying on screenshots. Click or read elements by name for precision that doesn't depend on screen resolution or theme.

## Skill: Browser Automation

**You can control a full Chromium browser.** Navigate to URLs, click links and buttons, fill out forms, read page content, execute JavaScript, and take page screenshots. All interactions use CSS selectors — no coordinate guessing required.

**The browser is persistent and stateful.** Pages stay loaded between tool calls. You can open multiple tabs, switch between them, and maintain sessions (cookies, local storage) across a multi-step workflow.

**You can extract structured data.** Read text content, HTML markup, or run JavaScript to pull data from the DOM. Combined with navigation and form-filling, you can automate any web-based workflow end to end.

## Skill: Command Execution

**You can run any command on the machine.** Execute programs, scripts, shell commands — anything the host OS can run. Commands start asynchronously and you can check back for output, send interactive input, or kill them.

**You can drive interactive programs.** Start a process, send lines to its stdin, read its stdout/stderr as it runs. This handles REPLs, installers, CLI tools that prompt for input, and long-running scripts.

## Skill: File Transfer

**You can read and write files on the machine.** Transfer file content as base64 in both directions. Read files in chunks for large transfers. List directories, check file metadata, move, rename, or delete files.

## Combining Skills

These skills compose naturally. Examples of compound workflows:

- **Install and configure software**: exec_run an installer, send interactive input, then take desktop screenshots to verify UI state.
- **Web scraping with file output**: browser_navigate to sites, browser_get_text to extract data, file_write to save results.
- **Automate a native app**: desktop_find_window to locate it, desktop_list_elements to discover controls, desktop_click_element to interact, desktop_screenshot to verify results.
- **Build and test code**: file_write source files, exec_run a build command, exec_get_output to check for errors, browser_navigate to a local dev server to verify.
- **Monitor a process**: exec_run a long-running task, periodically exec_get_output to check progress, desktop_screenshot to see if a GUI has changed.

## Connection

The server runs on the target Windows machine and listens for MCP clients over SSE/HTTP. Default endpoint: `http://<machine-ip>:8080/sse`. All tools are available to any connected agent, subject to the permission policy configured in `permissions.json`.

## Limitations

- Desktop coordinates are absolute pixels. After window moves or resolution changes, take a fresh screenshot before clicking.
- `desktop_type_text` only supports ASCII. For Unicode text, use clipboard-based approaches or browser_fill (which handles Unicode natively).
- Screenshots are JPEG at max 1280x960. Fine detail (small text, icons) may require a zoomed-in region screenshot.
- File transfers are base64 — there is overhead for very large files. Use chunked reads (offset/limit) to manage memory.
- The browser is Chromium only. Firefox and WebKit are not available.
- The server requires bearer token authentication. For additional protection, use IP allowlisting and run behind a VPN (Tailscale, WireGuard).
