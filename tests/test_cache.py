"""Unit tests for cache.py — no network required."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from geofabrik import cache


def test_default_cache_dir_returns_path() -> None:
    assert isinstance(cache.default_cache_dir(), Path)


def test_default_cache_dir_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    result = cache.default_cache_dir()
    assert result == Path.home() / "Library" / "Caches" / "geofabrik-downloader"


def test_default_cache_dir_linux_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CACHE_HOME", "/tmp/xdg")
    result = cache.default_cache_dir()
    assert result == Path("/tmp/xdg") / "geofabrik-downloader"


def test_default_cache_dir_linux_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    result = cache.default_cache_dir()
    assert result == Path.home() / ".cache" / "geofabrik-downloader"


def test_is_fresh_missing_file(tmp_path: Path) -> None:
    assert cache.is_fresh(tmp_path / "no-such-file.json", ttl_hours=24) is False


def test_is_fresh_new_file(tmp_path: Path) -> None:
    f = tmp_path / "index.json"
    f.write_bytes(b"{}")
    assert cache.is_fresh(f, ttl_hours=24) is True


def test_is_fresh_expired_file(tmp_path: Path) -> None:
    f = tmp_path / "index.json"
    f.write_bytes(b"{}")
    # backdate mtime by 2 hours
    old_mtime = time.time() - 7201
    import os
    os.utime(f, (old_mtime, old_mtime))
    assert cache.is_fresh(f, ttl_hours=2) is False


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "index.json"
    data = b'{"type": "FeatureCollection"}'
    cache.write_bytes(target, data)
    assert cache.read_bytes(target) == data


def test_write_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c" / "index.json"
    cache.write_bytes(target, b"x")
    assert target.exists()


def test_write_no_tmp_file_left_behind(tmp_path: Path) -> None:
    target = tmp_path / "index.json"
    cache.write_bytes(target, b"data")
    tmp = target.with_suffix(target.suffix + ".tmp")
    assert not tmp.exists()
