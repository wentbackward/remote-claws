# TOOLS.md — PyWinMCP Tool Reference

Complete reference for all 39 tools exposed by PyWinMCP. Tools are organized into four permission groups: `browser`, `desktop`, `exec`, and `files`. Each tool can be individually allowed or denied in `permissions.json`.

---

## Browser Tools

Automate a Chromium browser via Playwright. The browser launches lazily on first use and persists across calls. All selectors are CSS selectors.

### browser_navigate

Navigate to a URL and wait for the page to load.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | *required* | The URL to navigate to |

**Returns**: Page title, final URL, and HTTP status code.

### browser_click

Click an element on the page.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `selector` | string | *required* | CSS selector of the element |
| `button` | string | `"left"` | Mouse button: `"left"`, `"right"`, `"middle"` |
| `click_count` | int | `1` | Number of clicks (2 for double-click) |

### browser_fill

Clear an input/textarea and set its value. Triggers change events.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `selector` | string | *required* | CSS selector of the input |
| `value` | string | *required* | The value to set |

### browser_type

Type text keystroke-by-keystroke into an element. Does **not** clear existing content — appends to it.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `selector` | string | *required* | CSS selector of the element |
| `text` | string | *required* | Text to type |
| `delay` | int | `0` | Delay between keystrokes in milliseconds |

### browser_press_key

Press a keyboard key or key combination.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `key` | string | *required* | Key name, e.g. `"Enter"`, `"Escape"`, `"Tab"`, `"Control+a"`, `"Meta+c"` |

### browser_get_text

Extract the visible text content of an element.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `selector` | string | `"body"` | CSS selector of the element |

**Returns**: The `innerText` of the element.

### browser_get_html

Get the HTML markup of an element.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `selector` | string | `"html"` | CSS selector |
| `outer` | bool | `true` | `true` for outerHTML, `false` for innerHTML |

### browser_eval_js

Evaluate a JavaScript expression in the page context.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `expression` | string | *required* | JavaScript to evaluate |

**Returns**: JSON-serialized result of the expression.

### browser_screenshot

Take a screenshot of the page or a specific element.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `selector` | string | `""` | CSS selector to screenshot (empty = full page viewport) |
| `full_page` | bool | `false` | Capture the full scrollable page (ignored if selector is set) |
| `save_to_disk` | bool | `false` | Also save the image to the configured screenshot directory |

**Returns**: JPEG image, downscaled to max 1280x960.

### browser_wait_for

Wait for an element to reach a specified state.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `selector` | string | *required* | CSS selector |
| `state` | string | `"visible"` | Target state: `"visible"`, `"hidden"`, `"attached"`, `"detached"` |
| `timeout` | int | `10000` | Timeout in milliseconds |

### browser_select_option

Select an option from a `<select>` dropdown.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `selector` | string | *required* | CSS selector of the select element |
| `value` | string | *required* | Option value or visible label text |

### browser_go_back

Navigate back in browser history. Returns new page title and URL.

### browser_go_forward

Navigate forward in browser history. Returns new page title and URL.

### browser_tabs_list

List all open tabs. Returns JSON array with `index`, `url`, `title`, and `active` flag for each tab.

### browser_tab_new

Open a new browser tab.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | `"about:blank"` | URL to open in the new tab |

### browser_tab_close

Close a browser tab.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `index` | int | `-1` | Tab index to close (`-1` = current active tab) |

---

## Desktop Tools

Control the Windows desktop via mouse, keyboard, and UI automation. Screenshots use absolute screen coordinates. pyautogui failsafe is enabled — mouse to (0,0) aborts.

### desktop_screenshot

Capture the screen or a region.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `region` | list[int] | `null` | Optional `[x, y, width, height]` to capture a region |
| `save_to_disk` | bool | `false` | Also save the image to disk |

**Returns**: JPEG image, downscaled to max 1280x960.

### desktop_mouse_click

Click at absolute screen coordinates.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `x` | int | *required* | X coordinate |
| `y` | int | *required* | Y coordinate |
| `button` | string | `"left"` | `"left"`, `"right"`, `"middle"` |
| `clicks` | int | `1` | Number of clicks |

### desktop_mouse_move

Move the mouse cursor.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `x` | int | *required* | Target X coordinate |
| `y` | int | *required* | Target Y coordinate |
| `duration` | float | `0.2` | Movement duration in seconds |

### desktop_mouse_drag

Drag from one position to another.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `start_x` | int | *required* | Starting X |
| `start_y` | int | *required* | Starting Y |
| `end_x` | int | *required* | Ending X |
| `end_y` | int | *required* | Ending Y |
| `duration` | float | `0.5` | Drag duration in seconds |

### desktop_type_text

Type text at the current cursor/focus position using simulated keystrokes.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `text` | string | *required* | Text to type |
| `interval` | float | `0.02` | Delay between keystrokes in seconds |

