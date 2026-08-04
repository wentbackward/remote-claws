from __future__ import annotations

import io
import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP, Image

from remote_claws.dispatch import Handler, run_action
from remote_claws.permissions import PermissionChecker
from remote_claws.screenshot import downscale_and_encode, make_save_path


def h_screenshot(app: Any, region: list[int] | None = None, save_to_disk: bool = False) -> Image:
    import pyautogui

    pil_img = pyautogui.screenshot(region=tuple(region)) if region and len(region) == 4 else pyautogui.screenshot()
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


def h_mouse_click(app: Any, x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    import pyautogui

    pyautogui.click(x=x, y=y, button=button, clicks=clicks)
    return f"Clicked at ({x}, {y}) button={button} clicks={clicks}"


def h_mouse_move(app: Any, x: int, y: int, duration: float = 0.2) -> str:
    import pyautogui

    pyautogui.moveTo(x=x, y=y, duration=duration)
    return f"Moved mouse to ({x}, {y})"


def h_mouse_drag(app: Any, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5) -> str:
    import pyautogui

    pyautogui.moveTo(start_x, start_y)
    pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration)
    return f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})"


def h_type_text(app: Any, text: str, interval: float = 0.02) -> str:
    import pyautogui

    pyautogui.typewrite(text, interval=interval)
    return f"Typed {len(text)} characters"


def h_press_key(app: Any, keys: str) -> str:
    import pyautogui

    key_list = [k.strip() for k in keys.split("+")]
    if len(key_list) == 1:
        pyautogui.press(key_list[0])
    else:
        pyautogui.hotkey(*key_list)
    return f"Pressed: {keys}"


def h_scroll(app: Any, x: int, y: int, clicks: int = 3, direction: str = "down") -> str:
    import pyautogui

    amount = clicks if direction == "up" else -clicks
    pyautogui.scroll(amount, x=x, y=y)
    return f"Scrolled {direction} {clicks} clicks at ({x}, {y})"


def _find_window(title_substr: str):
    """Return the first UIA window whose title contains the substring, or None."""
    from pywinauto import Desktop

    desktop = Desktop(backend="uia")
    for win in desktop.windows():
        if title_substr.lower() in win.window_text().lower():
            return win
    return None


def h_find_window(app: Any, title: str = "", class_name: str = "") -> str:
    from pywinauto import Desktop

    desktop = Desktop(backend="uia")
    results = []
    for win in desktop.windows():
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


def h_focus_window(app: Any, title: str) -> str:
    win = _find_window(title)
    if win is None:
        return f"No window found matching: {title}"
    win.set_focus()
    return f"Focused window: {win.window_text()}"


def h_list_elements(app: Any, window_title: str, control_type: str = "", max_depth: int = 4) -> str:
    target = _find_window(window_title)
    if target is None:
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


def h_click_element(app: Any, window_title: str, element_name: str, control_type: str = "") -> str:
    target = _find_window(window_title)
    if target is None:
        return f"No window found matching: {window_title}"
    target.set_focus()

    for child in target.descendants():
        if child.element_info.name == element_name:
            if control_type and child.element_info.control_type != control_type:
                continue
            child.click_input()
            return f"Clicked element: {element_name}"
    return f"Element not found: {element_name}"


def h_get_element_text(app: Any, window_title: str, element_name: str, control_type: str = "") -> str:
    target = _find_window(window_title)
    if target is None:
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


HANDLERS: dict[str, Handler] = {
    "screenshot": h_screenshot,
    "mouse_click": h_mouse_click,
    "mouse_move": h_mouse_move,
    "mouse_drag": h_mouse_drag,
    "type_text": h_type_text,
    "press_key": h_press_key,
    "scroll": h_scroll,
    "find_window": h_find_window,
    "focus_window": h_focus_window,
    "list_elements": h_list_elements,
    "click_element": h_click_element,
    "get_element_text": h_get_element_text,
}


def register(mcp: FastMCP, permissions: PermissionChecker) -> None:
    """Register the single remote_desktop tool when the desktop group is active."""

    import pyautogui

    # Keep failsafe enabled — moving mouse to (0,0) aborts
    pyautogui.FAILSAFE = True

    @mcp.tool()
    async def remote_desktop(
        action: str,
        region: list[int] | None = None,
        save_to_disk: bool = False,
        x: int | None = None,
        y: int | None = None,
        start_x: int | None = None,
        start_y: int | None = None,
        end_x: int | None = None,
        end_y: int | None = None,
        button: str = "left",
        clicks: int = 1,
        duration: float = 0.2,
        text: str = "",
        interval: float = 0.02,
        keys: str = "",
        direction: str = "down",
        title: str = "",
        class_name: str = "",
        window_title: str = "",
        element_name: str = "",
        control_type: str = "",
        max_depth: int = 4,
        ctx: Context = None,
    ) -> Any:
        """Control the REMOTE machine's desktop: mouse, keyboard, screenshots, and
        Windows UI automation. Coordinates are absolute screen pixels. Returns text for
        most actions, a JPEG image for screenshot. Moving the mouse to (0,0) aborts
        (pyautogui failsafe).

        Workflow: screenshot first, act, re-screenshot to verify. Prefer element-name
        actions over coordinates when possible — coordinates break when windows move.

        Actions (params not listed for an action are ignored):

        Capture
          screenshot [region=[x,y,w,h]] [save_to_disk=false]
              JPEG of the full screen or a region.

        Mouse
          mouse_click x=<px> y=<px> [button=left] [clicks=1]      clicks=2 = double-click
          mouse_move x=<px> y=<px> [duration=0.2]
          mouse_drag start_x=<px> start_y=<px> end_x=<px> end_y=<px> [duration=0.5]
          scroll x=<px> y=<px> [clicks=3] [direction=down]        direction: up | down

        Keyboard (acts at current focus)
          type_text text=<text> [interval=0.02]   ASCII only.
          press_key keys=<combo>                  "enter", "ctrl+c", "alt+tab", "win"

        Windows UI automation (targets controls by NAME — resolution-independent)
          find_window [title=<substr>] [class_name=<substr>]
              List visible windows with title, class, rectangle.
          focus_window title=<substr>             Bring matching window to foreground.
          list_elements window_title=<substr> [control_type=<type>] [max_depth=4]
              Enumerate controls (Button, Edit, ...) with name/automation_id. Cap 200.
          click_element window_title=<substr> element_name=<name> [control_type=<type>]
          get_element_text window_title=<substr> element_name=<name> [control_type=<type>]

        Unknown actions return the valid action list. Denied actions return a
        permission error — do not retry them.
        """
        app = ctx.request_context.lifespan_context
        return await run_action(
            group="desktop",
            handlers=HANDLERS,
            action=action,
            app=app,
            params={
                "region": region,
                "save_to_disk": save_to_disk,
                "x": x,
                "y": y,
                "start_x": start_x,
                "start_y": start_y,
                "end_x": end_x,
                "end_y": end_y,
                "button": button,
                "clicks": clicks,
                "duration": duration,
                "text": text,
                "interval": interval,
                "keys": keys,
                "direction": direction,
                "title": title,
                "class_name": class_name,
                "window_title": window_title,
                "element_name": element_name,
                "control_type": control_type,
                "max_depth": max_depth,
            },
            permissions=permissions,
        )
