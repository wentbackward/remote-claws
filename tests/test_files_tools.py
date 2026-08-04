"""Test file action handlers against real files in tmp_path."""

import base64
import json
from types import SimpleNamespace

import pytest

from remote_claws.dispatch import run_action
from remote_claws.files.tools import HANDLERS


class _AllowAll:
    def is_action_allowed(self, group, action):
        return True


async def _call(action: str, **params):
    full = {
        "path": "",
        "content_base64": "",
        "make_dirs": True,
        "offset": 0,
        "limit": 0,
        "pattern": "*",
        "recursive": False,
        "src": "",
        "dst": "",
    }
    full.update(params)
    # files handlers ignore app; SimpleNamespace documents that explicitly
    return await run_action(
        group="files", handlers=HANDLERS, action=action, app=SimpleNamespace(), params=full, permissions=_AllowAll()
    )


@pytest.mark.asyncio
async def test_write_then_read_roundtrip(tmp_path):
    target = str(tmp_path / "sub" / "hello.txt")
    payload = base64.b64encode(b"hello world").decode()

    write_result = json.loads(await _call("write", path=target, content_base64=payload))
    assert write_result["status"] == "written"
    assert write_result["bytes"] == 11

    read_result = json.loads(await _call("read", path=target))
    assert base64.b64decode(read_result["content_base64"]) == b"hello world"
    assert read_result["size"] == 11


@pytest.mark.asyncio
async def test_read_with_offset_and_limit(tmp_path):
    target = tmp_path / "data.bin"
    target.write_bytes(b"0123456789")
    result = json.loads(await _call("read", path=str(target), offset=2, limit=4))
    assert base64.b64decode(result["content_base64"]) == b"2345"
    assert result["bytes_read"] == 4


@pytest.mark.asyncio
async def test_read_missing_file(tmp_path):
    result = json.loads(await _call("read", path=str(tmp_path / "nope.txt")))
    assert "File not found" in result["error"]


@pytest.mark.asyncio
async def test_list_with_pattern(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.log").write_text("b")
    result = json.loads(await _call("list", path=str(tmp_path), pattern="*.txt"))
    assert [r["path"].endswith("a.txt") for r in result] == [True]


@pytest.mark.asyncio
async def test_move_and_info_and_delete(tmp_path):
    src = tmp_path / "old.txt"
    src.write_text("x")
    dst = tmp_path / "newdir" / "new.txt"

    move_result = json.loads(await _call("move", src=str(src), dst=str(dst)))
    assert move_result["status"] == "moved"
    assert dst.exists() and not src.exists()

    info = json.loads(await _call("info", path=str(dst)))
    assert info["exists"] is True and info["is_dir"] is False

    delete = json.loads(await _call("delete", path=str(dst)))
    assert delete["status"] == "deleted"
    assert not dst.exists()


@pytest.mark.asyncio
async def test_write_requires_content(tmp_path):
    result = json.loads(await _call("write", path=str(tmp_path / "x.txt")))
    assert "requires params: content_base64" in result["error"]
