---
name: remote-claws
description: "Full control of a remote machine via Remote Claws MCP: screenshots, mouse/keyboard, browser automation, run commands, read/write files on the remote host."
homepage: https://github.com/wentbackward/remote-claws
---

# Remote Claws — Remote Machine Control

Controls a remote machine over MCP. Four tools, each taking an `action`
parameter (like a CLI subcommand): `remote_browser`, `remote_desktop`,
`remote_exec`, `remote_files`. Read each tool's description for its action
list — an unknown action returns the valid list.

## CRITICAL: Remote vs Local

The `remote_*` tools act on the REMOTE machine. OpenClaw's built-in `browser`,
`exec`, `read`/`write`/`edit` act on the LOCAL gateway machine. They are
different machines — never substitute one for the other. If the user says
"on Windows", "on the remote machine", or names the remote host, you MUST use
`remote_*` tools.

## Strategy

1. **Screenshot first.** `remote_desktop(action="screenshot")` before clicking
   or typing; use the returned coordinates to target actions. Re-screenshot
   after actions — windows move, dialogs appear.
2. **Prefer remote_browser for web tasks.** CSS selectors are
   resolution-independent. Only fall back to `remote_desktop` for things the
   browser can't reach (native dialogs, file pickers).
3. **Prefer element names over coordinates.** `remote_desktop(action=
   "click_element", ...)` targets controls by name — survives window moves.
4. **Exec is async.** `remote_exec(action="run", ...)` returns a process_id;
   poll with `action="get_output"` (wait=true blocks), `action="send_input"`
   for stdin, `action="kill"` when done.
5. **Denied actions are final.** A "permission denied" result means server
   policy — do not retry.

## Common actions

- Desktop: screenshot, mouse_click, mouse_move, mouse_drag, scroll,
  type_text (ASCII only), press_key, find_window, focus_window,
  list_elements, click_element, get_element_text
- Browser: navigate, click, fill (clears first, Unicode-safe), type
  (appends), press_key, get_text, get_html, eval_js, screenshot, wait_for,
  select_option, go_back, go_forward, tabs_list, tab_new, tab_close
- Exec: run, get_output, send_input, kill, list
- Files: read (base64, offset/limit for chunks), write (base64), list,
  delete, move, info

## Authentication & Security

The remote-claws MCP server requires a bearer token, configured in
`openclaw.json` when registering the server. Unauthenticated connections get
401. The server also supports IP allowlisting (`allowed_ips`), host header
validation (`allowed_hosts`), and per-action permission policies
(`permissions.json`). See the [setup guide](https://github.com/wentbackward/remote-claws/blob/master/remote-claws-openclaw-setup-guide.md)
and [README](https://github.com/wentbackward/remote-claws#security).

## Important Notes

- Screenshots are JPEG, max 1280x960. Coordinates are absolute pixels.
- **Text-only model?** If your primary model can't accept inline images, call
  `remote_desktop(action="screenshot", save_to_disk=true)` — it returns a file
  path as text. Fetch the file with `remote_files(action="read", path=...)` and
  hand it to the image tool, which routes to the vision-capable imageModel.
- `type_text` is ASCII only. For Unicode, use browser `fill`, or clipboard:
  `remote_exec(action="run", command="powershell", args=["Set-Clipboard", ...])`
  then `remote_desktop(action="press_key", keys="ctrl+v")`.
- File content is base64 encoded. Decode after reading.
- The browser launches on first use and stays open across calls. Sessions
  persist (cookies, local storage).
