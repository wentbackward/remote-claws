"""Test file action handlers against real files in tmp_path."""

import base64
import json
from types import SimpleNamespace

import pytest

from remote_claws.config import AppConfig
from remote_claws.dispatch import run_action
from remote_claws.files.tools import HANDLERS


class _AllowAll:
    def is_action_allowed(self, group, action):
        return True


def _app(tmp_path, **config_overrides):
    return SimpleNamespace(
        config=AppConfig(
            permissions_file=str(tmp_path / "p.json"),
            auth_file=str(tmp_path / "a.json"),
            **config_overrides,
        )
    )


def _default_app():
    return SimpleNamespace(config=AppConfig())


async def _call(action: str, app=None, **params):
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
    return await run_action(
        group="files", handlers=HANDLERS, action=action, app=app or _default_app(), params=full, permissions=_AllowAll()
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


@pytest.mark.asyncio
async def test_read_as_url_returns_download_url(tmp_path):
    from types import SimpleNamespace as NS

    from remote_claws.shots import ShotRegistry

    target = tmp_path / "big.bin"
    target.write_bytes(b"x" * 100)
    registry = ShotRegistry(ttl_seconds=600)

    result = await run_action(
        group="files",
        handlers=HANDLERS,
        action="read",
        app=NS(shots=registry),
        params={"path": str(target), "as_url": True, "request_host": "lucca:3030"},
        permissions=_AllowAll(),
    )
    data = json.loads(result)
    assert data["size_bytes"] == 100
    assert data["url"].startswith("http://lucca:3030/dl/")
    assert "content_base64" not in data
    name = data["url"].rsplit("/", 1)[-1]
    assert registry.resolve(name) == target


@pytest.mark.asyncio
async def test_read_over_inline_cap_hard_errors(tmp_path):
    target = tmp_path / "big.bin"
    target.write_bytes(b"x" * 1000)
    app = _app(tmp_path, max_inline_bytes=100)

    result = json.loads(await _call("read", app=app, path=str(target)))
    assert "inline read would return 1,000 bytes (cap 100)" in result["error"]
    assert "as_url=true" in result["error"]  # recovery is named in the error
    assert result["size_bytes"] == 1000
    assert result["cap_bytes"] == 100


@pytest.mark.asyncio
async def test_read_under_cap_with_limit_still_works(tmp_path):
    target = tmp_path / "big.bin"
    target.write_bytes(b"x" * 1000)
    app = _app(tmp_path, max_inline_bytes=100)

    # A chunk that fits under the cap is served inline as normal.
    ok = json.loads(await _call("read", app=app, path=str(target), offset=0, limit=50))
    assert ok["bytes_read"] == 50
    # A chunk that still exceeds the cap errors too.
    over = json.loads(await _call("read", app=app, path=str(target), offset=0, limit=500))
    assert "inline read would return 500 bytes (cap 100)" in over["error"]
