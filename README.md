# geofabrik-downloader

A lightweight, dependency-light Python client for discovering and downloading OpenStreetMap extracts from [Geofabrik](https://download.geofabrik.de/).

> **Status:** alpha. The public API may change before `1.0`.

## Why this exists

Geofabrik publishes daily OpenStreetMap extracts for every continent, country, and many sub-national regions. The existing Python tooling around it is either:

- **Bloated** — [`pydriosm`](https://github.com/mikeqfu/pydriosm) is the closest equivalent, but it pulls in `pandas`, `numpy`, `shapely`, `bs4`, `pyhelpers`, `pyrcs`, and a PostgreSQL I/O layer just to download a file. It is also GPLv3-licensed, which blocks adoption in many commercial codebases.
- **Indirect** — `osmnx` queries the Overpass API; `pyrosm` reads PBF files but expects you to source them yourself.

`geofabrik-downloader` does one thing: **list available regions and download their files.** Pair it with `pyrosm`, `pyosmium`, or `geopandas` for parsing.

## Features

- Region discovery via Geofabrik's structured [`index-v1.json`](https://download.geofabrik.de/index-v1.json) — no HTML scraping
- Browse, search, and walk the region hierarchy (`list_regions`, `search_regions`, `children_of`, `get_region`)
- Locally cached index with a configurable TTL and an explicit `refresh_index()`
- Download `.osm.pbf`, `.shp.zip`, `.gpkg.zip`, `.osm.bz2`, `.poly`, `.kml`
- MD5 checksum verification using the published `.md5` sidecars
- Resumable downloads via HTTP `Range` requests, with a progress callback hook
- Optional spatial lookup: `find_by_point` / `find_by_bbox` when the geometry-bearing index is loaded
- Selective shapefile-layer extraction from `.shp.zip` (`list_layers`, `extract_layer`) — no shapely/geopandas required
- Type hints throughout, MIT-licensed, single runtime dependency (`httpx`)

## Installation

```bash
pip install geofabrik-downloader
```

## Quick start

```python
from geofabrik import Client

with Client() as client:
    # List top-level continents
    for region in client.list_regions(parent=None):
        print(region.id, region.name)

    # Inspect a specific region
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

### Spatial lookup

Spatial helpers require the full index (≈50 MB) to be loaded:

```python
with Client(include_geometry=True) as client:
    # Smallest region containing the point first
    hits = client.find_by_point(lat=41.0, lon=29.0)
    print(hits[0].id)
```

### Extracting a single shapefile layer

```python
with Client() as client:
    zip_path = client.download("monaco", format="shp", dest="./data").path
    print(client.list_layers(zip_path))               # which layers are present
    client.extract_layer(zip_path, "roads", "./out")  # only the roads layer
```

## CLI

A `geofabrik` console-script entry point is declared in `pyproject.toml` but the CLI
module is not implemented yet. The `cli` extras (`typer`, `rich`) are reserved for it.
Until then, use the Python API above. Tracking the design in [IMPLEMENTATION.md](IMPLEMENTATION.md).

## What this package does *not* do

- Parse PBF or Shapefile content — use [`pyrosm`](https://pyrosm.readthedocs.io/), [`pyosmium`](https://osmcode.org/pyosmium/), or [`geopandas`](https://geopandas.org/)
- Write to a database — roll your own with `sqlalchemy` or `psycopg`
- Query the OSM Overpass / Nominatim APIs — use [`osmnx`](https://osmnx.readthedocs.io/) or [`overpy`](https://github.com/DinoTools/python-overpy)
- Download from BBBike or other OSM mirrors

These are deliberate scope choices, not roadmap items.

## Contributing

See [IMPLEMENTATION.md](IMPLEMENTATION.md) for the technical design and the current open questions. Issues and pull requests are welcome.

## License

[MIT](LICENSE). OpenStreetMap data itself is licensed under the [ODbL](https://opendatacommons.org/licenses/odbl/) by the OpenStreetMap Foundation.

## Acknowledgements

Inspired by [`pydriosm`](https://github.com/mikeqfu/pydriosm). This package borrows the problem statement and nothing else.
