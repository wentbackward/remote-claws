from __future__ import annotations

import hashlib
import hmac
import json
import logging
from pathlib import Path

from mcp.server.auth.provider import AccessToken

logger = logging.getLogger(__name__)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def load_token_hash(auth_file: str) -> str:
    p = Path(auth_file)
    if not p.exists():
        raise FileNotFoundError(
            f"Auth file not found: {auth_file}\nRun 'remote-claws-setup' to generate authentication credentials."
        )
    with open(p) as f:
        data = json.load(f)
    token_hash = data.get("token_hash")
    if not token_hash:
        raise ValueError(f"Auth file {auth_file} is missing 'token_hash' field.")
    logger.info("Loaded auth token hash from %s", auth_file)
    return token_hash


class HashedTokenVerifier:
    """MCP TokenVerifier that compares bearer tokens against a stored SHA-256 hash."""

    def __init__(self, token_hash: str):
        self._token_hash = token_hash

    async def verify_token(self, token: str) -> AccessToken | None:
        incoming_hash = hash_token(token)
        if hmac.compare_digest(incoming_hash, self._token_hash):
            return AccessToken(
                token=token,
                client_id="remote-agent",
                scopes=["*"],
            )
        logger.warning("Rejected connection: invalid bearer token")
        return None
