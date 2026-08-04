"""`remote-claws-browser-setup` CLI.

Opens the dedicated agent Chrome profile so the user can sign into the
services they want the agent to access (Gmail, NYT, Reddit, GitHub,
whatever), accept cookie banners, install their adblocker, and so on.

Chrome is launched **directly** via subprocess \u2014 not via Playwright \u2014
so the setup browser is indistinguishable from any other Chrome instance.
That matters for login flows that sniff for automation: even a brief
encounter with `navigator.webdriver = true` during sign-in can poison
the session.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from remote_claws.browser.profile import (
    find_chrome_executable,
    is_profile_locked,
    resolve_profile_dir,
    write_channel_stamp,
)
from remote_claws.config import AppConfig


def run_browser_setup(url: str | None = None) -> int:
    """Open Chrome on the dedicated profile, blocking until the user closes
    it. Returns a process exit code suitable for sys.exit().

    Importable so `remote-claws-setup` can chain into it directly without
    re-parsing argv.
    """
    config = AppConfig()
    profile_dir = resolve_profile_dir(config.browser_profile_dir)

    chrome = find_chrome_executable()
    if chrome is None:
        print(
            "ERROR: Google Chrome was not found on this machine.\n"
            "Install Chrome from https://www.google.com/chrome/ and try again.",
            file=sys.stderr,
        )
        return 1

    # This tool seeds the profile with REAL Chrome. If the server is
    # configured for a different channel (e.g. a leftover browser_channel
    # in remote-claws.json), the server will refuse to start with this
    # profile. Warn now, while the operator is here to fix it.
    if config.browser_channel != "chrome":
        print(
            f"WARNING: browser_channel is '{config.browser_channel}' "
            f"(from {config.source_of('browser_channel')}), but this setup "
            "launches real Google Chrome and stamps the profile as 'chrome'.\n"
            "The server will refuse to start with this profile while the "
            f"channel is '{config.browser_channel}'. Fix the setting, or point "
            "REMOTE_CLAWS_BROWSER_PROFILE_DIR at a separate directory.\n",
            file=sys.stderr,
        )

    if is_profile_locked(profile_dir):
        print(
            f"ERROR: Chrome profile at {profile_dir} appears to be in use.\n"
            "Stop the running remote-claws server (or any other Chrome\n"
            "instance using this profile) and try again. If the server\n"
            "crashed previously, delete the SingletonLock / lockfile in\n"
            "that directory to clear the stale lock.",
            file=sys.stderr,
        )
        return 1

    # This CLI launches real Chrome directly, so it owns the profile as
    # channel 'chrome'. Stamping that here lets the server fail fast at
    # startup if it is later configured with channel=chromium (bundled
    # Playwright build) — mixing builds on one profile crashes the browser.
    write_channel_stamp(profile_dir, "chrome")

    print()
    print("=" * 64)
    print("  Remote Claws \u2014 Browser Profile Setup")
    print("=" * 64)
    print()
    print(f"  Chrome:   {chrome}")
    print(f"  Profile:  {profile_dir}")
    print()
    print("  Chrome will open in a moment. While it's open:")
    print()
    print("    1. Sign into the services you want the agent to use")
    print("       (email, news sites, code hosts, etc.)")
    print("    2. Install any extensions you want (adblocker, etc.)")
    print("    3. Accept cookie banners on sites you'll visit")
    print()
    print("  >>> WHEN YOU'RE DONE: CLOSE THE CHROME WINDOW. <<<")
    print()
    print("  This script is blocked waiting for Chrome to exit. Closing")
    print("  Chrome ends setup and returns you to the terminal so you can")
    print("  start the server with `remote-claws`. Sessions persist across")
    print("  server restarts.")
    print()
    print("=" * 64)
    print()
    print("  Waiting for you to close Chrome...", flush=True)
    print()

    args = [
        str(chrome),
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if url:
        args.append(url)

    try:
        # Block until the user closes Chrome. We do not capture stdout/stderr
        # because Chrome's diagnostic chatter is harmless and seeing it can
        # help debug profile issues.
        completed = subprocess.run(args, check=False)
    except KeyboardInterrupt:
        print("\nSetup interrupted by user.")
        return 130

    print()
    print("=" * 64)
    if completed.returncode == 0:
        print("  Profile updated. Sign-ins are persisted.")
    else:
        # Chrome's exit codes are not particularly informative for our
        # purpose. We surface the number but do not treat non-zero as a
        # hard failure \u2014 it's normal for Chrome to exit with a code other
        # than 0 on some platforms even after a clean window close.
        print(
            f"  Chrome exited with code {completed.returncode}. If you completed\n"
            "  sign-ins before closing, the profile is still updated."
        )
    print()
    print("  Next: start the server with")
    print("      remote-claws")
    print("=" * 64)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="remote-claws-browser-setup",
        description=(
            "Open the dedicated agent Chrome profile so you can sign into "
            "services you want the remote-claws agent to access."
        ),
    )
    parser.add_argument(
        "--url",
        help="Optional URL to open Chrome on (e.g. https://nytimes.com).",
    )
    ns = parser.parse_args()
    sys.exit(run_browser_setup(url=ns.url))


if __name__ == "__main__":
    main()
