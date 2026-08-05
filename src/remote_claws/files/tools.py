from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from remote_claws.dispatch import Handler, run_action
from remote_claws.permissions import PermissionChecker


def h_write(app: Any, path: str, content_base64: str, make_dirs: bool = True) -> str:
    data = base64.b64decode(content_base64)
    p = Path(path)
    if make_dirs:
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return json.dumps({"status": "written", "path": str(p.resolve()), "bytes": len(data)})


def h_read(
    app: Any,
    path: str,
    offset: int = 0,
    limit: int = 0,
    as_url: bool = False,
    request_host: str = "",
) -> str:
    p = Path(path)
    if not p.exists():
        return json.dumps({"error": f"File not found: {path}"})

    file_size = p.stat().st_size

    # as_url: register a short-lived capability URL instead of returning
    # content. For large binaries — never pull those through model context.
    if as_url:
        name = app.shots.register(p)
        result: dict[str, Any] = {
            "path": str(p.resolve()),
            "size_bytes": file_size,
            "expires_in": app.shots.ttl_seconds,
        }
        if request_host:
            result["url"] = f"http://{request_host}/dl/{name}"
        return json.dumps(result)

    # Hard cap on inline (base64) reads: a big base64 payload in a tool
    # result explodes model context. Over-cap reads fail with guidance —
    # the agent recovers with as_url=true or a smaller offset/limit chunk.
    inline_bytes = min(limit, file_size - offset) if limit > 0 else file_size - offset
    inline_bytes = max(0, inline_bytes)
    cap = app.config.max_inline_bytes
    if inline_bytes > cap:
        return json.dumps(
            {
                "error": (
                    f"inline read would return {inline_bytes:,} bytes (cap {cap:,}). "
                    "Re-issue with as_url=true for a download URL, or read a "
                    "smaller chunk with offset/limit."
                ),
                "size_bytes": file_size,
                "inline_bytes": inline_bytes,
                "cap_bytes": cap,
            }
        )

    with open(p, "rb") as f:
        if offset > 0:
            f.seek(offset)
        data = f.read(limit) if limit > 0 else f.read()

    return json.dumps(
        {
            "path": str(p.resolve()),
            "size": file_size,
            "offset": offset,
            "bytes_read": len(data),
            "content_base64": base64.b64encode(data).decode(),
        }
    )


def h_list(app: Any, path: str = ".", pattern: str = "*", recursive: bool = False) -> str:
    p = Path(path)
    if not p.exists():
        return json.dumps({"error": f"Path not found: {path}"})

    entries = list(p.rglob(pattern)) if recursive else list(p.glob(pattern))

    results = []
    for entry in entries[:500]:  # cap results
        try:
            stat = entry.stat()
            results.append(
                {
                    "path": str(entry),
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size if not entry.is_dir() else None,
                    "modified": stat.st_mtime,
                }
            )
        except OSError:
            continue
    return json.dumps(results, indent=2)


def h_delete(app: Any, path: str) -> str:
    p = Path(path)
    if not p.exists():
        return json.dumps({"error": f"Not found: {path}"})

    if p.is_dir():
        p.rmdir()
    else:
        p.unlink()
    return json.dumps({"status": "deleted", "path": str(p.resolve())})


def h_move(app: Any, src: str, dst: str) -> str:
    src_p = Path(src)
    if not src_p.exists():
        return json.dumps({"error": f"Source not found: {src}"})

    dst_p = Path(dst)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src_p), str(dst_p))
    return json.dumps({"status": "moved", "src": str(src_p.resolve()), "dst": str(dst_p.resolve())})


def h_info(app: Any, path: str) -> str:
    p = Path(path)
    if not p.exists():
        return json.dumps({"exists": False, "path": path})

    stat = p.stat()
    return json.dumps(
        {
            "exists": True,
            "path": str(p.resolve()),
            "is_dir": p.is_dir(),
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "created": stat.st_ctime,
        }
    )


HANDLERS: dict[str, Handler] = {
    "write": h_write,
    "read": h_read,
    "list": h_list,
    "delete": h_delete,
    "move": h_move,
    "info": h_info,
}


def register(mcp: FastMCP, permissions: PermissionChecker) -> None:
    """Register the single remote_files tool when the files group is active."""

    @mcp.tool()
    async def remote_files(
        action: str,
        path: str = "",
        content_base64: str = "",
        make_dirs: bool = True,
        offset: int = 0,
        limit: int = 0,
        pattern: str = "*",
        recursive: bool = False,
        src: str = "",
        dst: str = "",
        as_url: bool = False,
        ctx: Context = None,
    ) -> str:
        """Read and write files on the REMOTE machine. Binary content is base64-encoded.

        Actions (params not listed for an action are ignored):

          read path=<path> [offset=0] [limit=0] [as_url=false]
              Return file content as {path, size, offset, bytes_read, content_base64}.
              limit=0 reads the whole file; use offset/limit to chunk large files.
              Inline reads are CAPPED (default 1MB): over-cap reads fail with
              "inline read would return N bytes" — re-issue with as_url=true.
              as_url=true returns {"path", "size_bytes", "url", "expires_in"}
              instead of content — use for LARGE BINARIES (images, video, PDF):
              hand the url to a tool that fetches out-of-band. Never base64 a
              big binary into your context.
          write path=<path> content_base64=<b64> [make_dirs=true]
              Write decoded bytes to path; creates parent dirs when make_dirs.
          list [path=.] [pattern=*] [recursive=false]
              Glob listing with {path, is_dir, size, modified}. Capped at 500 entries.
          delete path=<path>
              Delete a file or EMPTY directory.
          move src=<path> dst=<path>
              Move/rename; creates destination parent dirs.
          info path=<path>
              {exists, is_dir, size, modified, created}.

        Unknown actions return the valid action list. Denied actions return a
        permission error — do not retry them.
        """
        app = ctx.request_context.lifespan_context
        # Host the client used to reach us — builds download URLs for as_url
        # reads. Threaded internally; never part of the tool's public schema.
        request = getattr(ctx.request_context, "request", None)
        request_host = request.headers.get("host", "") if request is not None else ""
        return await run_action(
            group="files",
            handlers=HANDLERS,
            action=action,
            app=app,
            params={
                "path": path,
                "content_base64": content_base64,
                "make_dirs": make_dirs,
                "offset": offset,
                "limit": limit,
                "pattern": pattern,
                "recursive": recursive,
                "src": src,
                "dst": dst,
                "as_url": as_url,
                "request_host": request_host,
            },
            permissions=permissions,
        )
