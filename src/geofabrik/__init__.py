"""geofabrik-downloader: a lightweight Python client for Geofabrik OSM extracts."""

from __future__ import annotations

from .errors import (
    ChecksumMismatchError,
    FormatNotAvailableError,
    GeofabrikError,
    IndexFetchError,
    RegionNotFoundError,
)
from .models import DownloadResult, Format, Region

__version__ = "0.0.1"

__all__ = [
    "ChecksumMismatchError",
    "DownloadResult",
    "Format",
    "FormatNotAvailableError",
    "GeofabrikError",
    "IndexFetchError",
    "Region",
    "RegionNotFoundError",
    "__version__",
]
