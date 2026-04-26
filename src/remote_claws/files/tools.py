from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Context

from remote_claws.permissions import PermissionChecker


def register(mcp: FastMCP, permissions: PermissionChecker) -> None:

    def expose(fn):
        if permissions.is_allowed(fn.__name__):
            mcp.tool()(fn)
        return fn

    @expose
    def file_write(path: str, content_base64: str, make_dirs: bool = True, ctx: Context = None) -> str:
        """
        Write binary content to a file. Content must be base64-encoded.
        Set make_dirs=True to create parent directories automatically.
        """
        data = base64.b64decode(content_base64)
        p = Path(path)
        if make_dirs:
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return json.dumps({"status": "written", "path": str(p.resolve()), "bytes": len(data)})

    @expose
    def file_read(path: str, offset: int = 0, limit: int = 0, ctx: Context = None) -> str:
        """
        Read a file and return base64-encoded content.
        Use offset and limit (in bytes) for chunked reading of large files.
        limit=0 means read the entire file.
        """
        p = Path(path)
        if not p.exists():
            return json.dumps({"error": f"File not found: {path}"})

        file_size = p.stat().st_size
        with open(p, "rb") as f:
            if offset > 0:
                f.seek(offset)
            # Explicit if/else is clearer than ternary for read operations.
            if limit > 0:  # noqa: SIM108
                data = f.read(limit)
            else:
                data = f.read()

        return json.dumps(
            {
                "path": str(p.resolve()),
                "size": file_size,
                "offset": offset,
                "bytes_read": len(data),
                "content_base64": base64.b64encode(data).decode(),
            }
        )

    @expose
    def file_list(path: str = ".", pattern: str = "*", recursive: bool = False, ctx: Context = None) -> str:
        """
        List files in a directory. Use pattern for glob matching (e.g. '*.txt').
        Set recursive=True to search subdirectories.
        """
        p = Path(path)
        if not p.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        # Explicit if/else is clearer than ternary for glob operations.
        if recursive:  # noqa: SIM108
            entries = list(p.rglob(pattern))
        else:
            entries = list(p.glob(pattern))

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

    @expose
    def file_delete(path: str, ctx: Context = None) -> str:
        """Delete a file or empty directory."""
        p = Path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})

        if p.is_dir():
            p.rmdir()
        else:
            p.unlink()
        return json.dumps({"status": "deleted", "path": str(p.resolve())})

    @expose
    def file_move(src: str, dst: str, ctx: Context = None) -> str:
        """Move or rename a file or directory."""
        src_p = Path(src)
        if not src_p.exists():
            return json.dumps({"error": f"Source not found: {src}"})

        dst_p = Path(dst)
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_p), str(dst_p))
        return json.dumps({"status": "moved", "src": str(src_p.resolve()), "dst": str(dst_p.resolve())})

    @expose
    def file_info(path: str, ctx: Context = None) -> str:
        """Get file/directory metadata: size, modified time, exists, is_dir."""
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
