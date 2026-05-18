# Implementation Guide

This document describes the technical design of `geofabrik-downloader`. Read it **before** writing code.

The repository is currently a scaffold: data models (`models.py`) and the exception hierarchy (`errors.py`) are concrete; everything else is yet to be written.

---

## Scope

**In scope**

- Region discovery (listing, search, parent/child traversal)
- File download with checksum verification, resume support, and a local index cache
- Per-region format introspection
- A thin CLI wrapper

**Out of scope** — do not add without an explicit issue:

- Parsing PBF / Shapefile / GeoPackage content
- Database I/O (PostgreSQL, SQLite, etc.)
- BBBike or other OSM mirrors
- OSM Overpass / Nominatim API access

---

## Data sources

Geofabrik exposes three machine-readable artifacts. Use them; do **not** scrape HTML.

### 1. `index-v1.json` — the master catalogue

URL: <https://download.geofabrik.de/index-v1.json>

GeoJSON `FeatureCollection`. Each feature is one region:

```json
{
  "type": "Feature",
  "properties": {
    "id": "turkey",
    "parent": "asia",
    "name": "Turkey",
    "iso3166-1:alpha2": ["TR"],
    "urls": {
      "pbf": "https://download.geofabrik.de/asia/turkey-latest.osm.pbf",
      "bz2": "https://download.geofabrik.de/asia/turkey-latest.osm.bz2",
      "shp": "https://download.geofabrik.de/asia/turkey-latest-free.shp.zip",
      "pbf-internal": "...",
      "history": "...",
      "taginfo": "...",
      "updates": "..."
    }
  },
  "geometry": { "type": "MultiPolygon", "coordinates": [...] }
}
```

Geometry-free variant: <https://download.geofabrik.de/index-v1-nogeom.json> — prefer it for the default index cache (smaller, faster, the geometry is rarely needed at discovery time).

Schema notes:

- `properties.parent` is `null` for continent-level regions.
- The `urls` dict varies per region — small or non-standard regions may not offer every format.
- `iso3166-1:alpha2` is a list (some regions span multiple ISO codes, e.g. `israel-and-palestine`).
- `iso3166-2` may also appear for sub-national regions.

### 2. MD5 sidecar files

Every downloadable file has a `<file>.md5` sibling, e.g. `turkey-latest.osm.pbf.md5`:

```
8a7b3e4d5c6f...  turkey-latest.osm.pbf
```

Two whitespace-separated fields; take the first as the hash.

### 3. `.poly` boundary files

