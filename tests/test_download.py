"""Unit tests for download.py — all HTTP mocked via pytest-httpx."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from geofabrik.download import download, fetch_md5
from geofabrik.errors import ChecksumMismatchError, GeofabrikError

URL = "https://download.geofabrik.de/asia/turkey-latest.osm.pbf"
MD5_URL = URL + ".md5"
DATA = b"fake pbf binary content"
DATA_MD5 = hashlib.md5(DATA).hexdigest()


def _md5_body(data: bytes = DATA) -> bytes:
    return f"{hashlib.md5(data).hexdigest()}  turkey-latest.osm.pbf\n".encode()


# ---------------------------------------------------------------------------
# fetch_md5


def test_fetch_md5_returns_hash(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=MD5_URL, content=_md5_body())
    with httpx.Client() as http:
        assert fetch_md5(http, URL) == DATA_MD5


def test_fetch_md5_http_error_raises_geofabrik_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=MD5_URL, status_code=404)
    with httpx.Client() as http:
        with pytest.raises(GeofabrikError):
            fetch_md5(http, URL)


# ---------------------------------------------------------------------------
# Fresh download (200)


def test_download_writes_file(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=URL, content=DATA)
    httpx_mock.add_response(url=MD5_URL, content=_md5_body())
    with httpx.Client() as http:
        result = download(http, URL, tmp_path)
    assert Path(result.path).read_bytes() == DATA
    assert result.bytes_written == len(DATA)
    assert result.resumed is False
    assert result.verified is True


def test_download_creates_dest_dir(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    dest = tmp_path / "deep" / "path"
    httpx_mock.add_response(url=URL, content=DATA)
    httpx_mock.add_response(url=MD5_URL, content=_md5_body())
    with httpx.Client() as http:
        result = download(http, URL, dest)
    assert Path(result.path).exists()


def test_download_no_part_file_left_behind(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=URL, content=DATA)
    httpx_mock.add_response(url=MD5_URL, content=_md5_body())
    with httpx.Client() as http:
        download(http, URL, tmp_path)
    assert not list(tmp_path.glob("*.part"))


def test_download_verify_false_skips_md5(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=URL, content=DATA)
    with httpx.Client() as http:
        result = download(http, URL, tmp_path, verify=False)
    assert result.verified is False
    # If MD5 was requested it would fail because no mock is registered for it


def test_download_checksum_mismatch_raises(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=URL, content=DATA)
    httpx_mock.add_response(url=MD5_URL, content=b"deadbeef  turkey-latest.osm.pbf\n")
    with httpx.Client() as http:
        with pytest.raises(ChecksumMismatchError) as exc_info:
            download(http, URL, tmp_path)
    assert exc_info.value.expected == "deadbeef"
    assert exc_info.value.actual == DATA_MD5


def test_download_http_error_raises_geofabrik_error(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=URL, status_code=503)
    with httpx.Client() as http:
        with pytest.raises(GeofabrikError):
            download(http, URL, tmp_path)


# ---------------------------------------------------------------------------
# Existing file


def test_download_existing_file_not_overwritten(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    final = tmp_path / "turkey-latest.osm.pbf"
    final.write_bytes(DATA)
    httpx_mock.add_response(url=MD5_URL, content=_md5_body())
    with httpx.Client() as http:
        result = download(http, URL, tmp_path, overwrite=False)
    assert result.bytes_written == 0
    assert result.verified is True


def test_download_existing_file_overwritten(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    final = tmp_path / "turkey-latest.osm.pbf"
    final.write_bytes(b"old content")
    new_data = b"brand new content"
    httpx_mock.add_response(url=URL, content=new_data)
    httpx_mock.add_response(url=MD5_URL, content=_md5_body(new_data))
    with httpx.Client() as http:
        result = download(http, URL, tmp_path, overwrite=True)
    assert final.read_bytes() == new_data
    assert result.bytes_written == len(new_data)


# ---------------------------------------------------------------------------
# Resume (206 Partial Content)


def test_download_resumes_partial_file(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    partial = DATA[: len(DATA) // 2]
    remainder = DATA[len(DATA) // 2 :]

    part_file = tmp_path / "turkey-latest.osm.pbf.part"
    part_file.write_bytes(partial)

    httpx_mock.add_response(
        url=URL,
        status_code=206,
        content=remainder,
        headers={"Content-Range": f"bytes {len(partial)}-{len(DATA)-1}/{len(DATA)}"},
    )
    httpx_mock.add_response(url=MD5_URL, content=_md5_body())

    with httpx.Client() as http:
        result = download(http, URL, tmp_path)

    assert result.resumed is True
    assert result.bytes_written == len(remainder)
    assert (tmp_path / "turkey-latest.osm.pbf").read_bytes() == DATA


def test_download_server_ignores_range_restarts(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    part_file = tmp_path / "turkey-latest.osm.pbf.part"
    part_file.write_bytes(b"stale partial")

    # Server returns 200 ignoring Range header → full content
    httpx_mock.add_response(url=URL, status_code=200, content=DATA)
    httpx_mock.add_response(url=MD5_URL, content=_md5_body())

    with httpx.Client() as http:
        result = download(http, URL, tmp_path)

    assert result.resumed is False
    assert result.bytes_written == len(DATA)
    assert (tmp_path / "turkey-latest.osm.pbf").read_bytes() == DATA


def test_download_416_renames_part_to_final(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    part_file = tmp_path / "turkey-latest.osm.pbf.part"
    part_file.write_bytes(DATA)  # already complete

    httpx_mock.add_response(url=URL, status_code=416)
    httpx_mock.add_response(url=MD5_URL, content=_md5_body())

    with httpx.Client() as http:
        result = download(http, URL, tmp_path)

    assert result.resumed is True
    assert result.bytes_written == 0
    assert (tmp_path / "turkey-latest.osm.pbf").read_bytes() == DATA
    assert not part_file.exists()


def test_download_resume_false_ignores_part_file(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    part_file = tmp_path / "turkey-latest.osm.pbf.part"
    part_file.write_bytes(b"irrelevant partial")

    httpx_mock.add_response(url=URL, content=DATA)
    httpx_mock.add_response(url=MD5_URL, content=_md5_body())

    with httpx.Client() as http:
        result = download(http, URL, tmp_path, resume=False)

    assert result.resumed is False
    assert (tmp_path / "turkey-latest.osm.pbf").read_bytes() == DATA


# ---------------------------------------------------------------------------
# Progress callback


def test_download_progress_callback_called(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(
        url=URL,
        content=DATA,
        headers={"Content-Length": str(len(DATA))},
    )
    httpx_mock.add_response(url=MD5_URL, content=_md5_body())

    calls: list[tuple[int, int | None]] = []
    with httpx.Client() as http:
        download(http, URL, tmp_path, progress=lambda done, total: calls.append((done, total)))

    assert len(calls) > 0
    assert calls[-1][0] == len(DATA)