**Note**: Uses `pyautogui.typewrite` which only supports ASCII characters. For Unicode, use `desktop_press_key` or clipboard-based approaches.

### desktop_press_key

Press a key or hotkey combination.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `keys` | string | *required* | Key(s) separated by `+`, e.g. `"enter"`, `"ctrl+c"`, `"alt+tab"`, `"win"` |

### desktop_scroll

Scroll at a screen position.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `x` | int | *required* | X coordinate to scroll at |
| `y` | int | *required* | Y coordinate to scroll at |
| `clicks` | int | `3` | Scroll amount |
| `direction` | string | `"down"` | `"up"` or `"down"` |

### desktop_find_window

Find windows by title or class name. Uses pywinauto UIA backend.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | string | `""` | Substring to match in window title (case-insensitive) |
| `class_name` | string | `""` | Substring to match in window class name |

**Returns**: JSON array of matching windows with `title`, `class_name`, and `rectangle` (left/top/right/bottom).

### desktop_focus_window

Bring a window to the foreground.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | string | *required* | Substring to match in window title |

### desktop_list_elements

Enumerate UI controls within a window. Useful for discovering button names, text fields, etc.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `window_title` | string | *required* | Window title substring |
| `control_type` | string | `""` | Filter by type: `"Button"`, `"Edit"`, `"Text"`, `"CheckBox"`, etc. |
| `max_depth` | int | `4` | How deep to traverse the UI tree |

**Returns**: JSON array (max 200 entries) with `name`, `control_type`, and `automation_id` for each element.

### desktop_click_element

Click a UI element by its name within a window. More reliable than coordinate clicking.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `window_title` | string | *required* | Window title substring |
| `element_name` | string | *required* | Exact name of the UI element |
| `control_type` | string | `""` | Optional filter to disambiguate (e.g. `"Button"`) |

### desktop_get_element_text

Read the text or value of a UI element by name.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `window_title` | string | *required* | Window title substring |
| `element_name` | string | *required* | Exact name of the UI element |
| `control_type` | string | `""` | Optional filter |

---

## Exec Tools

Run commands asynchronously on the host machine. Processes are tracked by a short ID and persist until killed or the server shuts down.

### exec_run

Start a command. Returns immediately with a process ID.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `command` | string | *required* | The command or executable to run |
| `args` | list[string] | `null` | Arguments to pass |
| `cwd` | string | `null` | Working directory |
| `timeout` | int | `0` | Auto-kill after this many seconds (0 = no timeout) |
| `shell` | bool | `false` | Run via system shell (supports pipes, redirects, builtins) |

**Returns**: JSON with `process_id` (8-char hex), `pid`, and `status`.

### exec_get_output

Retrieve stdout and stderr from a tracked process.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `process_id` | string | *required* | The process ID from exec_run |
| `wait` | bool | `false` | Block until the process exits |
| `timeout` | int | `30` | Max seconds to wait (only when wait=true) |

**Returns**: JSON with `stdout`, `stderr`, `running` (bool), and `exit_code` (null if still running).

### exec_send_input

Send a line of text to a running process's stdin. A newline is appended automatically.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `process_id` | string | *required* | The process ID |
| `input_text` | string | *required* | Text to send |

### exec_kill

Terminate a running process.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `process_id` | string | *required* | The process ID |

### exec_list

List all tracked processes with their command, status, and PID. Takes no parameters.

---

## File Tools

Read and write files on the host machine. All file content is transferred as base64 to handle binary safely.

### file_write

Write content to a file. Creates parent directories by default.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | string | *required* | Destination file path |
| `content_base64` | string | *required* | File content, base64-encoded |
| `make_dirs` | bool | `true` | Create parent directories if they don't exist |

**Returns**: JSON with `path` (resolved) and `bytes` written.

### file_read

Read a file and return its content as base64. Supports chunked reading for large files.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | string | *required* | File path to read |
| `offset` | int | `0` | Byte offset to start reading from |
| `limit` | int | `0` | Max bytes to read (0 = entire file) |

**Returns**: JSON with `content_base64`, `size` (total file size), `offset`, and `bytes_read`.

### file_list

List files and directories matching a pattern.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | string | `"."` | Directory to list |
| `pattern` | string | `"*"` | Glob pattern (e.g. `"*.txt"`, `"**/*.py"`) |
| `recursive` | bool | `false` | Search subdirectories |

**Returns**: JSON array (max 500 entries) with `path`, `is_dir`, `size`, and `modified` timestamp.

### file_delete

Delete a file or empty directory.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | string | *required* | Path to delete |

### file_move

Move or rename a file or directory. Creates destination parent directories.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `src` | string | *required* | Source path |
| `dst` | string | *required* | Destination path |

### file_info

Get metadata about a file or directory.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | string | *required* | Path to inspect |

**Returns**: JSON with `exists`, `is_dir`, `size`, `modified`, and `created` timestamps.
