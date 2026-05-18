"""File download with MD5 verification and HTTP Range resume support."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

import httpx

from .errors import ChecksumMismatchError, GeofabrikError
from .models import DownloadResult

_CHUNK = 65_536  # 64 KB read/write chunks


# ---------------------------------------------------------------------------
# MD5 helpers


def fetch_md5(http: httpx.Client, url: str) -> str:
    """Fetch ``<url>.md5`` and return the hex digest string.

    The sidecar format is ``<hash>  <filename>\\n``; we take the first field.
    """
    md5_url = url + ".md5"
    try:
        response = http.get(md5_url)
        response.raise_for_status()
        return response.text.split()[0]
    except httpx.HTTPError as exc:
        raise GeofabrikError(f"Failed to fetch MD5 sidecar {md5_url!r}: {exc}") from exc


def _file_md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify(path: Path, expected: str) -> None:
    actual = _file_md5(path)
    if actual != expected:
        raise ChecksumMismatchError(str(path), expected, actual)


# ---------------------------------------------------------------------------
# Content-Length helper


def _total_size(response: httpx.Response, offset: int) -> int | None:
    """Return expected total file size in bytes, or None if unknown."""
    raw = response.headers.get("content-length")
    if raw is None:
        return None
    try:
        # 206: content-length is partial length → add offset for total
        # 200: content-length is already total → offset is 0 here
        return offset + int(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Main entry point


def download(
    http: httpx.Client,
    url: str,
    dest: Path,
    verify: bool = True,
    resume: bool = True,
    overwrite: bool = False,
    progress: Callable[[int, int | None], None] | None = None,
) -> DownloadResult:
    """Download *url* into directory *dest*.

    Parameters
    ----------
    http:       An open ``httpx.Client`` — caller owns the lifecycle.
    url:        Direct download URL (from ``Region.urls``).
    dest:       Directory to write into; created if absent.
    verify:     Fetch the ``.md5`` sidecar and verify the checksum.
    resume:     Continue an interrupted download from a ``.part`` file.
    overwrite:  If the final file already exists, re-download it.
    progress:   Callback ``(bytes_downloaded, total_or_none)`` called per chunk.

    Returns
    -------
    DownloadResult with ``bytes_written=0`` when an existing file is reused.
    """
    filename = url.rsplit("/", 1)[-1]
    dest.mkdir(parents=True, exist_ok=True)
    final_path = dest / filename
    part_path = dest / (filename + ".part")

    # ── Already finished ────────────────────────────────────────────────────
    if final_path.exists() and not overwrite:
        verified = False
        if verify:
            _verify(final_path, fetch_md5(http, url))
            verified = True
        return DownloadResult(
            path=str(final_path),
            bytes_written=0,
            resumed=False,
            verified=verified,
            url=url,
        )

    # ── Determine resume offset ──────────────────────────────────────────────
    offset = part_path.stat().st_size if (resume and part_path.exists()) else 0
    headers = {"Range": f"bytes={offset}-"} if offset > 0 else {}

    bytes_written = 0
    resumed = False

    # ── Stream ──────────────────────────────────────────────────────────────
    try:
        with http.stream("GET", url, headers=headers) as response:

            # 416: Range Not Satisfiable → .part is already complete
            if response.status_code == 416:
                part_path.replace(final_path)
                if verify:
                    _verify(final_path, fetch_md5(http, url))
                return DownloadResult(
                    path=str(final_path),
                    bytes_written=0,
                    resumed=True,
                    verified=verify,
                    url=url,
                )

            response.raise_for_status()

            if response.status_code == 206:
                # Server honoured the Range header
                resumed = True
                write_mode = "ab"
            else:
                # 200: server ignored Range or fresh request — start over
                offset = 0
                part_path.unlink(missing_ok=True)
                write_mode = "wb"

            total = _total_size(response, offset)

            with part_path.open(write_mode) as fh:
                for chunk in response.iter_bytes(chunk_size=_CHUNK):
                    fh.write(chunk)
                    bytes_written += len(chunk)
                    if progress:
                        progress(offset + bytes_written, total)

    except httpx.HTTPError as exc:
        raise GeofabrikError(f"Download failed for {url!r}: {exc}") from exc

    # ── Finalise ─────────────────────────────────────────────────────────────
    part_path.replace(final_path)

    if verify:
        _verify(final_path, fetch_md5(http, url))

    return DownloadResult(
        path=str(final_path),
        bytes_written=bytes_written,
        resumed=resumed,
        verified=verify,
        url=url,
    )
