"""Data models for Geofabrik regions and download results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Format = Literal["pbf", "shp", "gpkg", "bz2", "poly", "kml"]
"""Short-form file format identifiers accepted by the public API."""

ShpLayer = Literal[
    "buildings", "landuse", "natural", "places", "pois",
    "railways", "roads", "traffic", "transport", "water", "waterways",
]
"""Shapefile layer names present in a Geofabrik ``.shp.zip``."""

LAYER_TO_PREFIX: dict[ShpLayer, str] = {
    "buildings":  "gis_osm_buildings_a_free_1",
    "landuse":    "gis_osm_landuse_a_free_1",
    "natural":    "gis_osm_natural_a_free_1",
    "places":     "gis_osm_places_free_1",
    "pois":       "gis_osm_pois_free_1",
    "railways":   "gis_osm_railways_free_1",
    "roads":      "gis_osm_roads_free_1",
    "traffic":    "gis_osm_traffic_a_free_1",
    "transport":  "gis_osm_transport_a_free_1",
    "water":      "gis_osm_water_a_free_1",
    "waterways":  "gis_osm_waterways_free_1",
}
"""Maps a :data:`ShpLayer` name to its filename prefix inside the zip."""

FORMAT_TO_INDEX_KEY: dict[Format, str] = {
    "pbf": "pbf",
    "shp": "shp",
    "gpkg": "gpkg",
    "bz2": "bz2",
    "poly": "poly",
    "kml": "kml",
}
"""Mapping from short format identifiers to keys in ``index-v1.json`` -> ``properties.urls``."""


@dataclass(frozen=True, slots=True)
class Region:
    """A Geofabrik region (continent, country, or sub-national extract).

    Mirrors one feature from ``index-v1.json``. Geometry is exposed as a raw
    GeoJSON dict to keep ``shapely`` out of the runtime dependency tree.
    """

    id: str
    name: str
    parent: str | None
    iso3166_1_alpha2: tuple[str, ...] = ()
    iso3166_2: tuple[str, ...] = ()
    urls: dict[str, str] = field(default_factory=dict)
    geometry: dict[str, Any] | None = None

    @property
    def available_formats(self) -> frozenset[Format]:
        """Formats actually offered by Geofabrik for this region."""
        url_keys = self.urls.keys()
        return frozenset(
            fmt for fmt, key in FORMAT_TO_INDEX_KEY.items() if key in url_keys
        )


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """Outcome of a single download operation."""

    path: str
    bytes_written: int
    resumed: bool
    verified: bool
    url: str
