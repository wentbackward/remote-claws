# TOOLS.md — Remote Claws Tool Reference

Remote Claws exposes **4 MCP tools** covering 39 actions. Each tool takes an
`action` parameter plus that action's params, like a CLI subcommand:

```
remote_browser(action="navigate", url="https://example.com")
```

An unknown action returns a JSON error listing the valid actions. Params not
listed for an action are ignored. Required params must be non-empty.

## Permissions

`permissions.json` gates at two levels:

- **Group level (registration time):** if a group is disabled or fully denied,
  its tool is never registered and never appears in `tools/list`.
- **Action level (call time):** `allow`/`deny` entries are bare action names
  per group; deny always wins. A denied action returns
  `{"error": "permission denied: <group>:<action>"}`.

Legacy entries using old tool names (`browser_navigate`, `file_read`) are
auto-normalized to bare action names at load, with a deprecation warning in
the server log.

---

## remote_browser

Control the web browser on the REMOTE machine (persistent system Chrome via
Playwright). All selectors are CSS selectors. The browser is stateful: pages,
tabs, cookies and logins persist between calls. Returns text (JSON) for most
actions, a JPEG image for `screenshot`.

| Action | Params | Description |
|--------|--------|-------------|
| `navigate` | `url` (required), `wait_until="load"`, `settle_ms=0`, `timeout=30000` | Go to a URL. `wait_until`: `commit` \| `domcontentloaded` \| `load` \| `networkidle`. `settle_ms`: extra pause after load (SPA hydration, anti-bot interstitials). Returns final URL, title, HTTP status. |
| `go_back` | — | Navigate back in tab history. |
| `go_forward` | — | Navigate forward in tab history. |
| `click` | `selector` (required), `button="left"`, `click_count=1` | Click an element. `click_count=2` for double-click. |
| `fill` | `selector` (required), `value` (required) | Set input/textarea value: clears first, fires change events, Unicode-safe. |
| `type` | `selector` (required), `text` (required), `delay=0` | Type keystroke-by-keystroke (appends, does NOT clear). `delay` in ms/key. To select all before replacing: `press_key key="Control+a"` first. |
| `press_key` | `key` (required) | One key or combo: `"Enter"`, `"Escape"`, `"Tab"`, `"Control+a"`. |
| `select_option` | `selector` (required), `value` (required) | Choose a `<select>` option by value or label. |
| `get_text` | `selector="body"` | Visible inner text of an element. |
| `get_html` | `selector="html"`, `outer=true` | HTML markup; `outer=false` for innerHTML only. |
| `eval_js` | `expression` (required) | Run JavaScript in the page; JSON-serialized result. Use to clear a field without typing, read computed state, etc. |
| `wait_for` | `selector` (required), `state="visible"`, `timeout=10000` | Block until element reaches state: `visible` \| `hidden` \| `attached` \| `detached`. |
| `screenshot` | `selector=""`, `full_page=false`, `save_to_disk=false` | JPEG of viewport, full page, or one element. |
| `tabs_list` | — | All open tabs (index, url, title). |
| `tab_new` | `url="about:blank"` | Open a tab (becomes active). |
| `tab_close` | `index=-1` | Close a tab (`-1` = current). |

## remote_desktop

Control the REMOTE machine's desktop: mouse, keyboard, screenshots, and
Windows UI automation. Coordinates are absolute screen pixels. Returns text
for most actions, a JPEG image for `screenshot`. Moving the mouse to (0,0)
aborts (pyautogui failsafe).

Workflow: screenshot first, act, re-screenshot to verify. Prefer element-name
actions over coordinates — coordinates break when windows move.

| Action | Params | Description |
|--------|--------|-------------|
| `screenshot` | `region=None` ([x,y,w,h]), `save_to_disk=false` | JPEG of the full screen or region, returned inline. With `save_to_disk=true`: save a PNG to the remote temp dir and return `{"path", "size_bytes"}` as text instead — for models that can't accept inline images; fetch via `remote_files` `read`. Each save deletes the previous temp file. |
| `mouse_click` | `x`, `y` (required), `button="left"`, `clicks=1` | Click at screen coordinates. `clicks=2` = double-click. |
| `mouse_move` | `x`, `y` (required), `duration=0.2` | Move cursor to coordinates. |
| `mouse_drag` | `start_x`, `start_y`, `end_x`, `end_y` (required), `duration=0.5` | Drag between coordinates. |
| `scroll` | `x`, `y` (required), `clicks=3`, `direction="down"` | Scroll at position. `direction`: `up` \| `down`. |
| `type_text` | `text` (required), `interval=0.02` | Type at current focus. ASCII only. |
| `press_key` | `keys` (required) | Key or combo: `"enter"`, `"ctrl+c"`, `"alt+tab"`, `"win"`. |
| `find_window` | `title=""`, `class_name=""` | List visible windows with title, class, rectangle (substring filters). |
| `focus_window` | `title` (required) | Bring matching window to foreground. |
| `list_elements` | `window_title` (required), `control_type=""`, `max_depth=4` | Enumerate controls (Button, Edit, ...) with name/automation_id. Capped at 200. |
| `click_element` | `window_title`, `element_name` (required), `control_type=""` | Click a named UI element — resolution-independent. |
| `get_element_text` | `window_title`, `element_name` (required), `control_type=""` | Read text/value of a named UI element. |

## remote_exec

Run commands on the REMOTE machine. Processes are asynchronous: `run` returns
a process_id immediately; poll with `get_output`.

| Action | Params | Description |
|--------|--------|-------------|
| `run` | `command` (required), `args=None`, `cwd=None`, `timeout=0`, `shell=false` | Start a process; returns `{process_id, pid, status}`. `shell=true` runs via the system shell (pipes, redirects, builtins). `timeout>0` auto-kills after N seconds. |
| `get_output` | `process_id` (required), `wait=false`, `timeout=30` | Accumulated stdout/stderr, running flag, exit code. `wait=true` blocks until exit or timeout. |
| `send_input` | `process_id` (required), `input_text` (required) | Write a line to stdin (newline appended). |
| `kill` | `process_id` (required) | Terminate a running process. |
| `list` | — | All tracked processes with status. |

Processes persist until killed or server shutdown — kill them when done.

## remote_files

Read and write files on the REMOTE machine. Binary content is base64-encoded.

| Action | Params | Description |
|--------|--------|-------------|
| `read` | `path` (required), `offset=0`, `limit=0` | `{path, size, offset, bytes_read, content_base64}`. `limit=0` reads whole file; use offset/limit to chunk large files. |
| `write` | `path` (required), `content_base64` (required), `make_dirs=true` | Write decoded bytes to path; creates parent dirs when `make_dirs`. |
| `list` | `path="."`, `pattern="*"`, `recursive=false` | Glob listing with `{path, is_dir, size, modified}`. Capped at 500 entries. |
| `delete` | `path` (required) | Delete a file or EMPTY directory. |
| `move` | `src` (required), `dst` (required) | Move/rename; creates destination parent dirs. |
| `info` | `path` (required) | `{exists, is_dir, size, modified, created}`. |
