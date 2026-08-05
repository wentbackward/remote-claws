"""Test desktop screenshot handler: inline image vs save-to-disk path response.

pyautogui is faked via sys.modules so these tests need no display and run
anywhere (CI included).
"""

import io
import json
import sys
import types
from types import SimpleNamespace

import pytest
from PIL import Image as PILImage

from remote_claws.config import AppConfig
from remote_claws.dispatch import run_action
from remote_claws.desktop import tools as desktop_tools


class _AllowAll:
    def is_action_allowed(self, group, action):
        return True


class _FakePyautogui(types.ModuleType):
    """Minimal pyautogui stand-in: screenshot() returns a small PIL image."""

    def __init__(self):
        super().__init__("pyautogui")
        self.regions_seen: list = []
        self.FAILSAFE = True

    def screenshot(self, region=None):
        self.regions_seen.append(region)
        img = PILImage.new("RGB", (64, 48), color=(200, 30, 30))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return PILImage.open(buf)


@pytest.fixture
def fake_pyautogui(monkeypatch):
    fake = _FakePyautogui()
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    return fake


@pytest.fixture
def app(tmp_path):
    return SimpleNamespace(
        config=AppConfig(
            permissions_file=str(tmp_path / "p.json"),
            auth_file=str(tmp_path / "a.json"),
        )
    )


@pytest.fixture(autouse=True)
def _clean_screenshot_state(monkeypatch, tmp_path):
    """Isolate module-level screenshot state and redirect temp dir."""
    monkeypatch.setattr(desktop_tools, "_LAST_SCREENSHOT", None)
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))


async def _screenshot(app, **params):
    full = {"region": None, "save_to_disk": False}
    full.update(params)
    return await run_action(
        group="desktop",
        handlers=desktop_tools.HANDLERS,
        action="screenshot",
        app=app,
        params=full,
        permissions=_AllowAll(),
    )


@pytest.mark.asyncio
async def test_inline_returns_image_by_default(app, fake_pyautogui):
    from mcp.server.fastmcp import Image

    result = await _screenshot(app)
    assert isinstance(result, Image)
    assert result.data[:3] == b"\xff\xd8\xff"  # JPEG magic


@pytest.mark.asyncio
async def test_save_to_disk_returns_json_path(app, fake_pyautogui, tmp_path):
    result = await _screenshot(app, save_to_disk=True)
    assert isinstance(result, str)
    data = json.loads(result)

    path = tmp_path / data["path"].split("\\")[-1].split("/")[-1]
    assert data["path"].startswith(str(tmp_path))
    assert path.exists()
    assert data["size_bytes"] == path.stat().st_size
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic


@pytest.mark.asyncio
async def test_subsequent_save_deletes_previous(app, fake_pyautogui):
    from pathlib import Path

    first = json.loads(await _screenshot(app, save_to_disk=True))
    first_path = Path(first["path"])
    assert first_path.exists()

    second = json.loads(await _screenshot(app, save_to_disk=True))
    assert not first_path.exists()  # cleaned up
    assert Path(second["path"]).exists()


@pytest.mark.asyncio
async def test_cleanup_tolerates_missing_previous(app, fake_pyautogui):
    from pathlib import Path

    first = json.loads(await _screenshot(app, save_to_disk=True))
    Path(first["path"]).unlink()  # operator/agent deleted it out of band
    second = json.loads(await _screenshot(app, save_to_disk=True))
    assert Path(second["path"]).exists()


@pytest.mark.asyncio
async def test_region_passed_through_with_disk_save(app, fake_pyautogui):
    result = json.loads(await _screenshot(app, region=[0, 0, 32, 32], save_to_disk=True))
    assert fake_pyautogui.regions_seen == [(0, 0, 32, 32)]
    assert result["size_bytes"] > 0
