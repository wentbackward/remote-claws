"""Test the profile channel stamp: roundtrip, preflight mismatch detection."""

import pytest

from remote_claws.browser.manager import BrowserManager, BrowserStartupError
from remote_claws.browser.profile import read_channel_stamp, write_channel_stamp
from remote_claws.config import AppConfig


def _config(tmp_path, channel: str) -> AppConfig:
    return AppConfig(
        browser_channel=channel,
        browser_profile_dir=str(tmp_path / "profile"),
        permissions_file=str(tmp_path / "perms.json"),
        auth_file=str(tmp_path / "auth.json"),
    )


def test_stamp_roundtrip(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    assert read_channel_stamp(profile) is None  # never stamped
    write_channel_stamp(profile, "chrome")
    assert read_channel_stamp(profile) == "chrome"
    write_channel_stamp(profile, "chromium")  # re-stamp
    assert read_channel_stamp(profile) == "chromium"


def test_stamp_missing_dir_returns_none(tmp_path):
    assert read_channel_stamp(tmp_path / "nonexistent") is None


def test_preflight_passes_when_stamp_matches(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    write_channel_stamp(profile, "chromium")
    BrowserManager(_config(tmp_path, "chromium")).preflight()  # must not raise


def test_preflight_passes_when_unstamped(tmp_path):
    # Pre-feature profile: no stamp, nothing to mismatch. Channel chromium
    # needs no Chrome binary, so this must not raise.
    BrowserManager(_config(tmp_path, "chromium")).preflight()


def test_preflight_rejects_channel_mismatch(tmp_path):
    """The failure mode from the field: setup CLI seeded the profile with
    real Chrome, server then configured with bundled Chromium."""
    profile = tmp_path / "profile"
    profile.mkdir()
    write_channel_stamp(profile, "chrome")

    with pytest.raises(BrowserStartupError, match=r"channel='chromium'.*created by channel 'chrome'"):
        BrowserManager(_config(tmp_path, "chromium")).preflight()


def test_preflight_rejects_reverse_mismatch(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    write_channel_stamp(profile, "chromium")

    with pytest.raises(BrowserStartupError, match=r"channel='chrome'.*created by channel 'chromium'"):
        BrowserManager(_config(tmp_path, "chrome")).preflight()


def test_preflight_error_names_remedies(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    write_channel_stamp(profile, "chrome")

    with pytest.raises(BrowserStartupError) as exc_info:
        BrowserManager(_config(tmp_path, "chromium")).preflight()
    msg = str(exc_info.value)
    assert "REMOTE_CLAWS_BROWSER_CHANNEL" in msg
    assert "REMOTE_CLAWS_BROWSER_PROFILE_DIR" in msg
    assert ".remote-claws-channel" in msg
