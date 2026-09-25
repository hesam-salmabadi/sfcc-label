"""NSIDC EASE-Grid 2.0 Northern Hemisphere cell lookup (zero-based)."""

from dataclasses import dataclass
from math import floor, isfinite

from pyproj import Transformer

_TRANSFORMER = Transformer.from_crs("EPSG:4326", "EPSG:6931", always_xy=True)

# Dimensions and outer upper-left pixel edges from the NSIDC EASE-Grid guide.
_GRIDS = {
    "9km": (2000, 2000, -9000000.0, 9000000.0),
    "25km": (720, 720, -9000000.0, 9000000.0),
}


@dataclass(frozen=True)
class GridCell:
    resolution: str
    row: int
    col: int

    @property
    def cell_id(self) -> str:
        return f"EASE2_N_{self.resolution}_r{self.row:04d}_c{self.col:04d}"


def grid_cell(latitude: float, longitude: float, resolution: str = "9km") -> GridCell:
    """Locate a northern WGS84 point in the NSIDC polar grid."""
    if resolution not in _GRIDS:
        raise ValueError("resolution must be '9km' or '25km'")
    if not isfinite(latitude) or not 0 <= latitude <= 90:
        raise ValueError("latitude must be between 0 and 90 for the Northern Hemisphere grid")
    if not isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")
    columns, rows, left, top = _GRIDS[resolution]
    x, y = _TRANSFORMER.transform(longitude, latitude)
    if not isfinite(x) or not isfinite(y):
        raise ValueError("point cannot be projected onto the Northern Hemisphere EASE grid")
    width = -2 * left / columns
    height = 2 * top / rows
    col = floor((x - left) / width)
    row = floor((top - y) / height)
    if not (0 <= col < columns and 0 <= row < rows):
        raise ValueError("point is outside the published Northern Hemisphere EASE-Grid extent")
    return GridCell(resolution, row, col)
