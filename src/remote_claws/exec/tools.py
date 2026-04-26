from __future__ import annotations

import asyncio
import json
import uuid

from mcp.server.fastmcp import FastMCP, Context

from remote_claws.permissions import PermissionChecker


def _get_ctx(ctx: Context):
    return ctx.request_context.lifespan_context


def register(mcp: FastMCP, permissions: PermissionChecker) -> None:

    def expose(fn):
        if permissions.is_allowed(fn.__name__):
            mcp.tool()(fn)
        return fn

    @expose
    async def exec_run(
        command: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        timeout: int = 0,
        shell: bool = False,
        ctx: Context = None,
    ) -> str:
        """
        Start a command asynchronously. Returns a process_id to track it.
        Use exec_get_output to retrieve stdout/stderr.
        Set shell=True to run via the system shell (supports pipes, redirects, etc).
        timeout=0 means no timeout (run until completion or killed).
        """
        app = _get_ctx(ctx)
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

        # Start background readers
        async def _read_stream(stream, buf):
            while True:
                line = await stream.readline()
                if not line:
                    break
                buf.append(line.decode(errors="replace"))

        asyncio.create_task(_read_stream(proc.stdout, stdout_buf))
        asyncio.create_task(_read_stream(proc.stderr, stderr_buf))

        # Auto-kill after timeout if set
        if timeout > 0:
            async def _auto_kill():
                await asyncio.sleep(timeout)
                if proc.returncode is None:
                    proc.kill()

            asyncio.create_task(_auto_kill())

        return json.dumps({
            "process_id": process_id,
            "pid": proc.pid,
            "status": "running",
        })

    @expose
    async def exec_get_output(
        process_id: str,
        wait: bool = False,
        timeout: int = 30,
        ctx: Context = None,
    ) -> str:
        """
        Get stdout/stderr from a running process.
        wait=True blocks until the process completes (up to timeout seconds).
        Returns accumulated output so far.
        """
        app = _get_ctx(ctx)
        proc_info = app.processes.get(process_id)
        if not proc_info:
            return json.dumps({"error": f"No process found with id: {process_id}"})

        proc = proc_info["process"]

        if wait and proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass

        # Small delay to let readers catch up
        await asyncio.sleep(0.1)

        return json.dumps({
            "process_id": process_id,
            "running": proc.returncode is None,
            "exit_code": proc.returncode,
            "stdout": "".join(proc_info["stdout"]),
            "stderr": "".join(proc_info["stderr"]),
        })

    @expose
    async def exec_send_input(process_id: str, input_text: str, ctx: Context = None) -> str:
        """Send input (stdin) to a running process. Appends a newline automatically."""
        app = _get_ctx(ctx)
        proc_info = app.processes.get(process_id)
        if not proc_info:
            return json.dumps({"error": f"No process found with id: {process_id}"})

        proc = proc_info["process"]
        if proc.returncode is not None:
            return json.dumps({"error": "Process has already exited"})

        proc.stdin.write((input_text + "\n").encode())
        await proc.stdin.drain()
        return json.dumps({"status": "input sent", "process_id": process_id})

    @expose
    async def exec_kill(process_id: str, ctx: Context = None) -> str:
        """Kill a running process by its process_id."""
        app = _get_ctx(ctx)
        proc_info = app.processes.get(process_id)
        if not proc_info:
            return json.dumps({"error": f"No process found with id: {process_id}"})

        proc = proc_info["process"]
        if proc.returncode is not None:
            return json.dumps({"status": "already exited", "exit_code": proc.returncode})

        proc.kill()
        await proc.wait()
        return json.dumps({"status": "killed", "process_id": process_id, "exit_code": proc.returncode})

    @expose
    async def exec_list(ctx: Context = None) -> str:
        """List all tracked processes with their status."""
        app = _get_ctx(ctx)
        result = []
        for pid, info in app.processes.items():
            proc = info["process"]
            result.append({
                "process_id": pid,
                "command": info["command"],
                "args": info["args"],
                "running": proc.returncode is None,
                "exit_code": proc.returncode,
                "pid": proc.pid,
            })
        return json.dumps(result, indent=2)