Region boundaries in the [Osmosis polygon filter format](https://wiki.openstreetmap.org/wiki/Osmosis/Polygon_Filter_File_Format), linked from `urls.poly` when available.

---

## Module layout

```
src/geofabrik/
├── __init__.py        # Public re-exports — done
├── client.py          # Client class — TODO
├── catalogue.py       # Index fetching, parsing, region tree — TODO
├── models.py          # Region, DownloadResult, Format — done
├── download.py        # File download, MD5, resume — TODO
├── cache.py           # Index cache path + freshness logic — TODO
├── cli.py             # Typer-based CLI (optional dep) — TODO
└── errors.py          # Exception hierarchy — done
```

---

## Public API (target shape)

```python
from geofabrik import Client, Region

client = Client(
    cache_dir: Path | str | None = None,    # default: per-OS user cache dir
    index_ttl_hours: float = 24.0,
    timeout: float = 30.0,
    user_agent: str | None = None,          # default: "geofabrik-downloader/<version>"
)

# --- Catalogue ---
client.list_regions(parent: str | None = "__top__") -> list[Region]
client.get_region(region_id: str) -> Region              # raises RegionNotFoundError
client.search_regions(query: str) -> list[Region]         # case-insensitive substring on id + name
client.children_of(region_id: str) -> list[Region]
client.refresh_index() -> None                            # force re-fetch

# --- Downloads ---
client.download_url(region: Region | str, format: Format) -> str
client.download(
    region: Region | str,
    format: Format,
    dest: Path | str = ".",
    verify: bool = True,
    resume: bool = True,
    overwrite: bool = False,
    progress: Callable[[int, int | None], None] | None = None,
) -> DownloadResult
```

`Client` is a context manager (`__enter__` / `__exit__`) that owns an `httpx.Client`.

---

## Key design decisions

### Sync first

Build the synchronous API on `httpx.Client`. An `AsyncClient` mirror can come later in a separate module. Do **not** try to support both shapes in `Client` itself — the duplication tax is real, and one-shot scripts (the common case) do not need async.

### Cache the index, not the data

Cache `index-v1-nogeom.json` locally with a TTL. Data files are written wherever the caller specifies — the library never auto-caches multi-GB PBFs.

Default cache location:

- Linux: `$XDG_CACHE_HOME/geofabrik-downloader` (fallback `~/.cache/geofabrik-downloader`)
- macOS: `~/Library/Caches/geofabrik-downloader`
- Windows: `%LOCALAPPDATA%\geofabrik-downloader\Cache`

Hand-roll this in `cache.py`; do not introduce `platformdirs` for one path resolution.

### Checksum-as-default, opt-out

`verify=True` is the default. Geofabrik publishes MD5 for every file; refusing to verify is the wrong default. Document that this costs one extra HTTP request to fetch the `.md5` sidecar.

### Resume via Range requests

If `dest/<file>.part` exists, send `Range: bytes=<size>-` and handle:

- `206 Partial Content` → append to `.part`
- `200 OK` → server ignored Range, restart from scratch
- `416 Range Not Satisfiable` → file is already complete; verify checksum and rename
- Any other status → wrap in `GeofabrikError` and surface

On success, atomically rename `.part` to the final filename.

### Format aliases

Public API uses short forms: `pbf`, `shp`, `gpkg`, `bz2`, `poly`, `kml`. `models.FORMAT_TO_INDEX_KEY` maps them to the actual `urls.<key>` field. If `urls` does not contain the requested key, raise `FormatNotAvailableError`.

### No HTML scraping

If you find yourself reaching for `bs4`, stop — `index-v1.json` already has it. The only known scenario the JSON does not cover is per-day historical snapshots, which is out of scope.

### Geometry stays as dict

`Region.geometry` is the raw GeoJSON dict (or `None`). Do **not** return shapely geometries — keeping `shapely` out of the runtime dependency tree is a defining feature. Document the one-liner conversion in the README:

```python
from shapely.geometry import shape
poly = shape(region.geometry)
```

---

## Dependencies

**Runtime — single dependency:**

- `httpx >= 0.27` — Range support, HTTP/2, clean sync/async API

**Optional `[cli]`:**

- `typer >= 0.12`
- `rich >= 13.7` (table rendering)

**Dev:**

- `pytest >= 8`
- `pytest-httpx >= 0.30` (mock HTTP responses)
- `ruff >= 0.6`
- `mypy >= 1.11`

**Forbidden** without a written, reviewed justification:

- `pandas`, `numpy`, `shapely`, `geopandas`, `pyproj` — push these onto the user
- `requests` — `httpx` covers it
- `beautifulsoup4`, `lxml` — no HTML to parse
- `pydantic` — dataclasses are enough for this surface

---

## Error handling

Defined in `errors.py`:

| Exception | Raised when |
|---|---|
| `GeofabrikError` | Base class — catch this for anything from the package |
| `IndexFetchError` | Index cannot be fetched, parsed, or has unexpected shape |
| `RegionNotFoundError` | `region_id` not present in the index |
| `FormatNotAvailableError` | Region exists, format does not |
| `ChecksumMismatchError` | Downloaded file's MD5 disagrees with the sidecar |

Never let `httpx` exceptions escape the package — wrap them in `GeofabrikError` (or a subclass) with context.

---

## Testing strategy

- **Unit tests** use `pytest-httpx` to mock the network. Place a frozen snapshot of `index-v1-nogeom.json` (trimmed to ~20 regions covering the interesting shapes — continent, country, multi-ISO region, sub-national) at `tests/fixtures/index.json`.
- **One integration test** marked `@pytest.mark.network` hits the real Geofabrik index. Skipped by default; run with `pytest -m network`.
- **Coverage target:** 90% for `catalogue.py` and `download.py`. Lower is acceptable for `cli.py`.

---

## Versioning and release

- SemVer starting at `0.1.0` once the public API works end-to-end.
- Stay in `0.x` until two or three external users have given feedback.
- Tag releases as `v0.1.0`, `v0.1.1`, etc.
- A GitHub Actions workflow should build and publish to PyPI on tag push (set this up after the first manual release).
- Version lives in `src/geofabrik/__init__.py` and is read dynamically by `hatchling` (see `pyproject.toml`).

---

## Open questions for the next agent

1. **CLI in 0.1 or 0.2?** Shipping the library alone in `0.1.0` is faster and keeps the initial review small. CLI in `0.2.0`.
2. **Progress callback shape.** `Callable[[int, int | None], None]` (bytes_downloaded, total_or_none) is simple. A `rich.progress.Progress` integration is nicer for the CLI but couples to the optional extras — keep it in `cli.py`, not `download.py`.
3. **Async client.** Probably not worth it before `1.0`. Most users are one-shot scripts.
4. **Region tree helpers.** `region.descendants()` / `region.ancestors()` are convenient but need a reference back to the index, which forces an awkward dependency from `models.py` to `Client`. Prefer free functions on `Client` (`client.descendants_of(id)`, `client.ancestors_of(id)`).
5. **Bulk download.** A common ask, but it raises concurrency and rate-limiting questions. Defer to `0.3.0` with an explicit design discussion.

---

## Reference

- Geofabrik download server: <https://download.geofabrik.de/>
- Index endpoint: <https://download.geofabrik.de/index-v1.json>
- No-geometry variant: <https://download.geofabrik.de/index-v1-nogeom.json>
- `pydriosm` (prior art, GPLv3): <https://github.com/mikeqfu/pydriosm>
- HTTP Range: [RFC 7233](https://datatracker.ietf.org/doc/html/rfc7233)
- Osmosis polygon filter format: <https://wiki.openstreetmap.org/wiki/Osmosis/Polygon_Filter_File_Format>
