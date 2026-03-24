from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PYWINMCP_")

    host: str = "0.0.0.0"
    port: int = 8080
    browser_headless: bool = False
    browser_channel: str = "chromium"
    screenshot_max_width: int = 1280
    screenshot_max_height: int = 960
    screenshot_quality: int = 75
    screenshot_dir: str = ""
    permissions_file: str = "permissions.json"
