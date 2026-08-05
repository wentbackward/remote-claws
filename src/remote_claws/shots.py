"""Temporary download URLs for large binary artifacts (screenshots).

Tool results must not carry binary content: agents with text-only models
cannot accept it, and base64 in a tool result explodes context. Instead the
server saves the artifact, issues a short-lived capability URL
(/shots/<128-bit-token>), and the agent hands the URL to a tool that
fetches it out-of-band (e.g. an image-analysis tool running gateway-side).

Security model: the URL path IS the credential (same class as a pre-signed
object-store URL). Names are 128-bit random, files live only until TTL
expiry or eviction, and names are looked up in this registry — never joined
to the filesystem from request input, so traversal is impossible. The
endpoint is exempt from bearer auth by design (fetching tools cannot attach
headers); the IP allowlist middleware still applies.
"""

from __future__ import annotations

import secrets
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

# Bound on outstanding files: oldest-expiring shots are evicted beyond this,
# so a burst of screenshots cannot fill the temp dir between TTL purges.
MAX_SHOTS = 32


@dataclass
class Shot:
    path: Path
    expires_at: float


class ShotRegistry:
    """In-memory registry of issued download URLs. Lives on the process-level
    AppContext so every MCP request sees the same registry."""

    def __init__(self, ttl_seconds: int = 600):
        self._ttl = ttl_seconds
        self._shots: dict[str, Shot] = {}

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    def register(self, path: Path) -> str:
        """Register a file for download; returns the URL name (<token><suffix>)."""
        self._purge()
        name = f"{secrets.token_urlsafe(16)}{path.suffix}"
        self._shots[name] = Shot(path=path, expires_at=time.time() + self._ttl)
        while len(self._shots) > MAX_SHOTS:
            oldest = min(self._shots, key=lambda n: self._shots[n].expires_at)
            self._delete(oldest)
        return name

    def resolve(self, name: str) -> Path | None:
        """Return the file for a still-valid name, else None."""
        self._purge()
        shot = self._shots.get(name)
        if shot is None or not shot.path.exists():
            return None
        return shot.path

    def _purge(self) -> None:
        now = time.time()
        for name in [n for n, s in self._shots.items() if s.expires_at <= now]:
            self._delete(name)

    def _delete(self, name: str) -> None:
        shot = self._shots.pop(name, None)
        if shot is not None:
            with suppress(OSError):
                shot.path.unlink(missing_ok=True)
