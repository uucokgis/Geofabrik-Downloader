"""Public Client — the single entry point for library users."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import httpx

from . import download as _dl
from .cache import default_cache_dir
from .catalogue import Catalogue
from .errors import FormatNotAvailableError
from .models import FORMAT_TO_INDEX_KEY, DownloadResult, Format, Region


class Client:
    """Discover and download Geofabrik OSM extracts.

    Usage::

        with Client() as client:
            turkey = client.get_region("turkey")
            result = client.download(turkey, format="pbf", dest="./data")

    Parameters
    ----------
    cache_dir:
        Directory for the cached index file.  Defaults to the OS user-cache dir
        (``~/Library/Caches/geofabrik-downloader`` on macOS, etc.).
    index_ttl_hours:
        How long to keep the cached index before re-fetching.  Default: 24 h.
    timeout:
        HTTP request timeout in seconds.  Default: 30 s.
    user_agent:
        Override the ``User-Agent`` header.
    include_geometry:
        When ``True`` the full ``index-v1.json`` (~50 MB) is fetched and
        ``Region.geometry`` is populated.  Default: ``False`` (500 KB
        geometry-free index).
    """

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        index_ttl_hours: float = 24.0,
        timeout: float = 30.0,
        user_agent: str | None = None,
        include_geometry: bool = False,
    ) -> None:
        from . import __version__

        cache_path = Path(cache_dir) if cache_dir is not None else default_cache_dir()
        ua = user_agent or f"geofabrik-downloader/{__version__}"

        self._http = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": ua},
            follow_redirects=True,
        )
        self._catalogue = Catalogue(
            http=self._http,
            cache_dir=cache_path,
            ttl_hours=index_ttl_hours,
            include_geometry=include_geometry,
        )

    # ── Context manager ──────────────────────────────────────────────────────

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http.close()

    # ── Catalogue ────────────────────────────────────────────────────────────

    def list_regions(self, parent: str | None = None) -> list[Region]:
        """Return regions whose parent matches *parent*.

        Pass ``parent=None`` (default) for top-level continents; pass a
        region id to list its direct children.
        """
        return self._catalogue.list_regions(parent)

    def get_region(self, region_id: str) -> Region:
        """Return the region for *region_id*, raising ``RegionNotFoundError`` if absent."""
        return self._catalogue.get_region(region_id)

    def search_regions(self, query: str) -> list[Region]:
        """Case-insensitive substring search over region id and name."""
        return self._catalogue.search_regions(query)

    def children_of(self, region_id: str) -> list[Region]:
        """Return direct children of *region_id*."""
        return self._catalogue.children_of(region_id)

    def refresh_index(self) -> None:
        """Force a re-fetch of the Geofabrik index regardless of cache TTL."""
        self._catalogue.refresh()

    # ── Downloads ────────────────────────────────────────────────────────────

    def download_url(self, region: Region | str, format: Format) -> str:
        """Return the download URL for *region* + *format* without fetching the file.

        Raises ``FormatNotAvailableError`` if the region does not offer *format*.
        """
        r = self._resolve(region)
        key = FORMAT_TO_INDEX_KEY[format]
        if key not in r.urls:
            raise FormatNotAvailableError(r.id, format, r.available_formats)
        return r.urls[key]

    def download(
        self,
        region: Region | str,
        format: Format,
        dest: Path | str = ".",
        verify: bool = True,
        resume: bool = True,
        overwrite: bool = False,
        progress: Callable[[int, int | None], None] | None = None,
    ) -> DownloadResult:
        """Download *region* in *format* to the *dest* directory.

        Parameters
        ----------
        region:    A ``Region`` object or a region id string (e.g. ``"turkey"``).
        format:    One of ``"pbf"``, ``"shp"``, ``"gpkg"``, ``"bz2"``, ``"poly"``, ``"kml"``.
        dest:      Destination directory (created if absent).  Default: current dir.
        verify:    Verify MD5 checksum after download.  Default: ``True``.
        resume:    Resume an interrupted download if a ``.part`` file exists.
        overwrite: Re-download even if the file already exists.
        progress:  Callback ``(bytes_downloaded, total_or_none)`` fired per chunk.
        """
        url = self.download_url(region, format)
        return _dl.download(
            http=self._http,
            url=url,
            dest=Path(dest),
            verify=verify,
            resume=resume,
            overwrite=overwrite,
            progress=progress,
        )

    # ── Internal ─────────────────────────────────────────────────────────────

    def _resolve(self, region: Region | str) -> Region:
        return region if isinstance(region, Region) else self.get_region(region)
