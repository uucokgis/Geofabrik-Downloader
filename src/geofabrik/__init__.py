"""geofabrik-downloader: a lightweight Python client for Geofabrik OSM extracts."""

from __future__ import annotations

from .client import Client
from .errors import (
    ChecksumMismatchError,
    FormatNotAvailableError,
    GeofabrikError,
    GeometryNotLoadedError,
    IndexFetchError,
    LayerNotFoundError,
    RegionNotFoundError,
)
from .models import DownloadResult, Format, Region, ShpLayer

__version__ = "0.1.0"

__all__ = [
    "ChecksumMismatchError",
    "Client",
    "DownloadResult",
    "Format",
    "FormatNotAvailableError",
    "GeofabrikError",
    "GeometryNotLoadedError",
    "IndexFetchError",
    "LayerNotFoundError",
    "Region",
    "RegionNotFoundError",
    "ShpLayer",
    "__version__",
]
