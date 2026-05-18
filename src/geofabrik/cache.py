"""Cache path resolution and freshness checking for the Geofabrik index."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_APP = "geofabrik-downloader"


def default_cache_dir() -> Path:
    """Return the OS-appropriate user cache directory for this package."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / _APP
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / _APP / "Cache"
    # Linux / other POSIX — honour XDG
    xdg = os.environ.get("XDG_CACHE_HOME")
    return Path(xdg) / _APP if xdg else Path.home() / ".cache" / _APP


def is_fresh(path: Path, ttl_hours: float) -> bool:
    """Return True if *path* exists and is younger than *ttl_hours*."""
    try:
        age = time.time() - path.stat().st_mtime
        return age < ttl_hours * 3600
    except FileNotFoundError:
        return False


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def write_bytes(path: Path, data: bytes) -> None:
    """Write *data* to *path* atomically via a sibling .tmp file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
