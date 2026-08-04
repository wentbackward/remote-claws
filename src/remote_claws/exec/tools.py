from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from remote_claws.dispatch import Handler, run_action
from remote_claws.permissions import PermissionChecker

# Strong references to fire-and-forget background tasks (stream readers,
# auto-kill timers). asyncio only weak-references tasks, so an unreferenced
# task can be garbage-collected mid-run — this set keeps them alive until
# they complete.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def h_run(
    app: Any,
    command: str,
    args: list[str] | None = None,
    cwd: str | None = None,
    timeout: int = 0,
    shell: bool = False,
) -> str:
    process_id = uuid.uuid4().hex[:8]
    stdout_buf: list[str] = []
    stderr_buf: list[str] = []

    if shell:
        proc = await asyncio.create_subprocess_shell(
            command if not args else f"{command} {' '.join(args)}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    else:
        cmd_list = [command] + (args or [])
        proc = await asyncio.create_subprocess_exec(
            *cmd_list,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

    app.processes[process_id] = {
        "process": proc,
        "command": command,
        "args": args or [],
        "stdout": stdout_buf,
        "stderr": stderr_buf,
        "timeout": timeout,
    }

    async def _read_stream(stream, buf):
        while True:
            line = await stream.readline()
            if not line:
                break
            buf.append(line.decode(errors="replace"))

    _spawn(_read_stream(proc.stdout, stdout_buf))
    _spawn(_read_stream(proc.stderr, stderr_buf))

    if timeout > 0:

        async def _auto_kill():
            await asyncio.sleep(timeout)
            if proc.returncode is None:
                proc.kill()

        _spawn(_auto_kill())

    return json.dumps({"process_id": process_id, "pid": proc.pid, "status": "running"})


async def h_get_output(app: Any, process_id: str, wait: bool = False, timeout: int = 30) -> str:
    proc_info = app.processes.get(process_id)
    if not proc_info:
        return json.dumps({"error": f"No process found with id: {process_id}"})

    proc = proc_info["process"]

    if wait and proc.returncode is None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=timeout)

    # Small delay to let readers catch up
    await asyncio.sleep(0.1)

    return json.dumps(
        {
            "process_id": process_id,
            "running": proc.returncode is None,
            "exit_code": proc.returncode,
            "stdout": "".join(proc_info["stdout"]),
            "stderr": "".join(proc_info["stderr"]),
        }
    )


async def h_send_input(app: Any, process_id: str, input_text: str) -> str:
    proc_info = app.processes.get(process_id)
    if not proc_info:
        return json.dumps({"error": f"No process found with id: {process_id}"})

    proc = proc_info["process"]
    if proc.returncode is not None:
        return json.dumps({"error": "Process has already exited"})

    proc.stdin.write((input_text + "\n").encode())
    await proc.stdin.drain()
    return json.dumps({"status": "input sent", "process_id": process_id})


async def h_kill(app: Any, process_id: str) -> str:
    proc_info = app.processes.get(process_id)
    if not proc_info:
        return json.dumps({"error": f"No process found with id: {process_id}"})

    proc = proc_info["process"]
    if proc.returncode is not None:
        return json.dumps({"status": "already exited", "exit_code": proc.returncode})

    proc.kill()
    await proc.wait()
    return json.dumps({"status": "killed", "process_id": process_id, "exit_code": proc.returncode})


async def h_list(app: Any) -> str:
    result = []
    for pid, info in app.processes.items():
        proc = info["process"]
        result.append(
            {
                "process_id": pid,
                "command": info["command"],
                "args": info["args"],
                "running": proc.returncode is None,
                "exit_code": proc.returncode,
                "pid": proc.pid,
            }
        )
    return json.dumps(result, indent=2)


HANDLERS: dict[str, Handler] = {
    "run": h_run,
    "get_output": h_get_output,
    "send_input": h_send_input,
    "kill": h_kill,
    "list": h_list,
}


def register(mcp: FastMCP, permissions: PermissionChecker) -> None:
    """Register the single remote_exec tool when the exec group is active."""

    @mcp.tool()
    async def remote_exec(
        action: str,
        command: str = "",
        args: list[str] | None = None,
        cwd: str | None = None,
        timeout: int = 0,
        shell: bool = False,
        process_id: str = "",
        wait: bool = False,
        input_text: str = "",
        ctx: Context = None,
    ) -> str:
        """Run commands on the REMOTE machine. Processes are asynchronous: run returns
        a process_id immediately; poll with get_output.

        Actions (params not listed for an action are ignored):

          run command=<cmd> [args=["..."]] [cwd=<dir>] [timeout=0] [shell=false]
              Start a process; returns {process_id, pid, status}. shell=true runs via the
              system shell (pipes, redirects, builtins). timeout>0 auto-kills after N sec.
          get_output process_id=<id> [wait=false] [timeout=30]
              Accumulated stdout/stderr, running flag, exit code. wait=true blocks until
              the process exits or timeout elapses.
          send_input process_id=<id> input_text=<line>
              Write a line to stdin (newline appended automatically).
          kill process_id=<id>
              Terminate a running process.
          list
              All tracked processes with status.

        Processes persist until killed or server shutdown — kill them when done.
        """
        app = ctx.request_context.lifespan_context
        return await run_action(
            group="exec",
            handlers=HANDLERS,
            action=action,
            app=app,
            params={
                "command": command,
                "args": args,
                "cwd": cwd,
                "timeout": timeout,
                "shell": shell,
                "process_id": process_id,
                "wait": wait,
                "input_text": input_text,
            },
            permissions=permissions,
        )
