"""Geofabrik index fetching, parsing, and region tree."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from . import cache as _cache
from .errors import GeometryNotLoadedError, IndexFetchError, RegionNotFoundError
from .models import FORMAT_TO_INDEX_KEY, Region

INDEX_URL_NOGEOM = "https://download.geofabrik.de/index-v1-nogeom.json"
INDEX_URL_GEOM = "https://download.geofabrik.de/index-v1.json"

_DOWNLOAD_KEYS: frozenset[str] = frozenset(FORMAT_TO_INDEX_KEY.values())


class Catalogue:
    """In-process region tree backed by a locally cached copy of the Geofabrik index.

    By default the geometry-free index (~500 KB) is used. Pass
    ``include_geometry=True`` to fetch the full GeoJSON index (~50 MB) which
    populates ``Region.geometry`` and enables spatial queries.
    """

    def __init__(
        self,
        http: httpx.Client,
        cache_dir: Path,
        ttl_hours: float,
        include_geometry: bool = False,
    ) -> None:
        self._http = http
        self._ttl = ttl_hours
        self._include_geometry = include_geometry
        self._index_url = INDEX_URL_GEOM if include_geometry else INDEX_URL_NOGEOM
        cache_file = "index-v1.json" if include_geometry else "index-v1-nogeom.json"
        self._cache_path = cache_dir / cache_file
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

    def find_by_point(self, lat: float, lon: float) -> list[Region]:
        """Return all regions whose bounding box contains ``(lat, lon)``.

        Results are sorted smallest-first (most specific region first).
        Requires ``include_geometry=True``; raises
        :exc:`~geofabrik.GeometryNotLoadedError` otherwise.

        .. note::
            This is a **bounding-box approximation** — no point-in-polygon
            test is performed.  For exact containment use ``shapely``::

                from shapely.geometry import Point, shape
                pt = Point(lon, lat)
                exact = [r for r in results if shape(r.geometry).contains(pt)]
        """
        self._require_geometry()
        return self._spatial_filter(lambda b: b[0] <= lon <= b[2] and b[1] <= lat <= b[3])

    def find_by_bbox(
        self,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
    ) -> list[Region]:
        """Return all regions whose bounding box overlaps with the given bbox.

        Results are sorted smallest-first (most specific region first).
        Requires ``include_geometry=True``; raises
        :exc:`~geofabrik.GeometryNotLoadedError` otherwise.
        """
        self._require_geometry()

        def _overlaps(b: tuple[float, float, float, float]) -> bool:
            return not (b[2] < min_lon or b[0] > max_lon or b[3] < min_lat or b[1] > max_lat)

        return self._spatial_filter(_overlaps)

    # ------------------------------------------------------------------
    # Internal

    def _require_geometry(self) -> None:
        if not self._include_geometry:
            raise GeometryNotLoadedError()

    def _spatial_filter(
        self,
        predicate: Any,
    ) -> list[Region]:
        """Apply *predicate(bbox)* to all regions that have geometry."""
        hits: list[tuple[float, Region]] = []
        for region in self._load().values():
            if region.geometry is None:
                continue
            bbox = _geometry_bbox(region.geometry)
            if bbox is None:
                continue
            if predicate(bbox):
                area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                hits.append((area, region))
        hits.sort(key=lambda x: x[0])
        return [r for _, r in hits]

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
            response = self._http.get(self._index_url)
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


# ---------------------------------------------------------------------------
# Geometry helpers (module-level, no shapely)


def _flatten_coords(geometry: dict[str, Any]) -> list[list[float]]:
    gtype = geometry.get("type")
    coords: Any = geometry.get("coordinates", [])
    if gtype == "Polygon":
        return [pt for ring in coords for pt in ring]
    if gtype == "MultiPolygon":
        return [pt for poly in coords for ring in poly for pt in ring]
    return []


def _geometry_bbox(
    geometry: dict[str, Any],
) -> tuple[float, float, float, float] | None:
    """Return ``(min_lon, min_lat, max_lon, max_lat)`` for a GeoJSON geometry."""
    pts = _flatten_coords(geometry)
    if not pts:
        return None
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return min(lons), min(lats), max(lons), max(lats)
