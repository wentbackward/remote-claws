from __future__ import annotations

import io
import json

from mcp.server.fastmcp import FastMCP, Context, Image

from remote_claws.permissions import PermissionChecker
from remote_claws.screenshot import downscale_and_encode, make_save_path


def _get_ctx(ctx: Context):
    return ctx.request_context.lifespan_context


def register(mcp: FastMCP, permissions: PermissionChecker) -> None:
    """Register every desktop tool the policy permits. pyautogui is imported
    here — not at module top — so disabling the desktop group keeps it (and
    its X11/Win32 side effects) out of memory entirely."""

    import pyautogui

    # Keep failsafe enabled — moving mouse to (0,0) aborts
    pyautogui.FAILSAFE = True

    def expose(fn):
        if permissions.is_allowed(fn.__name__):
            mcp.tool()(fn)
        return fn

    @expose
    def desktop_screenshot(
        region: list[int] | None = None,
        save_to_disk: bool = False,
        ctx: Context = None,
    ) -> Image:
        """Take a screenshot of the entire desktop or a region [x, y, width, height]. Returns JPEG image."""
        app = _get_ctx(ctx)
        # Ternary would obscure the intent — explicit if/else is clearer.
        if region and len(region) == 4:  # noqa: SIM108
            pil_img = pyautogui.screenshot(region=tuple(region))
        else:
            pil_img = pyautogui.screenshot()
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        save_path = make_save_path(app.config.screenshot_dir) if save_to_disk else None
        jpeg_bytes, _saved = downscale_and_encode(
            buf.getvalue(),
            max_width=app.config.screenshot_max_width,
            max_height=app.config.screenshot_max_height,
            quality=app.config.screenshot_quality,
            save_path=save_path,
        )
        return Image(data=jpeg_bytes, format="jpeg")

    @expose
    def desktop_mouse_click(x: int, y: int, button: str = "left", clicks: int = 1, ctx: Context = None) -> str:
        """Click the mouse at screen coordinates (x, y)."""
        pyautogui.click(x=x, y=y, button=button, clicks=clicks)
        return f"Clicked at ({x}, {y}) button={button} clicks={clicks}"

    @expose
    def desktop_mouse_move(x: int, y: int, duration: float = 0.2, ctx: Context = None) -> str:
        """Move the mouse to screen coordinates (x, y)."""
        pyautogui.moveTo(x=x, y=y, duration=duration)
        return f"Moved mouse to ({x}, {y})"

    @expose
    def desktop_mouse_drag(
        start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5, ctx: Context = None
    ) -> str:
        """Drag the mouse from (start_x, start_y) to (end_x, end_y)."""
        pyautogui.moveTo(start_x, start_y)
        pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration)
        return f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})"

    @expose
    def desktop_type_text(text: str, interval: float = 0.02, ctx: Context = None) -> str:
        """Type text at the current cursor/focus position."""
        pyautogui.typewrite(text, interval=interval)
        return f"Typed {len(text)} characters"

    @expose
    def desktop_press_key(keys: str, ctx: Context = None) -> str:
        """Press a key or hotkey combo (e.g. 'enter', 'ctrl+c', 'alt+tab', 'win')."""
        key_list = [k.strip() for k in keys.split("+")]
        if len(key_list) == 1:
            pyautogui.press(key_list[0])
        else:
            pyautogui.hotkey(*key_list)
        return f"Pressed: {keys}"

    @expose
    def desktop_scroll(x: int, y: int, clicks: int = 3, direction: str = "down", ctx: Context = None) -> str:
        """Scroll at screen position (x, y). Direction: 'up' or 'down'. Clicks = scroll amount."""
        amount = clicks if direction == "up" else -clicks
        pyautogui.scroll(amount, x=x, y=y)
        return f"Scrolled {direction} {clicks} clicks at ({x}, {y})"

    @expose
    def desktop_find_window(title: str = "", class_name: str = "", ctx: Context = None) -> str:
        """Find windows by title substring or class name using pywinauto. Returns JSON list."""
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        windows = desktop.windows()
        results = []
        for win in windows:
            win_title = win.window_text()
            win_class = win.class_name()
            if title and title.lower() not in win_title.lower():
                continue
            if class_name and class_name.lower() not in win_class.lower():
                continue
            results.append(
                {
                    "title": win_title,
                    "class_name": win_class,
                    "rectangle": {
                        "left": win.rectangle().left,
                        "top": win.rectangle().top,
                        "right": win.rectangle().right,
                        "bottom": win.rectangle().bottom,
                    },
                }
            )
        return json.dumps(results, indent=2)

    @expose
    def desktop_focus_window(title: str, ctx: Context = None) -> str:
        """Bring a window to the foreground by title substring."""
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        for win in desktop.windows():
            if title.lower() in win.window_text().lower():
                win.set_focus()
                return f"Focused window: {win.window_text()}"
        return f"No window found matching: {title}"

    @expose
    def desktop_list_elements(
        window_title: str, control_type: str = "", max_depth: int = 4, ctx: Context = None
    ) -> str:
        """List UI elements in a window. Optionally filter by control_type (e.g. 'Button', 'Edit')."""
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        target = None
        for win in desktop.windows():
            if window_title.lower() in win.window_text().lower():
                target = win
                break
        if not target:
            return f"No window found matching: {window_title}"

        elements = []
        for child in target.descendants(depth=max_depth):
            ct = child.element_info.control_type
            if control_type and ct != control_type:
                continue
            elements.append(
                {
                    "name": child.element_info.name,
                    "control_type": ct,
                    "automation_id": child.element_info.automation_id,
                }
            )
        return json.dumps(elements[:200], indent=2)  # cap at 200

    @expose
    def desktop_click_element(window_title: str, element_name: str, control_type: str = "", ctx: Context = None) -> str:
        """Click a specific UI element by name within a window (pywinauto)."""
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        target = None
        for win in desktop.windows():
            if window_title.lower() in win.window_text().lower():
                target = win
                break
        if not target:
            return f"No window found matching: {window_title}"
        target.set_focus()

        for child in target.descendants():
            if child.element_info.name == element_name:
                if control_type and child.element_info.control_type != control_type:
                    continue
                child.click_input()
                return f"Clicked element: {element_name}"
        return f"Element not found: {element_name}"

    @expose
    def desktop_get_element_text(
        window_title: str, element_name: str, control_type: str = "", ctx: Context = None
    ) -> str:
        """Get text/value from a UI element by name within a window."""
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        target = None
        for win in desktop.windows():
            if window_title.lower() in win.window_text().lower():
                target = win
                break
        if not target:
            return f"No window found matching: {window_title}"

        for child in target.descendants():
            if child.element_info.name == element_name:
                if control_type and child.element_info.control_type != control_type:
                    continue
                try:
                    return child.window_text()
                except Exception:
                    return child.element_info.name
        return f"Element not found: {element_name}"
