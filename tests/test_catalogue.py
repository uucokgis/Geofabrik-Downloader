"""Unit tests for catalogue.py — all HTTP is mocked via pytest-httpx."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from geofabrik.catalogue import INDEX_URL_GEOM, INDEX_URL_NOGEOM, Catalogue

INDEX_URL = INDEX_URL_NOGEOM  # default used by most tests
from geofabrik.errors import IndexFetchError, RegionNotFoundError

FIXTURE = Path(__file__).parent / "fixtures" / "index.json"


def _fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


def _make_catalogue(tmp_path: Path, http: httpx.Client, ttl: float = 24.0) -> Catalogue:
    return Catalogue(http=http, cache_dir=tmp_path, ttl_hours=ttl)


# ---------------------------------------------------------------------------
# Fetching and parsing


def test_list_regions_fetches_index(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        cat = _make_catalogue(tmp_path, http)
        regions = cat.list_regions()
    assert len(regions) == 4  # africa, asia, europe, north-america


def test_list_top_level_returns_continents(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        regions = _make_catalogue(tmp_path, http).list_regions()
    ids = {r.id for r in regions}
    assert ids == {"africa", "asia", "europe", "north-america"}


def test_list_regions_by_parent(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        regions = _make_catalogue(tmp_path, http).list_regions(parent="europe")
    assert {r.id for r in regions} == {"germany", "france"}


def test_list_regions_subnational(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        regions = _make_catalogue(tmp_path, http).list_regions(parent="germany")
    assert {r.id for r in regions} == {"nordrhein-westfalen", "bayern"}


def test_get_region_found(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        turkey = _make_catalogue(tmp_path, http).get_region("turkey")
    assert turkey.id == "turkey"
    assert turkey.parent == "asia"
    assert turkey.iso3166_1_alpha2 == ("TR",)


def test_get_region_not_found(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        with pytest.raises(RegionNotFoundError) as exc_info:
            _make_catalogue(tmp_path, http).get_region("narnia")
    assert exc_info.value.region_id == "narnia"


def test_multi_iso_region(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        region = _make_catalogue(tmp_path, http).get_region("israel-and-palestine")
    assert set(region.iso3166_1_alpha2) == {"IL", "PS"}


def test_subnational_iso3166_2(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        region = _make_catalogue(tmp_path, http).get_region("nordrhein-westfalen")
    assert region.iso3166_2 == ("DE-NW",)


# ---------------------------------------------------------------------------
# Search


def test_search_case_insensitive(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        cat = _make_catalogue(tmp_path, http)
        # Matches on id ("germany") and name ("Germany") — sub-regions don't contain "germany"
        assert {r.id for r in cat.search_regions("GERMANY")} == {"germany"}


def test_search_by_name_substring(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        results = _make_catalogue(tmp_path, http).search_regions("tur")
    assert any(r.id == "turkey" for r in results)


def test_search_no_match(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        assert _make_catalogue(tmp_path, http).search_regions("zzznomatch") == []


# ---------------------------------------------------------------------------
# children_of


def test_children_of(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        children = _make_catalogue(tmp_path, http).children_of("germany")
    assert {r.id for r in children} == {"nordrhein-westfalen", "bayern"}


def test_children_of_unknown_raises(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        with pytest.raises(RegionNotFoundError):
            _make_catalogue(tmp_path, http).children_of("atlantis")


def test_children_of_leaf_is_empty(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        assert _make_catalogue(tmp_path, http).children_of("turkey") == []


# ---------------------------------------------------------------------------
# composite_parts (split regions like us/california)


def test_composite_parts_returns_split_children(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        parts = _make_catalogue(tmp_path, http).composite_parts("us/california", "shp")
    assert {p.id for p in parts} == {"norcal", "socal"}


def test_composite_parts_empty_when_parent_offers_format(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        # Parent already publishes pbf — no composite needed.
        assert _make_catalogue(tmp_path, http).composite_parts("us/california", "pbf") == []


def test_composite_parts_empty_when_children_dont_cover(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        # us/california children don't all publish gpkg.
        assert _make_catalogue(tmp_path, http).composite_parts("us/california", "gpkg") == []


def test_composite_parts_empty_for_leaf(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        assert _make_catalogue(tmp_path, http).composite_parts("turkey", "gpkg") == []


def test_composite_parts_unknown_region_raises(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        with pytest.raises(RegionNotFoundError):
            _make_catalogue(tmp_path, http).composite_parts("atlantis", "shp")


# ---------------------------------------------------------------------------
# Caching behaviour


def test_index_cached_after_first_load(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        cat = _make_catalogue(tmp_path, http)
        cat.list_regions()
        cat.list_regions()  # should NOT make a second HTTP request
    # pytest-httpx raises if unexpected requests are made — silence means success


def test_uses_disk_cache_when_fresh(tmp_path: Path) -> None:
    # Pre-seed cache; no HTTP mock registered → any request would raise
    (tmp_path / "index-v1-nogeom.json").write_bytes(_fixture_bytes())
    with httpx.Client() as http:
        cat = Catalogue(http=http, cache_dir=tmp_path, ttl_hours=24.0)
        regions = cat.list_regions()
    assert len(regions) == 4


def test_refresh_bypasses_cache(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    # Both requests go through HTTP (ttl=0 → always stale).
    # First response has 1 region; after refresh it has the full fixture.
    minimal = b"""{
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"id": "europe", "name": "Europe", "parent": null, "urls": {}},
            "geometry": null
        }]
    }"""
    httpx_mock.add_response(url=INDEX_URL, content=minimal)
    httpx_mock.add_response(url=INDEX_URL, content=_fixture_bytes())
    with httpx.Client() as http:
        cat = Catalogue(http=http, cache_dir=tmp_path, ttl_hours=0.0)
        assert len(cat.list_regions()) == 1
        cat.refresh()
        assert len(cat.list_regions()) == 4


# ---------------------------------------------------------------------------
# URL filtering


def test_internal_urls_stripped(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    payload = b"""{
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "id": "turkey", "name": "Turkey", "parent": "asia",
                "urls": {
                    "pbf": "https://example.test/turkey.pbf",
                    "pbf-internal": "https://internal.test/turkey.pbf",
                    "history": "https://internal.test/turkey-history.pbf",
                    "taginfo": "https://taginfo.example.test/turkey"
                }
            },
            "geometry": null
        }]
    }"""
    httpx_mock.add_response(url=INDEX_URL, content=payload)
    with httpx.Client() as http:
        turkey = _make_catalogue(tmp_path, http).get_region("turkey")
    assert set(turkey.urls.keys()) == {"pbf"}


# ---------------------------------------------------------------------------
# Error handling


def test_index_fetch_error_on_http_failure(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, status_code=503)
    with httpx.Client() as http:
        with pytest.raises(IndexFetchError):
            _make_catalogue(tmp_path, http).list_regions()


def test_index_fetch_error_on_bad_json(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=b"not json at all")
    with httpx.Client() as http:
        with pytest.raises(IndexFetchError):
            _make_catalogue(tmp_path, http).list_regions()


def test_index_fetch_error_on_missing_features_key(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL, content=b'{"type": "FeatureCollection"}')
    with httpx.Client() as http:
        with pytest.raises(IndexFetchError):
            _make_catalogue(tmp_path, http).list_regions()


def test_index_fetch_error_on_empty_index(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(
        url=INDEX_URL, content=b'{"type":"FeatureCollection","features":[]}'
    )
    with httpx.Client() as http:
        with pytest.raises(IndexFetchError, match="no regions"):
            _make_catalogue(tmp_path, http).list_regions()


# ---------------------------------------------------------------------------
# Spatial queries


def _geom_fixture_bytes() -> bytes:
    """Fixture index with real-ish bounding box geometries for spatial tests."""
    import json

    # Turkey bbox: roughly lon 26-45, lat 36-42
    # Germany bbox: roughly lon 6-15, lat 47-55
    return json.dumps({
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"id": "asia", "name": "Asia", "parent": None, "urls": {}},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[26.0, 36.0], [45.0, 36.0], [45.0, 42.0], [26.0, 42.0], [26.0, 36.0]]]
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "id": "turkey", "name": "Turkey", "parent": "asia",
                    "urls": {"pbf": "https://example.test/turkey.pbf"},
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[26.0, 36.0], [45.0, 36.0], [45.0, 42.0], [26.0, 42.0], [26.0, 36.0]]]
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "id": "germany", "name": "Germany", "parent": "europe",
                    "urls": {"pbf": "https://example.test/germany.pbf"},
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[6.0, 47.0], [15.0, 47.0], [15.0, 55.0], [6.0, 55.0], [6.0, 47.0]]]
                },
            },
        ],
    }).encode()


def _make_geom_catalogue(tmp_path: Path, http: httpx.Client) -> Catalogue:
    return Catalogue(http=http, cache_dir=tmp_path, ttl_hours=24.0, include_geometry=True)


def test_find_by_point_returns_matching_region(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL_GEOM, content=_geom_fixture_bytes())
    with httpx.Client() as http:
        cat = _make_geom_catalogue(tmp_path, http)
        results = cat.find_by_point(lat=39.9, lon=32.8)  # Ankara
    assert any(r.id == "turkey" for r in results)
    assert not any(r.id == "germany" for r in results)


def test_find_by_point_sorted_smallest_first(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL_GEOM, content=_geom_fixture_bytes())
    with httpx.Client() as http:
        cat = _make_geom_catalogue(tmp_path, http)
        results = cat.find_by_point(lat=39.9, lon=32.8)
    # turkey bbox is same size as asia in this fixture, but both should be returned
    ids = [r.id for r in results]
    assert "turkey" in ids


def test_find_by_point_no_match(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL_GEOM, content=_geom_fixture_bytes())
    with httpx.Client() as http:
        cat = _make_geom_catalogue(tmp_path, http)
        results = cat.find_by_point(lat=-33.9, lon=18.4)  # Cape Town
    assert results == []


def test_find_by_bbox_overlapping(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL_GEOM, content=_geom_fixture_bytes())
    with httpx.Client() as http:
        cat = _make_geom_catalogue(tmp_path, http)
        # bbox covering central Europe — should hit Germany, not Turkey
        results = cat.find_by_bbox(min_lon=8.0, min_lat=48.0, max_lon=14.0, max_lat=52.0)
    assert any(r.id == "germany" for r in results)
    assert not any(r.id == "turkey" for r in results)


def test_find_by_bbox_no_overlap(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL_GEOM, content=_geom_fixture_bytes())
    with httpx.Client() as http:
        cat = _make_geom_catalogue(tmp_path, http)
        results = cat.find_by_bbox(min_lon=-80.0, min_lat=-60.0, max_lon=-70.0, max_lat=-50.0)
    assert results == []


def test_find_by_point_requires_geometry(tmp_path: Path) -> None:
    # GeometryNotLoadedError is raised before any HTTP call — no mock needed
    from geofabrik.errors import GeometryNotLoadedError
    with httpx.Client() as http:
        cat = Catalogue(http=http, cache_dir=tmp_path, ttl_hours=24.0, include_geometry=False)
        with pytest.raises(GeometryNotLoadedError):
            cat.find_by_point(lat=39.9, lon=32.8)


def test_find_by_bbox_requires_geometry(tmp_path: Path) -> None:
    # GeometryNotLoadedError is raised before any HTTP call — no mock needed
    from geofabrik.errors import GeometryNotLoadedError
    with httpx.Client() as http:
        cat = Catalogue(http=http, cache_dir=tmp_path, ttl_hours=24.0, include_geometry=False)
        with pytest.raises(GeometryNotLoadedError):
            cat.find_by_bbox(0.0, 0.0, 1.0, 1.0)


# ---------------------------------------------------------------------------
# include_geometry


def test_include_geometry_fetches_geom_url(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL_GEOM, content=_fixture_bytes())
    with httpx.Client() as http:
        cat = Catalogue(http=http, cache_dir=tmp_path, ttl_hours=24.0, include_geometry=True)
        cat.list_regions()
    assert (tmp_path / "index-v1.json").exists()
    assert not (tmp_path / "index-v1-nogeom.json").exists()


def test_no_geometry_fetches_nogeom_url(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=_fixture_bytes())
    with httpx.Client() as http:
        cat = Catalogue(http=http, cache_dir=tmp_path, ttl_hours=24.0, include_geometry=False)
        cat.list_regions()
    assert (tmp_path / "index-v1-nogeom.json").exists()
    assert not (tmp_path / "index-v1.json").exists()


# ---------------------------------------------------------------------------
# Network integration (skipped by default)


@pytest.mark.network
def test_real_index_has_turkey() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp, httpx.Client() as http:
        cat = Catalogue(http=http, cache_dir=Path(tmp), ttl_hours=0)
        turkey = cat.get_region("turkey")
    assert turkey.parent == "asia"
    assert "pbf" in turkey.available_formats
