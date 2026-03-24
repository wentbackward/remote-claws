from __future__ import annotations

import json
import secrets
import sys
from base64 import urlsafe_b64encode
from pathlib import Path

from remote_claws.auth import hash_token
from remote_claws.config import AppConfig


def main() -> None:
    config = AppConfig()
    auth_path = Path(config.auth_file)

    if auth_path.exists():
        print(f"Auth file already exists: {auth_path}")
        response = input("Overwrite? [y/N] ").strip().lower()
        if response != "y":
            print("Aborted.")
            sys.exit(0)

    # Generate a cryptographically random token (48 bytes → 64-char base64url)
    raw_bytes = secrets.token_bytes(48)
    token = urlsafe_b64encode(raw_bytes).decode().rstrip("=")

    token_hash = hash_token(token)

    auth_data = {"token_hash": token_hash}
    with open(auth_path, "w") as f:
        json.dump(auth_data, f, indent=2)
        f.write("\n")

    print()
    print("=" * 60)
    print("  Remote Claws — Authentication Setup")
    print("=" * 60)
    print()
    print("  Auth file written to:", auth_path.resolve())
    print()
    print("  Your bearer token (copy this to your agent config):")
    print()
    print(f"  {token}")
    print()
    print("  This token will NOT be shown again.")
    print("  Only the hash is stored on disk.")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
