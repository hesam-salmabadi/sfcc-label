"""NSIDC EASE-Grid 2.0 cell lookup (zero-based) for the Northern Hemisphere (N)
and global (M) grids at 6.25, 9, 12.5, 25, and 36 km.

A grid name is ``<family><resolution>``, e.g. ``N25km``, ``M9km``, or ``N6p25km``
(``p`` replaces the decimal point, as in sensor ids). A bare resolution such as
``9km`` means the Northern Hemisphere grid; dotted input like ``6.25km`` is accepted.
"""

from dataclasses import dataclass
from functools import lru_cache
from math import floor, isfinite

from pyproj import Transformer

CRS = {"N": "EPSG:6931", "M": "EPSG:6933"}
RESOLUTIONS = ("6p25km", "9km", "12p5km", "25km", "36km")
# family, columns, rows, cell size (m), from the NSIDC EASE-Grid 2.0 definitions.
# Grids are centred on the projection origin.
_DEFINITIONS = {
    "N6p25km": ("N", 2880, 2880, 6250.0),
    "N9km": ("N", 2000, 2000, 9000.0),
    "N12p5km": ("N", 1440, 1440, 12500.0),
    "N25km": ("N", 720, 720, 25000.0),
    "N36km": ("N", 500, 500, 36000.0),
    "M6p25km": ("M", 5552, 2336, 6256.315),
    "M9km": ("M", 3856, 1624, 9008.055210146),
    "M12p5km": ("M", 2776, 1168, 12512.63),
    "M25km": ("M", 1388, 584, 25025.26),
    "M36km": ("M", 964, 406, 36032.220840584),
}
GRID_NAMES = tuple(_DEFINITIONS)


@dataclass(frozen=True)
class EaseGrid:
    name: str
    family: str
    resolution: str
    columns: int
    rows: int
    cell_m: float

    @property
    def crs(self) -> str:
        return CRS[self.family]

    @property
    def left(self) -> float:
        return -self.columns * self.cell_m / 2

    @property
    def top(self) -> float:
        return self.rows * self.cell_m / 2

    def transform(self):
        from affine import Affine
        return Affine(self.cell_m, 0.0, self.left, 0.0, -self.cell_m, self.top)


def ease_grid(name: str) -> EaseGrid:
    name = name.replace(".", "p")
    key = name if name[:1] in CRS else f"N{name}"
    if key not in _DEFINITIONS:
        raise ValueError(f"grid must be one of {', '.join(GRID_NAMES)} (bare resolution means N)")
    family, columns, rows, cell_m = _DEFINITIONS[key]
    return EaseGrid(key, family, key[1:], columns, rows, cell_m)


@lru_cache(maxsize=None)
def _transformer(family: str) -> Transformer:
    return Transformer.from_crs("EPSG:4326", CRS[family], always_xy=True)


@dataclass(frozen=True)
class GridCell:
    resolution: str
    row: int
    col: int
    family: str = "N"

    @property
    def cell_id(self) -> str:
        return f"EASE2_{self.family}_{self.resolution}_r{self.row:04d}_c{self.col:04d}"


def grid_cell(latitude: float, longitude: float, resolution: str = "9km") -> GridCell:
    """Locate a WGS84 point in an EASE-Grid 2.0 grid (``9km``, ``N25km``, ``M36km``...)."""
    grid = ease_grid(resolution)
    low, label = (0, "Northern Hemisphere") if grid.family == "N" else (-90, "global")
    if not isfinite(latitude) or not low <= latitude <= 90:
        raise ValueError(f"latitude must be between {low} and 90 for the {label} {grid.name} grid")
    if not isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")
    x, y = _transformer(grid.family).transform(longitude, latitude)
    if not isfinite(x) or not isfinite(y):
        raise ValueError(f"point cannot be projected onto the {grid.name} grid")
    col = floor((x - grid.left) / grid.cell_m)
    row = floor((grid.top - y) / grid.cell_m)
    if not (0 <= col < grid.columns and 0 <= row < grid.rows):
        raise ValueError(f"point is outside the published {grid.name} extent")
    return GridCell(grid.resolution, row, col, grid.family)


def write_sensor_grid_cells(catalog, output) -> dict[str, int]:
    """One row per sensor with its cell id on every grid; returns occupied cells per grid."""
    import csv
    from pathlib import Path

    with Path(catalog).open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    columns = [f"EASE2_{name[0]}_{name[1:]}" for name in GRID_NAMES]
    occupied = {column: set() for column in columns}
    output = Path(output)
    temporary = output.with_name(output.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("sensor_id", "source", "site_id", "latitude", "longitude", *columns))
        for row in rows:
            latitude, longitude = float(row["latitude"]), float(row["longitude"])
            cells = []
            for name, column in zip(GRID_NAMES, columns):
                try:
                    cell = grid_cell(latitude, longitude, name).cell_id
                    occupied[column].add(cell)
                except ValueError:
                    cell = "NaN"
                cells.append(cell)
            writer.writerow((row["sensor_id"], row["source"], row["site_id"],
                             row["latitude"], row["longitude"], *cells))
    temporary.replace(output)
    return {column: len(cells) for column, cells in occupied.items()}
