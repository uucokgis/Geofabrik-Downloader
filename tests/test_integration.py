"""Integration tests — hit the real Geofabrik API.

Run with:
    pytest -m network

Skipped by default in CI. Requires internet access.
Small regions are chosen deliberately to keep download times short.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

import geofabrik


# ---------------------------------------------------------------------------
# Index & discovery


@pytest.mark.network
def test_real_index_has_many_regions(tmp_path: Path) -> None:
    with geofabrik.Client(cache_dir=tmp_path, index_ttl_hours=0) as client:
        all_regions = client.search_regions("")
    # Geofabrik currently lists 400+ regions
    assert len(all_regions) > 400


@pytest.mark.network
def test_real_get_turkey(tmp_path: Path) -> None:
    with geofabrik.Client(cache_dir=tmp_path, index_ttl_hours=0) as client:
        turkey = client.get_region("turkey")
    assert turkey.parent == "asia"
    assert turkey.iso3166_1_alpha2 == ("TR",)
    assert "pbf" in turkey.available_formats
    assert "shp" in turkey.available_formats


@pytest.mark.network
def test_real_children_of_europe_includes_germany(tmp_path: Path) -> None:
    with geofabrik.Client(cache_dir=tmp_path, index_ttl_hours=0) as client:
        children = client.children_of("europe")
    ids = {r.id for r in children}
    assert "germany" in ids
    assert "france" in ids


@pytest.mark.network
def test_real_search_regions_turkey(tmp_path: Path) -> None:
    with geofabrik.Client(cache_dir=tmp_path, index_ttl_hours=0) as client:
        results = client.search_regions("turkey")
    assert any(r.id == "turkey" for r in results)


# ---------------------------------------------------------------------------
# Downloads — small files only


@pytest.mark.network
def test_real_download_delaware_poly(tmp_path: Path) -> None:
    """Delaware .poly is ~1 KB — fast canary for the download pipeline."""
    with geofabrik.Client(cache_dir=tmp_path, index_ttl_hours=0) as client:
        result = client.download("delaware", "poly", dest=tmp_path / "data", verify=False)
    path = Path(result.path)
    assert path.exists()
    assert path.stat().st_size > 0
    # .poly files start with the region name on the first line
    first_line = path.read_text(errors="replace").splitlines()[0]
    assert len(first_line) > 0


@pytest.mark.network
def test_real_download_liechtenstein_pbf(tmp_path: Path) -> None:
    """Liechtenstein .pbf is ~3 MB — verifies MD5 end-to-end."""
    with geofabrik.Client(cache_dir=tmp_path, index_ttl_hours=0) as client:
        result = client.download("liechtenstein", "pbf", dest=tmp_path / "data", verify=True)
    path = Path(result.path)
    assert path.stat().st_size > 1_000_000  # sanity: at least 1 MB
    assert result.verified is True
    # PBF magic bytes: first 4 bytes are a length-prefixed blob header
    header = path.read_bytes()[:4]
    assert len(header) == 4
    (blob_len,) = struct.unpack(">I", header)
    assert blob_len > 0


@pytest.mark.network
def test_real_download_resume(tmp_path: Path) -> None:
    """Simulate a prior interrupted download by pre-seeding a .part file."""
    dest = tmp_path / "data"
    dest.mkdir()
    # Seed a non-empty but incomplete .part file
    part = dest / "liechtenstein.poly.part"
    part.write_bytes(b"x" * 10)  # intentionally corrupt partial
    with geofabrik.Client(cache_dir=tmp_path, index_ttl_hours=0) as client:
        result = client.download("liechtenstein", "poly", dest=dest, verify=False)
    # Either resumed (206) or server sent 200 and restarted — both are valid
    assert Path(result.path).exists()
    assert Path(result.path).stat().st_size > 0


# ---------------------------------------------------------------------------
# Spatial queries (require geometry index)


@pytest.mark.network
def test_real_find_by_point_los_angeles(tmp_path: Path) -> None:
    """(34.05, -118.24) is downtown Los Angeles — should land in a US/California region."""
    with geofabrik.Client(
        cache_dir=tmp_path, index_ttl_hours=0, include_geometry=True
    ) as client:
        results = client.find_by_point(lat=34.05, lon=-118.24)
    ids = [r.id for r in results]
    # Geofabrik has socal (Southern California) and us/california above it
    assert any("california" in rid or "socal" in rid for rid in ids), (
        f"Expected a California region, got: {ids}"
    )


@pytest.mark.network
def test_real_find_by_bbox_benelux(tmp_path: Path) -> None:
    """Bbox covering Belgium/Netherlands/Luxembourg."""
    with geofabrik.Client(
        cache_dir=tmp_path, index_ttl_hours=0, include_geometry=True
    ) as client:
        results = client.find_by_bbox(
            min_lon=2.5, min_lat=49.4, max_lon=7.1, max_lat=53.6
        )
    ids = {r.id for r in results}
    assert ids & {"belgium", "netherlands", "luxembourg"}


@pytest.mark.network
def test_real_find_by_point_returns_smallest_first(tmp_path: Path) -> None:
    """Sub-national region should come before its continent."""
    with geofabrik.Client(
        cache_dir=tmp_path, index_ttl_hours=0, include_geometry=True
    ) as client:
        results = client.find_by_point(lat=51.5, lon=-0.1)  # London
    ids = [r.id for r in results]
    assert len(ids) >= 2
    # The first result should be smaller than europe
    assert ids[0] != "europe"


# ---------------------------------------------------------------------------
# Shapefile extraction


@pytest.mark.network
def test_real_list_layers_delaware_shp(tmp_path: Path) -> None:
    """Download Delaware .shp.zip and verify expected layers are present."""
    with geofabrik.Client(cache_dir=tmp_path, index_ttl_hours=0) as client:
        result = client.download("delaware", "shp", dest=tmp_path / "data", verify=True)
        layers = client.list_layers(result.path)
    assert "roads" in layers
    assert "buildings" in layers


@pytest.mark.network
def test_real_extract_delaware_roads(tmp_path: Path) -> None:
    """Download Delaware .shp.zip and extract only the roads layer."""
    with geofabrik.Client(cache_dir=tmp_path, index_ttl_hours=0) as client:
        result = client.download("delaware", "shp", dest=tmp_path / "data", verify=True)
        paths = client.extract_layer(result.path, "roads", dest=tmp_path / "roads")
    exts = {p.suffix for p in paths}
    assert ".shp" in exts
    assert ".dbf" in exts
    # Verify the .shp file has the shapefile magic (file code 9994)
    shp_file = next(p for p in paths if p.suffix == ".shp")
    (file_code,) = struct.unpack(">I", shp_file.read_bytes()[:4])
    assert file_code == 9994


@pytest.mark.network
def test_real_extract_buildings_not_mixed_with_roads(tmp_path: Path) -> None:
    """Extracting buildings should not include roads files."""
    with geofabrik.Client(cache_dir=tmp_path, index_ttl_hours=0) as client:
        result = client.download("delaware", "shp", dest=tmp_path / "data", verify=False)
        paths = client.extract_layer(result.path, "buildings", dest=tmp_path / "buildings")
    for p in paths:
        assert "buildings" in p.name
        assert "roads" not in p.name
