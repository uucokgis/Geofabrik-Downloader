# Geofabrik Downloader

[![CI](https://github.com/uucokgis/Geofabrik-Downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/uucokgis/Geofabrik-Downloader/actions)
[![PyPI](https://img.shields.io/pypi/v/geofabrik-downloader.svg)](https://pypi.org/project/geofabrik-downloader/)
[![Python](https://img.shields.io/pypi/pyversions/geofabrik-downloader.svg)](https://pypi.org/project/geofabrik-downloader/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Typed: mypy strict](https://img.shields.io/badge/typed-mypy%20strict-blue.svg)](#)

A small, strictly-typed Python client **and CLI** for discovering and downloading OpenStreetMap extracts from [Geofabrik](https://download.geofabrik.de/). One runtime dependency (`httpx`), MIT-licensed, and deliberately scoped to *fetching* — pair it with `pyrosm`, `pyosmium`, or `geopandas` to parse what you download.

> **Status:** alpha (`0.1.x`). Public API may change before `1.0`.

## Why another one

Geofabrik publishes daily OSM extracts for every continent, country, and many sub-national regions. The existing Python options have problems:

- **[`pydriosm`](https://github.com/mikeqfu/pydriosm)** pulls in `pandas`, `numpy`, `shapely`, `bs4`, `pyhelpers`, `pyrcs`, and a PostgreSQL I/O layer just to download a file — and is GPLv3, which rules it out for many commercial codebases.
- **[`osmnx`](https://osmnx.readthedocs.io/)** talks to Overpass, not Geofabrik.
- **[`pyrosm`](https://pyrosm.readthedocs.io/)** parses `.osm.pbf` files but expects you to source them yourself.

`geofabrik-downloader` does one thing well: **list the catalogue and download files**, with checksum verification, resumable transfers, and a typed surface.

## Features

- **Structured catalogue** — region discovery via Geofabrik's [`index-v1.json`](https://download.geofabrik.de/index-v1.json); no HTML scraping.
- **Browse & search** — `list_regions`, `search_regions`, `children_of`, `get_region`.
- **Local index cache** — configurable TTL with an explicit `refresh_index()` escape hatch.
- **All published formats** — `.osm.pbf`, `.shp.zip`, `.gpkg.zip`, `.osm.bz2`, `.poly`, `.kml`.
- **MD5 verification** — verified against the published `.md5` sidecar by default.
- **Resumable downloads** — HTTP `Range` requests with a progress-callback hook.
- **Spatial lookup** — optional `find_by_point` / `find_by_bbox` when the geometry-bearing index is loaded.
- **Shapefile layer extraction** — `list_layers` and `extract_layer` pull a single layer out of `.shp.zip` without shapely or geopandas.
- **Full CLI** — `geofabrik list | search | children | info | url | download | find-point | find-bbox | layers | extract | refresh`, with Rich progress bars and a `--json` mode for scripting.
- **Stable script-friendly exit codes** — distinct codes for region-not-found, format-unavailable, checksum-mismatch, etc.
- **`py.typed`**, mypy-strict, no `Any` in the public API.

## Installation

```bash
pip install geofabrik-downloader            # library only
pip install "geofabrik-downloader[cli]"     # adds the geofabrik CLI (typer + rich)
```

Requires Python 3.10+.

## Quick start — Python API

```python
from geofabrik import Client

with Client() as client:
    # Top-level continents
    for region in client.list_regions(parent=None):
        print(region.id, region.name)

    # Inspect a region
    turkey = client.get_region("turkey")
    print(turkey.available_formats)  # e.g. frozenset({'pbf', 'shp', 'poly', 'kml'})

    # Download with MD5 verification (default)
    result = client.download(turkey, format="pbf", dest="./data")
    print(f"Saved {result.bytes_written} bytes to {result.path}")
```

### Searching and walking the hierarchy

```python
with Client() as client:
    matches = client.search_regions("bavaria")
    for region in client.children_of("germany"):
        print(region.id)
```

### Resumable downloads with progress

```python
def on_progress(downloaded: int, total: int | None) -> None:
    pct = f"{downloaded / total:.1%}" if total else f"{downloaded} B"
    print(f"\r{pct}", end="")

with Client() as client:
    client.download("monaco", format="pbf", dest="./data", progress=on_progress)
```

Interrupt and re-run the same command — the transfer resumes via HTTP `Range`.

### Spatial lookup

Spatial helpers require the full geometry-bearing index (≈50 MB):

```python
with Client(include_geometry=True) as client:
    hits = client.find_by_point(lat=41.0, lon=29.0)   # smallest containing region first
    print(hits[0].id)
```

### Extracting a single shapefile layer

```python
with Client() as client:
    zip_path = client.download("monaco", format="shp", dest="./data").path
    print(client.list_layers(zip_path))                 # e.g. [roads, buildings, ...]
    client.extract_layer(zip_path, "roads", "./out")    # writes only roads.* files
```

## Quick start — CLI

Install with the `[cli]` extras, then:

```bash
geofabrik list                                # continents
geofabrik list --parent europe                # children of a region
geofabrik search bavaria
geofabrik children germany
geofabrik info turkey                         # available formats, size hints, parent
geofabrik url turkey --format pbf             # print the download URL
geofabrik download turkey --format pbf -d ./data
geofabrik find-point 41.0 29.0
geofabrik find-bbox 28.5 40.8 29.5 41.3
geofabrik layers ./data/monaco-latest-free.shp.zip
geofabrik extract ./data/monaco-latest-free.shp.zip roads ./out
geofabrik refresh                             # force-refresh the cached index
```

Global flags: `--cache-dir`, `--index-ttl`, `--timeout`, `--user-agent`, `--json`, `--quiet`, `--verbose`.

Exit codes (stable contract for shell scripts):

| Code | Meaning |
|-----:|---------|
| 0    | success |
| 1    | generic error |
| 2    | region not found |
| 3    | format not available for that region |
| 4    | checksum mismatch |
| 5    | shapefile layer not found |
| 6    | spatial command used without the geometry-bearing index |

## Error handling

All package-specific exceptions derive from `GeofabrikError`:

```python
from geofabrik import (
    ChecksumMismatchError, FormatNotAvailableError, GeometryNotLoadedError,
    IndexFetchError, LayerNotFoundError, RegionNotFoundError,
)
```

## Configuration

`Client(...)` accepts:

- `cache_dir` — where the index JSON and partial downloads live (default: platform cache dir).
- `index_ttl_hours` — how long the cached index is considered fresh (default: 24).
- `timeout` — per-request timeout in seconds (default: 30).
- `user_agent` — custom UA; please set this for non-trivial usage out of courtesy to Geofabrik.
- `include_geometry` — load the geometry-bearing index for spatial lookup (`find_by_*`).

## What this package does *not* do

- Parse PBF or Shapefile content — use [`pyrosm`](https://pyrosm.readthedocs.io/), [`pyosmium`](https://osmcode.org/pyosmium/), or [`geopandas`](https://geopandas.org/).
- Write to a database — bring your own `sqlalchemy` / `psycopg`.
- Query Overpass / Nominatim — use [`osmnx`](https://osmnx.readthedocs.io/) or [`overpy`](https://github.com/DinoTools/python-overpy).
- Download from BBBike or other OSM mirrors.

These are deliberate scope choices, not roadmap items.

## Development

```bash
git clone https://github.com/uucokgis/Geofabrik-Downloader
cd Geofabrik-Downloader
python -m venv venv && source venv/bin/activate
pip install -e ".[cli,dev]"

pytest                          # unit tests (no network)
pytest -m network               # integration tests against the real Geofabrik API
ruff check . && mypy
```

Tests live under `tests/` and cover the cache, catalogue, client, downloader, extractor, the CLI, and an end-to-end integration suite. The `network` marker isolates tests that hit `download.geofabrik.de`.

## Contributing

See [IMPLEMENTATION.md](IMPLEMENTATION.md) for the technical design and open questions. Issues and PRs welcome.

## License

[MIT](LICENSE). OpenStreetMap data itself is © OpenStreetMap contributors, licensed under the [ODbL](https://opendatacommons.org/licenses/odbl/) by the OpenStreetMap Foundation.

## Acknowledgements

Built on the public catalogue maintained by [Geofabrik GmbH](https://www.geofabrik.de/). Problem statement inspired by [`pydriosm`](https://github.com/mikeqfu/pydriosm). If you use OSM data at scale, please consider [donating to OpenStreetMap](https://donate.openstreetmap.org/).
