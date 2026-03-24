from __future__ import annotations

import io
import os
import time
from pathlib import Path

from PIL import Image as PILImage


def downscale_and_encode(
    raw_bytes: bytes,
    max_width: int = 1280,
    max_height: int = 960,
    quality: int = 75,
    save_path: str | None = None,
) -> tuple[bytes, str | None]:
    """
    Takes raw PNG screenshot bytes.
    Returns (jpeg_bytes, optional_saved_path).
    """
    img = PILImage.open(io.BytesIO(raw_bytes))
    img.thumbnail((max_width, max_height), PILImage.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    jpeg_bytes = buf.getvalue()

    saved = None
    if save_path:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(jpeg_bytes)
        saved = save_path

    return jpeg_bytes, saved


def make_save_path(screenshot_dir: str) -> str | None:
    if not screenshot_dir:
        return None
    os.makedirs(screenshot_dir, exist_ok=True)
    return os.path.join(screenshot_dir, f"screenshot_{int(time.time() * 1000)}.jpg")
