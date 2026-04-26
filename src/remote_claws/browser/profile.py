"""Pure helpers for the persistent Chrome profile.

Kept free of Playwright and pyautogui imports so the auth-token setup CLI
can import this without dragging the whole automation stack in.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

# Files Chrome creates in user_data_dir while it is running. Their presence
# is a strong (not perfect) signal that another Chrome instance owns the
# profile. On Unix SingletonLock is a symlink whose target encodes
# hostname-pid; on Windows there is no symlink, only the lock files.
_UNIX_LOCK_NAME = "SingletonLock"
_WIN_LOCK_NAME = "lockfile"


def default_profile_dir() -> Path:
    """OS-appropriate default location for the dedicated agent Chrome profile.

    Each user gets their own profile under the platform's per-user data
    directory. We deliberately do not point at the user's normal Chrome
    profile \u2014 sharing it would (a) conflict with the single-instance lock
    whenever they have Chrome open, and (b) expose every signed-in service
    they own to the agent. The user opts services in by signing into them
    inside the dedicated profile.
    """
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Local")
        return Path(base) / "RemoteClaws" / "chrome-profile"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "RemoteClaws" / "chrome-profile"
    # Linux / other Unix \u2014 follow XDG.
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "remote-claws" / "chrome-profile"


def resolve_profile_dir(configured: str) -> Path:
    """Resolve the configured browser_profile_dir, falling back to the OS
    default when the config value is empty. Always returns an absolute path
    with parents created."""
    path = Path(configured).expanduser() if configured else default_profile_dir()
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_profile_locked(profile_dir: Path) -> bool:
    """Heuristic: is another Chrome process currently using this profile?

    Used by the setup CLI to give the user a clear error instead of letting
    Chrome flash up and die with a cryptic 'profile is in use' dialog. False
    negatives are possible (stale lock files after a crash) \u2014 those
    surface as a normal Chrome error on launch, which is recoverable.
    """
    if not profile_dir.exists():
        return False
    if platform.system() == "Windows":
        # Chrome's lockfile is opened with exclusive sharing; existence alone
        # is a reasonable signal because Chrome removes it on clean exit.
        return (profile_dir / _WIN_LOCK_NAME).exists()
    # Unix: SingletonLock is a symlink. islink() is true even when the
    # target process is gone (stale lock), but matching Chrome's own check
    # is good enough for our purpose \u2014 we tell the user to stop the server
    # or remove the file.
    return (profile_dir / _UNIX_LOCK_NAME).is_symlink()


def find_chrome_executable() -> Path | None:
    """Locate the system Google Chrome binary, or return None if not found.

    Used at server startup to fail fast when the configured channel is
    'chrome' but Chrome is not installed. We do not consult Playwright here
    because (a) Playwright requires its own runtime to answer this, and
    (b) the setup CLI needs to spawn Chrome directly without Playwright in
    the picture at all.
    """
    system = platform.system()
    candidates: list[Path] = []
    if system == "Windows":
        program_files = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("LocalAppData", str(Path.home() / "AppData" / "Local")),
        ]
        for pf in program_files:
            candidates.append(Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif system == "Darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
        candidates.append(Path.home() / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome")
    else:
        # Linux \u2014 prefer PATH lookup, then well-known absolute paths.
        for name in ("google-chrome", "google-chrome-stable", "chrome"):
            found = shutil.which(name)
            if found:
                return Path(found)
        candidates.extend([
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/opt/google/chrome/chrome"),
        ])

    for c in candidates:
        if c.is_file():
            return c
    # Final fallback: PATH lookup on all platforms (handles unusual installs).
    for name in ("chrome", "chrome.exe", "google-chrome"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None
