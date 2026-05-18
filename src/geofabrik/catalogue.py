"""Geofabrik index fetching, parsing, and region tree."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from . import cache as _cache
from .errors import IndexFetchError, RegionNotFoundError
from .models import FORMAT_TO_INDEX_KEY, Region

INDEX_URL = "https://download.geofabrik.de/index-v1-nogeom.json"

_DOWNLOAD_KEYS: frozenset[str] = frozenset(FORMAT_TO_INDEX_KEY.values())


class Catalogue:
    """In-process region tree backed by a locally cached copy of the Geofabrik index."""

    def __init__(self, http: httpx.Client, cache_dir: Path, ttl_hours: float) -> None:
        self._http = http
        self._cache_path = cache_dir / "index-v1-nogeom.json"
        self._ttl = ttl_hours
        self._index: dict[str, Region] | None = None

    # ------------------------------------------------------------------
    # Public interface

    def list_regions(self, parent: str | None = None) -> list[Region]:
        """Return regions whose parent matches *parent*.

        Pass ``parent=None`` (the default) to list top-level continents.
        Pass a region id string to list its direct children.
        """
        return [r for r in self._load().values() if r.parent == parent]

    def get_region(self, region_id: str) -> Region:
        """Return the region for *region_id*, raising RegionNotFoundError if absent."""
        try:
            return self._load()[region_id]
        except KeyError:
            raise RegionNotFoundError(region_id)

    def search_regions(self, query: str) -> list[Region]:
        """Case-insensitive substring search over region id and name."""
        q = query.lower()
        return [r for r in self._load().values() if q in r.id.lower() or q in r.name.lower()]

    def children_of(self, region_id: str) -> list[Region]:
        """Return direct children of *region_id*, raising RegionNotFoundError if absent."""
        self.get_region(region_id)  # validate parent exists
        return [r for r in self._load().values() if r.parent == region_id]

    def refresh(self) -> None:
        """Force a re-fetch of the index regardless of cache freshness."""
        data = self._fetch()
        _cache.write_bytes(self._cache_path, data)
        self._index = self._parse(data)

    # ------------------------------------------------------------------
    # Internal

    def _load(self) -> dict[str, Region]:
        if self._index is not None:
            return self._index
        if _cache.is_fresh(self._cache_path, self._ttl):
            raw = _cache.read_bytes(self._cache_path)
        else:
            raw = self._fetch()
            _cache.write_bytes(self._cache_path, raw)
        self._index = self._parse(raw)
        return self._index

    def _fetch(self) -> bytes:
        try:
            response = self._http.get(INDEX_URL)
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            raise IndexFetchError(f"Failed to fetch Geofabrik index: {exc}") from exc

    def _parse(self, data: bytes) -> dict[str, Region]:
        try:
            geojson: dict[str, Any] = json.loads(data)
            features: list[dict[str, Any]] = geojson["features"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise IndexFetchError(f"Unexpected index format: {exc}") from exc

        result: dict[str, Region] = {}
        for feat in features:
            props: dict[str, Any] = feat.get("properties") or {}
            region_id: str | None = props.get("id")
            if not region_id:
                continue
            raw_urls: dict[str, str] = props.get("urls") or {}
            result[region_id] = Region(
                id=region_id,
                name=props.get("name", region_id),
                parent=props.get("parent"),
                iso3166_1_alpha2=tuple(props.get("iso3166-1:alpha2") or []),
                iso3166_2=tuple(props.get("iso3166-2") or []),
                # Keep only download-relevant URL keys; strip pbf-internal, history, etc.
                urls={k: v for k, v in raw_urls.items() if k in _DOWNLOAD_KEYS},
                geometry=feat.get("geometry"),
            )

        if not result:
            raise IndexFetchError("Index parsed successfully but contained no regions.")

        return result
