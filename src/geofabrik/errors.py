"""Exception hierarchy for the geofabrik package."""

from __future__ import annotations


class GeofabrikError(Exception):
    """Base class for all errors raised by this package."""


class IndexFetchError(GeofabrikError):
    """Raised when the Geofabrik index cannot be fetched or parsed."""


class RegionNotFoundError(GeofabrikError):
    """Raised when a region id does not exist in the index."""

    def __init__(self, region_id: str) -> None:
        super().__init__(f"No region with id {region_id!r} in the Geofabrik index.")
        self.region_id = region_id


class FormatNotAvailableError(GeofabrikError):
    """Raised when a region exists but the requested format is not offered."""

    def __init__(
        self,
        region_id: str,
        format: str,
        available: frozenset[str],
        parts: tuple[str, ...] = (),
    ) -> None:
        msg = (
            f"Region {region_id!r} does not offer format {format!r}. "
            f"Available: {sorted(available)}"
        )
        if parts:
            msg += (
                f". Geofabrik splits this region — children {list(parts)} each offer "
                f"{format!r}. Use download_parts(...) or pass --parts on the CLI."
            )
        super().__init__(msg)
        self.region_id = region_id
        self.format = format
        self.available = available
        self.parts = parts


class ChecksumMismatchError(GeofabrikError):
    """Raised when a downloaded file's MD5 does not match the published checksum."""

    def __init__(self, path: str, expected: str, actual: str) -> None:
        super().__init__(
            f"Checksum mismatch for {path}: expected {expected}, got {actual}."
        )
        self.path = path
        self.expected = expected
        self.actual = actual


class LayerNotFoundError(GeofabrikError):
    """Raised when the requested shapefile layer is absent from the zip."""

    def __init__(self, layer: str, available: list[str]) -> None:
        super().__init__(
            f"Layer {layer!r} not found in shapefile zip. "
            f"Available: {sorted(available) if available else '(none detected)'}"
        )
        self.layer = layer
        self.available = available


class GeometryNotLoadedError(GeofabrikError):
    """Raised when a spatial query is attempted without geometry in the index."""

    def __init__(self) -> None:
        super().__init__(
            "Spatial queries require geometry. "
            "Initialise the client with include_geometry=True."
        )
