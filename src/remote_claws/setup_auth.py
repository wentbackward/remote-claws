from __future__ import annotations

import json
import secrets
import sys
from base64 import urlsafe_b64encode
from pathlib import Path

from remote_claws.auth import hash_token
from remote_claws.config import AppConfig


def main() -> None:
    """Interactive setup: generate (or keep) the bearer token, then offer to
    chain into the browser-profile setup.

    Re-running this is the supported way to seed the Chrome profile after
    the fact, so declining to overwrite an existing token must keep the
    rest of the setup flow alive — not abort the whole script.
    """
    config = AppConfig()
    auth_path = Path(config.auth_file)

    if _generate_token(auth_path) is False:
        # User declined to overwrite an existing token. That's fine — the
        # token they already have still works; carry on to the next step.
        print(f"Keeping existing token in {auth_path.resolve()}.")
        print()

    _configure_transport()
    _maybe_run_browser_setup()


def _generate_token(auth_path: Path) -> bool:
    """Generate and write a fresh bearer token, prompting before overwriting
    an existing file. Returns True if a new token was written, False if the
    user chose to keep the existing one."""
    if auth_path.exists():
        print(f"Auth file already exists: {auth_path}")
        response = input(
            "Overwrite and generate a new token? [y/N] "
        ).strip().lower()
        if response not in {"y", "yes"}:
            return False

    # Cryptographically random token (48 bytes → 64-char base64url).
    raw_bytes = secrets.token_bytes(48)
    token = urlsafe_b64encode(raw_bytes).decode().rstrip("=")

    auth_data = {"token_hash": hash_token(token)}
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
    print()
    return True


def _configure_transport() -> None:
    """Ask the user which MCP transport to use and persist the choice.

    SSE is the legacy transport (Claude Desktop, openclaw, most existing
    clients). Streamable HTTP is the MCP spec 2025-03-26+ transport
    (Claude Code, newer SDKs).

    If the config file already exists and contains a transport setting we
    skip the prompt — the user already made a choice.
    """
    config_path = Path(AppConfig().config_file)
    if config_path.exists():
        try:
            with open(config_path) as f:
                existing = json.load(f)
            if "transport" in existing:
                # Already configured — nothing to do.
                return
        except (json.JSONDecodeError, OSError):
            pass

    if not sys.stdin.isatty():
        # Non-interactive: default to SSE.
        return

    response = input(
        "Which MCP transport should the server expose?\n"
        "\n"
        "  1) SSE (legacy) — works with Claude Desktop, openclaw,\n"
        "     most existing clients. Default.\n"
        "  2) Streamable HTTP — MCP spec 2025-03-26+. Works with\n"
        "     Claude Code and newer SDKs.\n"
        "\n"
        "  [1] SSE  [2] Streamable HTTP  (default: 1)\n"
    ).strip()

    transport = "sse"
    if response in {"2", "streamable-http", "streamable"}:
        transport = "streamable-http"

    # Merge into the existing config file (or create it).
    config_data: dict = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                config_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    config_data["transport"] = transport
    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)
        f.write("\n")

    print(f"\n  Transport set to: {transport}")
    print(f"  Written to: {config_path.resolve()}")


def _maybe_run_browser_setup() -> None:
    """Offer to chain into the browser-profile setup. Skipped silently when
    stdin is not a TTY (e.g. piped invocation in CI) so this remains safe
    to call from automation.
    """
    if not sys.stdin.isatty():
        return
    response = input(
        "Set up the dedicated Chrome profile now so the agent can\n"
        "browse with your identity (sign into services, install adblocker,\n"
        "accept cookie banners)? [Y/n] "
    ).strip().lower()
    if response and response not in {"y", "yes"}:
        print("Skipped. Run `remote-claws-browser-setup` later when ready.")
        return
    # Imported lazily so a missing browser dep (Chrome not installed yet)
    # doesn't break auth-only setup runs.
    from remote_claws.browser.setup import run_browser_setup
    run_browser_setup()


if __name__ == "__main__":
    main()
