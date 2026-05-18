"""Smoke tests — verify the package imports and the data models behave."""

from __future__ import annotations

import geofabrik


def test_version_is_semver_shaped() -> None:
    assert isinstance(geofabrik.__version__, str)
    assert geofabrik.__version__.count(".") == 2


def test_region_reports_available_formats() -> None:
    region = geofabrik.Region(
        id="turkey",
        name="Turkey",
        parent="asia",
        iso3166_1_alpha2=("TR",),
        urls={
            "pbf": "https://example.test/turkey-latest.osm.pbf",
            "shp": "https://example.test/turkey-latest-free.shp.zip",
        },
    )
    assert region.available_formats == frozenset({"pbf", "shp"})


def test_region_without_urls_has_no_formats() -> None:
    region = geofabrik.Region(id="x", name="X", parent=None)
    assert region.available_formats == frozenset()


def test_error_hierarchy() -> None:
    assert issubclass(geofabrik.RegionNotFoundError, geofabrik.GeofabrikError)
    assert issubclass(geofabrik.FormatNotAvailableError, geofabrik.GeofabrikError)
    assert issubclass(geofabrik.ChecksumMismatchError, geofabrik.GeofabrikError)
    assert issubclass(geofabrik.IndexFetchError, geofabrik.GeofabrikError)
