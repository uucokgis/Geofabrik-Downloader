"""Unit tests for extract.py — uses in-memory zip files, no network."""

from __future__ import annotations

import zipfile
import io
from pathlib import Path

import pytest

from geofabrik.extract import extract_layer, list_layers
from geofabrik.errors import LayerNotFoundError


def _make_shp_zip(layers: list[str], tmp_path: Path) -> Path:
    """Create a fake .shp.zip containing empty sidecar files for each layer prefix."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for prefix in layers:
            for ext in (".shp", ".dbf", ".shx", ".prj"):
                zf.writestr(f"{prefix}{ext}", b"")
    zip_path = tmp_path / "test.shp.zip"
    zip_path.write_bytes(buf.getvalue())
    return zip_path


# ---------------------------------------------------------------------------
# list_layers


def test_list_layers_detects_roads(tmp_path: Path) -> None:
    z = _make_shp_zip(["gis_osm_roads_free_1"], tmp_path)
    assert list_layers(z) == ["roads"]


def test_list_layers_multiple(tmp_path: Path) -> None:
    z = _make_shp_zip(
        ["gis_osm_roads_free_1", "gis_osm_buildings_a_free_1", "gis_osm_pois_free_1"],
        tmp_path,
    )
    assert set(list_layers(z)) == {"roads", "buildings", "pois"}


def test_list_layers_sorted(tmp_path: Path) -> None:
    z = _make_shp_zip(
        ["gis_osm_waterways_free_1", "gis_osm_roads_free_1", "gis_osm_pois_free_1"],
        tmp_path,
    )
    result = list_layers(z)
    assert result == sorted(result)


def test_list_layers_unknown_prefix_ignored(tmp_path: Path) -> None:
    z = _make_shp_zip(["gis_osm_roads_free_1", "gis_osm_unknown_layer_x"], tmp_path)
    assert list_layers(z) == ["roads"]


def test_list_layers_empty_zip(tmp_path: Path) -> None:
    z = _make_shp_zip([], tmp_path)
    assert list_layers(z) == []


# ---------------------------------------------------------------------------
# extract_layer


def test_extract_layer_writes_files(tmp_path: Path) -> None:
    z = _make_shp_zip(["gis_osm_roads_free_1"], tmp_path)
    dest = tmp_path / "out"
    paths = extract_layer(z, "roads", dest)
    assert len(paths) == 4
    exts = {p.suffix for p in paths}
    assert exts == {".shp", ".dbf", ".shx", ".prj"}


def test_extract_layer_creates_dest_dir(tmp_path: Path) -> None:
    z = _make_shp_zip(["gis_osm_roads_free_1"], tmp_path)
    dest = tmp_path / "deep" / "nested"
    extract_layer(z, "roads", dest)
    assert dest.is_dir()


def test_extract_layer_files_readable(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("gis_osm_buildings_a_free_1.shp", b"FAKE_SHP_HEADER")
        zf.writestr("gis_osm_buildings_a_free_1.dbf", b"FAKE_DBF")
        zf.writestr("gis_osm_buildings_a_free_1.shx", b"FAKE_SHX")
        zf.writestr("gis_osm_buildings_a_free_1.prj", b"FAKE_PRJ")
    z = tmp_path / "test.shp.zip"
    z.write_bytes(buf.getvalue())

    paths = extract_layer(z, "buildings", tmp_path / "out")
    shp = next(p for p in paths if p.suffix == ".shp")
    assert shp.read_bytes() == b"FAKE_SHP_HEADER"


def test_extract_layer_not_found_raises(tmp_path: Path) -> None:
    z = _make_shp_zip(["gis_osm_roads_free_1"], tmp_path)
    with pytest.raises(LayerNotFoundError) as exc_info:
        extract_layer(z, "buildings", tmp_path / "out")
    assert exc_info.value.layer == "buildings"
    assert "roads" in exc_info.value.available


def test_extract_layer_not_found_empty_zip(tmp_path: Path) -> None:
    z = _make_shp_zip([], tmp_path)
    with pytest.raises(LayerNotFoundError) as exc_info:
        extract_layer(z, "pois", tmp_path / "out")
    assert exc_info.value.available == []


def test_extract_only_target_layer(tmp_path: Path) -> None:
    """Extracting roads should not write buildings files."""
    z = _make_shp_zip(
        ["gis_osm_roads_free_1", "gis_osm_buildings_a_free_1"], tmp_path
    )
    dest = tmp_path / "out"
    paths = extract_layer(z, "roads", dest)
    for p in paths:
        assert "roads" in p.name
