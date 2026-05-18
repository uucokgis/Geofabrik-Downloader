"""Unit tests for client.py."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

import geofabrik
from geofabrik.catalogue import INDEX_URL_NOGEOM
from geofabrik.errors import FormatNotAvailableError, RegionNotFoundError
from geofabrik.models import Region

FIXTURE = Path(__file__).parent / "fixtures" / "index.json"

PBF_URL = "https://download.geofabrik.de/asia/turkey-latest.osm.pbf"
MD5_URL = PBF_URL + ".md5"
DATA = b"fake pbf content"


def _md5_body(data: bytes = DATA) -> bytes:
    return f"{hashlib.md5(data).hexdigest()}  turkey-latest.osm.pbf\n".encode()


# ---------------------------------------------------------------------------
# Constructor & context manager


def test_client_is_importable() -> None:
    assert geofabrik.Client is not None


def test_client_context_manager(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=FIXTURE.read_bytes())
    with geofabrik.Client(cache_dir=tmp_path) as client:
        regions = client.list_regions()
    assert len(regions) == 3


def test_client_close_explicit(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=FIXTURE.read_bytes())
    client = geofabrik.Client(cache_dir=tmp_path)
    client.list_regions()
    client.close()  # should not raise


def test_client_custom_user_agent(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=FIXTURE.read_bytes())
    with geofabrik.Client(cache_dir=tmp_path, user_agent="my-app/1.0") as client:
        client.list_regions()
    request = httpx_mock.get_requests()[0]
    assert request.headers["user-agent"] == "my-app/1.0"


def test_client_default_user_agent_contains_version(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=FIXTURE.read_bytes())
    with geofabrik.Client(cache_dir=tmp_path) as client:
        client.list_regions()
    request = httpx_mock.get_requests()[0]
    assert geofabrik.__version__ in request.headers["user-agent"]


# ---------------------------------------------------------------------------
# Catalogue delegation


def test_client_list_regions(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=FIXTURE.read_bytes())
    with geofabrik.Client(cache_dir=tmp_path) as client:
        continents = client.list_regions()
    assert {r.id for r in continents} == {"africa", "asia", "europe"}


def test_client_get_region(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=FIXTURE.read_bytes())
    with geofabrik.Client(cache_dir=tmp_path) as client:
        turkey = client.get_region("turkey")
    assert turkey.name == "Turkey"


def test_client_get_region_not_found(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=FIXTURE.read_bytes())
    with geofabrik.Client(cache_dir=tmp_path) as client:
        with pytest.raises(RegionNotFoundError):
            client.get_region("nowhere")


def test_client_search_regions(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=FIXTURE.read_bytes())
    with geofabrik.Client(cache_dir=tmp_path) as client:
        results = client.search_regions("turkey")
    assert any(r.id == "turkey" for r in results)


def test_client_children_of(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=FIXTURE.read_bytes())
    with geofabrik.Client(cache_dir=tmp_path) as client:
        children = client.children_of("germany")
    assert {r.id for r in children} == {"nordrhein-westfalen", "bayern"}


# ---------------------------------------------------------------------------
# download_url


def test_download_url_returns_correct_url(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=FIXTURE.read_bytes())
    with geofabrik.Client(cache_dir=tmp_path) as client:
        url = client.download_url("turkey", "pbf")
    assert url == PBF_URL


def test_download_url_format_not_available(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=FIXTURE.read_bytes())
    with geofabrik.Client(cache_dir=tmp_path) as client:
        # kenya fixture only has pbf + poly
        with pytest.raises(FormatNotAvailableError) as exc_info:
            client.download_url("kenya", "shp")
    assert exc_info.value.region_id == "kenya"
    assert exc_info.value.format == "shp"


def test_download_url_accepts_region_object(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=FIXTURE.read_bytes())
    with geofabrik.Client(cache_dir=tmp_path) as client:
        turkey = client.get_region("turkey")
        url = client.download_url(turkey, "pbf")
    assert "turkey" in url


# ---------------------------------------------------------------------------
# download


def test_client_download(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=FIXTURE.read_bytes())
    httpx_mock.add_response(url=PBF_URL, content=DATA)
    httpx_mock.add_response(url=MD5_URL, content=_md5_body())
    with geofabrik.Client(cache_dir=tmp_path) as client:
        result = client.download("turkey", "pbf", dest=tmp_path / "data")
    assert Path(result.path).read_bytes() == DATA
    assert result.verified is True


def test_client_download_accepts_region_object(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=FIXTURE.read_bytes())
    httpx_mock.add_response(url=PBF_URL, content=DATA)
    httpx_mock.add_response(url=MD5_URL, content=_md5_body())
    with geofabrik.Client(cache_dir=tmp_path) as client:
        turkey = client.get_region("turkey")
        result = client.download(turkey, "pbf", dest=tmp_path / "data")
    assert result.url == PBF_URL


def test_client_download_no_verify(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=INDEX_URL_NOGEOM, content=FIXTURE.read_bytes())
    httpx_mock.add_response(url=PBF_URL, content=DATA)
    with geofabrik.Client(cache_dir=tmp_path) as client:
        result = client.download("turkey", "pbf", dest=tmp_path, verify=False)
    assert result.verified is False


# ---------------------------------------------------------------------------
# Network integration (skipped by default)


@pytest.mark.network
def test_real_client_list_and_download(tmp_path: Path) -> None:
    with geofabrik.Client(cache_dir=tmp_path) as client:
        turkey = client.get_region("turkey")
        assert "pbf" in turkey.available_formats
        url = client.download_url(turkey, "poly")
        assert url.endswith(".poly")
