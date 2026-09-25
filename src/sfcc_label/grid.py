"""NSIDC EASE-Grid 2.0 global cell lookup (zero-based indexing)."""

from dataclasses import dataclass
from math import floor, isfinite

from pyproj import Transformer

_TRANSFORMER = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)

# Dimensions and outer upper-left pixel edges from the NSIDC EASE-Grid guide.
_GRIDS = {
    "9km": (3856, 1624, -17367530.44, 7314540.83),
    "25km": (1388, 584, -17367530.44, 7307375.92),
}


@dataclass(frozen=True)
class GridCell:
    resolution: str
    row: int
    col: int

    @property
    def cell_id(self) -> str:
        return f"EASE2_G_{self.resolution}_r{self.row:04d}_c{self.col:04d}"


def grid_cell(latitude: float, longitude: float, resolution: str = "9km") -> GridCell:
    """Locate a WGS84 point in the NSIDC global grid, or raise if out of bounds."""
    if resolution not in _GRIDS:
        raise ValueError("resolution must be '9km' or '25km'")
    if not isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if not isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")
    columns, rows, left, top = _GRIDS[resolution]
    x, y = _TRANSFORMER.transform(longitude, latitude)
    if not isfinite(x) or not isfinite(y):
        raise ValueError("point cannot be projected onto the global EASE grid")
    width = -2 * left / columns
    height = 2 * top / rows
    col = floor((x - left) / width)
    row = floor((top - y) / height)
    # Longitudes +/-180 are the same meridian; wrap only that right-hand edge.
    if col == columns and longitude == 180:
        col = 0
    if not (0 <= col < columns and 0 <= row < rows):
        raise ValueError("point is outside the published global EASE-Grid extent")
    return GridCell(resolution, row, col)
