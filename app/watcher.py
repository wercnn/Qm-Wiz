"""Watch a folder for new PDFs, zips and folders. Simple polling, so there is nothing extra to install."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from . import config


def _items(folder: Path) -> set[Path]:
    """PDFs, zips and folders directly inside the watched folder."""
    return {
        p for p in folder.iterdir()
        if not p.name.startswith(".") and (p.is_dir() or p.suffix.lower() in (".pdf", ".zip"))
    }


def _wait_until_complete(path: Path) -> bool:
    """Browsers write downloads in pieces. Wait until the size stops changing."""
    last = -1
    for _ in range(20):
        if not path.exists():
            return False
        if path.is_dir():
            time.sleep(2)  # give an unzip time to finish
            return True
        size = path.stat().st_size
        if size > 0 and size == last:
            return True
        last = size
        time.sleep(0.5)
    return False


def start(on_new_pdf: Callable[[Path], None]) -> None:
    """Call on_new_pdf for every PDF, zip or folder that appears after the app starts.

    Things already in the folder are ignored, so old downloads are never touched.
    """
    def loop() -> None:
        seen = _items(config.WATCH_DIR)
        while True:
            time.sleep(1)
            try:
                current = _items(config.WATCH_DIR)
            except OSError:
                continue
            for path in sorted(current - seen):
                if _wait_until_complete(path):
                    on_new_pdf(path)
            seen = current

    threading.Thread(target=loop, daemon=True).start()
