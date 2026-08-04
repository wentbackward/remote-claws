"""Test exec action handlers with real subprocesses."""

import json
import sys
from types import SimpleNamespace

import pytest

from remote_claws.dispatch import run_action
from remote_claws.exec.tools import HANDLERS


class _AllowAll:
    def is_action_allowed(self, group, action):
        return True


@pytest.fixture
def app():
    return SimpleNamespace(processes={})


async def _call(app, action: str, **params):
    full = {
        "command": "",
        "args": None,
        "cwd": None,
        "timeout": 0,
        "shell": False,
        "process_id": "",
        "wait": False,
        "input_text": "",
    }
    full.update(params)
    return await run_action(
        group="exec", handlers=HANDLERS, action=action, app=app, params=full, permissions=_AllowAll()
    )


@pytest.mark.asyncio
async def test_run_and_get_output(app):
    started = json.loads(
        await _call(
            app,
            "run",
            command=sys.executable,
            args=["-c", "print('hello'); import sys; print('oops', file=sys.stderr)"],
        )
    )
    proc_id = started["process_id"]
    assert started["status"] == "running"

    out = json.loads(await _call(app, "get_output", process_id=proc_id, wait=True, timeout=15))
    assert out["running"] is False
    assert out["exit_code"] == 0
    assert "hello" in out["stdout"]
    assert "oops" in out["stderr"]


@pytest.mark.asyncio
async def test_list_shows_tracked_process(app):
    started = json.loads(await _call(app, "run", command=sys.executable, args=["-c", "pass"]))
    listed = json.loads(await _call(app, "list"))
    assert any(p["process_id"] == started["process_id"] for p in listed)
    out = json.loads(await _call(app, "get_output", process_id=started["process_id"], wait=True, timeout=15))
    assert out["exit_code"] == 0


@pytest.mark.asyncio
async def test_send_input_roundtrip(app):
    started = json.loads(
        await _call(app, "run", command=sys.executable, args=["-c", "line = input(); print(f'got:{line}')"])
    )
    proc_id = started["process_id"]
    sent = json.loads(await _call(app, "send_input", process_id=proc_id, input_text="ping"))
    assert sent["status"] == "input sent"
    out = json.loads(await _call(app, "get_output", process_id=proc_id, wait=True, timeout=15))
    assert "got:ping" in out["stdout"]


@pytest.mark.asyncio
async def test_kill_running_process(app):
    started = json.loads(await _call(app, "run", command=sys.executable, args=["-c", "import time; time.sleep(60)"]))
    proc_id = started["process_id"]
    killed = json.loads(await _call(app, "kill", process_id=proc_id))
    assert killed["status"] == "killed"
    assert killed["exit_code"] is not None


@pytest.mark.asyncio
async def test_unknown_process_id(app):
    result = json.loads(await _call(app, "get_output", process_id="deadbeef"))
    assert "No process found" in result["error"]


@pytest.mark.asyncio
async def test_shell_mode(app):
    started = json.loads(await _call(app, "run", command="echo shelled", shell=True))
    out = json.loads(await _call(app, "get_output", process_id=started["process_id"], wait=True, timeout=15))
    assert "shelled" in out["stdout"]
