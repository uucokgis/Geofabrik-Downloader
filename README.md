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
- Download `.osm.pbf`, `.shp.zip`, `.gpkg.zip`, `.osm.bz2`, `.poly`, `.kml`
- MD5 checksum verification using the published `.md5` sidecars
- Resumable downloads via HTTP `Range` requests
- Local cache for the index with a configurable TTL
- Optional CLI (`pip install "geofabrik-downloader[cli]"`)
- Type hints throughout, MIT-licensed, single runtime dependency (`httpx`)

## Installation

```bash
pip install geofabrik-downloader
```

With the CLI extras:

```bash
pip install "geofabrik-downloader[cli]"
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
    print(turkey.available_formats)  # frozenset of available format strings e.g. {'pbf', 'shp', ...}

    # Download with MD5 verification (default)
    result = client.download(turkey, format="pbf", dest="./data")
    print(f"Saved {result.bytes_written} bytes to {result.path}")
```

## CLI

```bash
geofabrik list --parent europe
geofabrik info germany
geofabrik download turkey --format pbf --dest ./data
```

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
