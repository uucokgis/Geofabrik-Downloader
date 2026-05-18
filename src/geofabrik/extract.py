"""Shapefile layer extraction from Geofabrik ``.shp.zip`` archives."""

from __future__ import annotations

import zipfile
from pathlib import Path

from .errors import LayerNotFoundError
from .models import LAYER_TO_PREFIX, ShpLayer

_SHP_EXTS = frozenset({".shp", ".dbf", ".shx", ".prj"})
_PREFIX_TO_LAYER = {v: k for k, v in LAYER_TO_PREFIX.items()}


def list_layers(zip_path: Path) -> list[ShpLayer]:
    """Return which :data:`~geofabrik.ShpLayer` values are present in *zip_path*.

    Only layers whose ``.shp`` component is found are reported.
    """
    with zipfile.ZipFile(zip_path) as zf:
        names = {Path(n).stem for n in zf.namelist() if n.endswith(".shp")}
    layers: list[ShpLayer] = []
    for stem in names:
        layer = _PREFIX_TO_LAYER.get(stem)
        if layer is not None:
            layers.append(layer)
    return sorted(layers)


def extract_layer(zip_path: Path, layer: ShpLayer, dest: Path) -> list[Path]:
    """Extract all sidecar files for *layer* from *zip_path* into *dest*.

    Returns the list of extracted file paths (``.shp``, ``.dbf``, ``.shx``,
    ``.prj``).  Raises :exc:`~geofabrik.LayerNotFoundError` if *layer* is
    absent from the archive.
    """
    prefix = LAYER_TO_PREFIX[layer]
    dest.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        targets = [
            n for n in zf.namelist()
            if Path(n).stem == prefix and Path(n).suffix in _SHP_EXTS
        ]
        if not targets:
            available = list_layers(zip_path)
            raise LayerNotFoundError(layer, available)

        extracted: list[Path] = []
        for member in targets:
            out_path = dest / Path(member).name
            with zf.open(member) as src, out_path.open("wb") as dst:
                dst.write(src.read())
            extracted.append(out_path)

    return extracted
