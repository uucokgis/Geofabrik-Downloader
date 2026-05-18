"""Typer + Rich CLI for geofabrik-downloader.

Installed as the ``geofabrik`` console script (see ``pyproject.toml``).
Requires the optional ``[cli]`` extras (``typer``, ``rich``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import click
import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from . import extract as _ex
from .client import Client
from .errors import (
    ChecksumMismatchError,
    FormatNotAvailableError,
    GeofabrikError,
    GeometryNotLoadedError,
    LayerNotFoundError,
    RegionNotFoundError,
)
from .models import LAYER_TO_PREFIX, Format, Region, ShpLayer

# Exit codes — stable contract for scripts.
EXIT_GENERIC = 1
EXIT_REGION_NOT_FOUND = 2
EXIT_FORMAT_NOT_AVAILABLE = 3
EXIT_CHECKSUM_MISMATCH = 4
EXIT_LAYER_NOT_FOUND = 5
EXIT_GEOMETRY_NOT_LOADED = 6


app = typer.Typer(
    name="geofabrik",
    help="List, search, and download OpenStreetMap extracts from Geofabrik.",
    no_args_is_help=True,
    add_completion=False,
)
out = Console()
err = Console(stderr=True)


# ── Shared CLI state ─────────────────────────────────────────────────────────


@dataclass
class _CliState:
    cache_dir: Path | None = None
    index_ttl: float = 24.0
    timeout: float = 30.0
    user_agent: str | None = None
    json_output: bool = False
    quiet: bool = False
    verbose: bool = False

    def open_client(self, include_geometry: bool = False) -> Client:
        return Client(
            cache_dir=self.cache_dir,
            index_ttl_hours=self.index_ttl,
            timeout=self.timeout,
            user_agent=self.user_agent,
            include_geometry=include_geometry,
        )


def _state(ctx: typer.Context) -> _CliState:
    return ctx.ensure_object(_CliState)


# ── Root callback ────────────────────────────────────────────────────────────


@app.callback()
def _root(
    ctx: typer.Context,
    cache_dir: Annotated[
        Path | None,
        typer.Option("--cache-dir", help="Override the index cache directory."),
    ] = None,
    index_ttl: Annotated[
        float, typer.Option("--index-ttl", help="Index cache TTL in hours.")
    ] = 24.0,
    timeout: Annotated[
        float, typer.Option("--timeout", help="HTTP timeout in seconds.")
    ] = 30.0,
    user_agent: Annotated[
        str | None, typer.Option("--user-agent", help="Override the HTTP User-Agent.")
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON instead of tables.")
    ] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Suppress progress output.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print tracebacks on errors.")
    ] = False,
) -> None:
    ctx.obj = _CliState(
        cache_dir=cache_dir,
        index_ttl=index_ttl,
        timeout=timeout,
        user_agent=user_agent,
        json_output=json_output,
        quiet=quiet,
        verbose=verbose,
    )


# ── Rendering helpers ────────────────────────────────────────────────────────


def _region_to_dict(r: Region, *, include_geometry: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": r.id,
        "name": r.name,
        "parent": r.parent,
        "iso3166_1_alpha2": list(r.iso3166_1_alpha2),
        "iso3166_2": list(r.iso3166_2),
        "urls": dict(r.urls),
        "available_formats": sorted(r.available_formats),
    }
    if include_geometry:
        d["geometry"] = r.geometry
    return d


def _print_regions(state: _CliState, regions: list[Region]) -> None:
    if state.json_output:
        out.print_json(data=[_region_to_dict(r) for r in regions])
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id")
    table.add_column("name")
    table.add_column("parent")
    table.add_column("formats")
    for r in regions:
        table.add_row(
            r.id,
            r.name,
            r.parent or "-",
            ",".join(sorted(r.available_formats)) or "-",
        )
    out.print(table)


def _print_region_detail(state: _CliState, region: Region) -> None:
    if state.json_output:
        out.print_json(data=_region_to_dict(region))
        return
    table = Table(show_header=False, box=None)
    table.add_column("field", style="bold")
    table.add_column("value")
    table.add_row("id", region.id)
    table.add_row("name", region.name)
    table.add_row("parent", region.parent or "-")
    if region.iso3166_1_alpha2:
        table.add_row("iso3166-1", ", ".join(region.iso3166_1_alpha2))
    if region.iso3166_2:
        table.add_row("iso3166-2", ", ".join(region.iso3166_2))
    table.add_row("formats", ", ".join(sorted(region.available_formats)) or "-")
    out.print(table)
    if region.urls:
        urls = Table(title="URLs", show_header=True, header_style="bold")
        urls.add_column("format")
        urls.add_column("url")
        for key, url in sorted(region.urls.items()):
            urls.add_row(key, url)
        out.print(urls)


# ── Validation helpers ───────────────────────────────────────────────────────


_VALID_FORMATS: frozenset[str] = frozenset({"pbf", "shp", "gpkg", "bz2", "poly", "kml"})
_VALID_LAYERS: frozenset[str] = frozenset(LAYER_TO_PREFIX.keys())


def _coerce_format(value: str) -> Format:
    if value not in _VALID_FORMATS:
        raise typer.BadParameter(
            f"{value!r} is not a valid format. Choose from: {sorted(_VALID_FORMATS)}"
        )
    return value  # type: ignore[return-value]


def _coerce_layer(value: str) -> ShpLayer:
    if value not in _VALID_LAYERS:
        raise typer.BadParameter(
            f"{value!r} is not a valid layer. Choose from: {sorted(_VALID_LAYERS)}"
        )
    return value  # type: ignore[return-value]


# ── Commands ─────────────────────────────────────────────────────────────────


@app.command("list")
def list_regions(
    ctx: typer.Context,
    parent: Annotated[
        str | None,
        typer.Option("--parent", help="Parent region id; omit for top-level continents."),
    ] = None,
) -> None:
    """List regions, optionally filtered by parent."""
    state = _state(ctx)
    with state.open_client() as client:
        regions = client.list_regions(parent=parent)
    _print_regions(state, regions)


@app.command("search")
def search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Case-insensitive substring.")],
) -> None:
    """Search region id and name."""
    state = _state(ctx)
    with state.open_client() as client:
        regions = client.search_regions(query)
    _print_regions(state, regions)


@app.command("children")
def children(
    ctx: typer.Context,
    region_id: Annotated[str, typer.Argument(help="Parent region id.")],
) -> None:
    """List direct children of a region."""
    state = _state(ctx)
    with state.open_client() as client:
        regions = client.children_of(region_id)
    _print_regions(state, regions)


@app.command("info")
def info(
    ctx: typer.Context,
    region_id: Annotated[str, typer.Argument(help="Region id (e.g. 'germany').")],
) -> None:
    """Show details and download URLs for a single region."""
    state = _state(ctx)
    with state.open_client() as client:
        region = client.get_region(region_id)
    _print_region_detail(state, region)


@app.command("url")
def url(
    ctx: typer.Context,
    region_id: Annotated[str, typer.Argument()],
    format: Annotated[
        str,
        typer.Option(
            "--format", "-f",
            click_type=click.Choice(sorted(_VALID_FORMATS)),
            help="File format to print the URL for.",
        ),
    ],
) -> None:
    """Print the download URL for a region/format. Pipeable into curl or wget."""
    state = _state(ctx)
    with state.open_client() as client:
        download_url = client.download_url(region_id, _coerce_format(format))
    out.print(download_url, highlight=False, soft_wrap=True)


@app.command("refresh")
def refresh(ctx: typer.Context) -> None:
    """Force a re-fetch of the Geofabrik index."""
    state = _state(ctx)
    with state.open_client() as client:
        client.refresh_index()
    if not state.quiet:
        err.print("[green]Index refreshed.[/green]")


@app.command("download")
def download(
    ctx: typer.Context,
    region_id: Annotated[str, typer.Argument()],
    format: Annotated[
        str,
        typer.Option(
            "--format", "-f",
            click_type=click.Choice(sorted(_VALID_FORMATS)),
            help="File format to download.",
        ),
    ],
    dest: Annotated[Path, typer.Option("--dest", "-d", help="Destination directory.")] = Path("."),
    verify: Annotated[bool, typer.Option("--verify/--no-verify", help="MD5-verify after download.")] = True,
    resume: Annotated[bool, typer.Option("--resume/--no-resume", help="Resume an interrupted download.")] = True,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Re-download even if the file exists.")] = False,
) -> None:
    """Download a region in the chosen format."""
    state = _state(ctx)
    fmt = _coerce_format(format)
    show_progress = not state.quiet and out.is_terminal and not state.json_output

    with state.open_client() as client:
        if show_progress:
            progress = Progress(
                TextColumn("[bold]{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=err,
            )
            with progress:
                task_id = progress.add_task(f"{region_id} ({fmt})", total=None)

                def on_chunk(done: int, total: int | None) -> None:
                    if total is not None:
                        progress.update(task_id, total=total)
                    progress.update(task_id, completed=done)

                result = client.download(
                    region_id,
                    format=fmt,
                    dest=dest,
                    verify=verify,
                    resume=resume,
                    overwrite=overwrite,
                    progress=on_chunk,
                )
        else:
            result = client.download(
                region_id,
                format=fmt,
                dest=dest,
                verify=verify,
                resume=resume,
                overwrite=overwrite,
            )

    if state.json_output:
        out.print_json(
            data={
                "path": result.path,
                "bytes_written": result.bytes_written,
                "resumed": result.resumed,
                "verified": result.verified,
                "url": result.url,
            }
        )
    elif not state.quiet:
        verified = "[green]verified[/green]" if result.verified else "[yellow]unverified[/yellow]"
        resumed = " (resumed)" if result.resumed else ""
        err.print(
            f"Saved [bold]{result.bytes_written:,}[/bold] bytes to "
            f"[cyan]{result.path}[/cyan] — {verified}{resumed}"
        )


@app.command("find-point")
def find_point(
    ctx: typer.Context,
    lat: Annotated[float, typer.Argument()],
    lon: Annotated[float, typer.Argument()],
) -> None:
    """Find regions whose bounding box contains a point. Forces a full index fetch (~50 MB)."""
    state = _state(ctx)
    if not state.quiet:
        err.print("[yellow]Loading full index with geometry (~50 MB)…[/yellow]")
    with state.open_client(include_geometry=True) as client:
        regions = client.find_by_point(lat, lon)
    _print_regions(state, regions)


@app.command("find-bbox")
def find_bbox(
    ctx: typer.Context,
    min_lon: Annotated[float, typer.Argument()],
    min_lat: Annotated[float, typer.Argument()],
    max_lon: Annotated[float, typer.Argument()],
    max_lat: Annotated[float, typer.Argument()],
) -> None:
    """Find regions whose bounding box overlaps a bbox. Forces a full index fetch (~50 MB)."""
    state = _state(ctx)
    if not state.quiet:
        err.print("[yellow]Loading full index with geometry (~50 MB)…[/yellow]")
    with state.open_client(include_geometry=True) as client:
        regions = client.find_by_bbox(min_lon, min_lat, max_lon, max_lat)
    _print_regions(state, regions)


@app.command("layers")
def layers(
    ctx: typer.Context,
    zip_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
) -> None:
    """List shapefile layers present in a Geofabrik .shp.zip (local; no network)."""
    state = _state(ctx)
    # Layer listing doesn't need the index — skip the HTTP client.
    found = _ex.list_layers(zip_path)
    if state.json_output:
        out.print_json(data=found)  # list_layers() already returns sorted
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("layer")
    table.add_column("file prefix")
    for layer in sorted(found):
        table.add_row(layer, LAYER_TO_PREFIX[layer])
    out.print(table)


@app.command("extract")
def extract_layers(
    ctx: typer.Context,
    zip_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    layers_arg: Annotated[
        list[str],
        typer.Argument(
            metavar="LAYER...",
            help="One or more shapefile layer names (e.g. roads buildings).",
        ),
    ],
    dest: Annotated[Path, typer.Option("--dest", "-d", help="Destination directory.")] = Path("."),
) -> None:
    """Extract one or more shapefile layers from a Geofabrik .shp.zip."""
    state = _state(ctx)
    written: dict[str, list[str]] = {}
    for raw in layers_arg:
        layer = _coerce_layer(raw)
        paths = _ex.extract_layer(zip_path, layer, dest)
        written[layer] = [str(p) for p in paths]

    if state.json_output:
        out.print_json(data=written)
    elif not state.quiet:
        for layer, paths in written.items():
            err.print(f"[green]{layer}[/green]: {len(paths)} files")
            for p in paths:
                err.print(f"  {p}")


# ── Entry point with centralised error handling ──────────────────────────────


def main() -> None:
    """Console-script entry point. Maps known errors to stable exit codes."""
    try:
        app(standalone_mode=False)
    except typer.Exit as exc:
        raise SystemExit(exc.exit_code) from None
    except typer.Abort:
        err.print("[yellow]Aborted.[/yellow]")
        raise SystemExit(130) from None
    except click_exceptions() as exc:  # Typer's underlying click errors
        exc.show()
        raise SystemExit(exc.exit_code) from None
    except RegionNotFoundError as exc:
        err.print(f"[red]{exc}[/red]")
        raise SystemExit(EXIT_REGION_NOT_FOUND) from None
    except FormatNotAvailableError as exc:
        err.print(f"[red]{exc}[/red]")
        raise SystemExit(EXIT_FORMAT_NOT_AVAILABLE) from None
    except ChecksumMismatchError as exc:
        err.print(f"[red]{exc}[/red]")
        raise SystemExit(EXIT_CHECKSUM_MISMATCH) from None
    except LayerNotFoundError as exc:
        err.print(f"[red]{exc}[/red]")
        raise SystemExit(EXIT_LAYER_NOT_FOUND) from None
    except GeometryNotLoadedError as exc:
        err.print(f"[red]{exc}[/red]")
        raise SystemExit(EXIT_GEOMETRY_NOT_LOADED) from None
    except GeofabrikError as exc:
        err.print(f"[red]{exc}[/red]")
        raise SystemExit(EXIT_GENERIC) from None
    except KeyboardInterrupt:
        err.print("[yellow]Interrupted.[/yellow]")
        raise SystemExit(130) from None


def click_exceptions() -> tuple[type[BaseException], ...]:
    """Lazy-import click's UsageError so we don't add an explicit dep line."""
    try:
        from click.exceptions import ClickException

        return (ClickException,)
    except ImportError:  # pragma: no cover
        return ()


if __name__ == "__main__":  # pragma: no cover
    main()
