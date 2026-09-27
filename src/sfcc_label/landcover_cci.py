"""ESA CCI Land Cover on every EASE-Grid 2.0 grid, in the six SMOS FT classes.

The SMOS L3 soil freeze-thaw product (Rautiainen et al., 2025, ESSD) aggregates
ESA CCI Land Cover v2.0.7 (300 m) into six classes and uses them to judge
whether a sensor represents its EASE-2 cell. This module does the same for one
representative year (default 2015, the last v2.0.7 year) on all ten grids:
Northern Hemisphere (N) and global (M) at 6.25, 9, 12.5, 25, and 36 km.

The paper names the six classes but not the mapping. The mapping here follows
the ESA CCI LC user guide IPCC conversion (flooded tree cover counts as
forest); ice, bare areas, and urban are "other" as in SMOS.

Each output GeoTIFF has seven uint16 bands: 1 = dominant class code (0 = no
data), 2-7 = area fraction of each class with scale 0.0001. Fractions are
weighted by 300 m pixel area (cos latitude), so they are true area shares.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from .grid import CRS, GRID_NAMES, ease_grid, grid_cell
from .landcover import screen_land_cover

CLASSES = {1: "forest", 2: "low_vegetation", 3: "wetland", 4: "agriculture", 5: "water", 6: "other"}
_GROUPS = {
    1: (50, 60, 61, 62, 70, 71, 72, 80, 81, 82, 90, 100, 160, 170),
    2: (110, 120, 121, 122, 130, 140, 150, 151, 152, 153),
    3: (180,),
    4: (10, 11, 12, 20, 30, 40),
    5: (210,),
    6: (190, 200, 201, 202, 220),
}
LOOKUP = np.zeros(256, dtype=np.uint8)
for _code, _values in _GROUPS.items():
    LOOKUP[list(_values)] = _code
FRACTION_SCALE = 1e-4
CHUNK_ROWS = 360  # one degree of 300 m CCI rows
SENSOR_COLUMNS = (
    "sensor_id", "source", "site_id", "latitude", "longitude", "cci_class", "sensor_class",
    "grid", "cell_id", "row", "col", "cell_class",
    *(f"{name}_fraction" for name in CLASSES.values()),
    "sensor_class_fraction", "sensor_matches_cell", "eligible", "reason", "land_cover_source",
)


def _projectors():
    """Separable EASE-2 projections: one call per row or column, not per pixel."""
    from pyproj import Transformer
    to_m = Transformer.from_crs("EPSG:4326", CRS["M"], always_xy=True)
    to_n = Transformer.from_crs("EPSG:4326", CRS["N"], always_xy=True)

    def global_x(lons):
        return to_m.transform(lons, np.zeros_like(lons))[0]

    def global_y(lats):
        return to_m.transform(np.zeros_like(lats), lats)[1]

    def polar_radius(lats):
        # EASE2_N is polar Lambert azimuthal equal-area: x = r sin(lon), y = -r cos(lon)
        return -to_n.transform(np.zeros_like(lats), lats)[1]

    return global_x, global_y, polar_radius


class _Accumulator:
    def __init__(self, name: str):
        self.grid = ease_grid(name)
        self.cells = self.grid.columns * self.grid.rows
        self.weights = np.zeros(self.cells * 7, dtype=np.float64)

    def add(self, x, y, classes, weight):
        grid = self.grid
        col = np.floor((x - grid.left) / grid.cell_m).astype(np.int64)
        row = np.floor((grid.top - y) / grid.cell_m).astype(np.int64)
        inside = (col >= 0) & (col < grid.columns) & (row >= 0) & (row < grid.rows) & (classes > 0)
        if not inside.any():
            return
        index = (row[inside] * grid.columns + col[inside]) * 7 + classes[inside]
        self.weights += np.bincount(index, weights=weight[inside], minlength=self.cells * 7)

    def bands(self) -> np.ndarray:
        weights = self.weights.reshape(self.grid.rows, self.grid.columns, 7)[..., 1:]
        total = weights.sum(axis=-1, keepdims=True)
        fractions = np.divide(weights, total, out=np.zeros_like(weights), where=total > 0)
        dominant = np.where(total[..., 0] > 0, fractions.argmax(axis=-1) + 1, 0)
        scaled = np.rint(fractions / FRACTION_SCALE).astype(np.uint16)
        return np.concatenate([dominant[None].astype(np.uint16), np.moveaxis(scaled, -1, 0)])


def aggregate_cci(source: str | Path, output_dir: str | Path, year: int = 2015,
                  grids: tuple[str, ...] = GRID_NAMES, progress=print) -> list[Path]:
    """Count area-weighted CCI classes inside every cell of each grid; write one GeoTIFF per grid."""
    import rasterio
    from rasterio.windows import Window

    output_dir = Path(output_dir)
    outputs = {name: output_dir / f"landcover_cci{year}_EASE2_{name}.tif" for name in grids}
    if any(path.exists() for path in outputs.values()):
        raise FileExistsError("land-cover grids already exist; remove them to rebuild")
    output_dir.mkdir(parents=True, exist_ok=True)
    global_x, global_y, polar_radius = _projectors()
    accumulators = [_Accumulator(name) for name in grids]
    families = {a.grid.family for a in accumulators}
    with rasterio.open(source) as src:
        if src.crs.to_epsg() != 4326 or src.count != 1:
            raise ValueError("expected the one-band EPSG:4326 ESA CCI LC GeoTIFF")
        step = src.transform.a
        lons = src.transform.c + (np.arange(src.width) + 0.5) * step
        lon_rad = np.radians(lons)
        sin_lon, cos_lon = np.sin(lon_rad), np.cos(lon_rad)
        xs_global = global_x(lons) if "M" in families else None
        for start in range(0, src.height, CHUNK_ROWS):
            rows = min(CHUNK_ROWS, src.height - start)
            lats = src.transform.f - (start + np.arange(rows) + 0.5) * step
            # N grid corners reach about 34 S; M grid ends near 85 degrees
            if lats.max() < -40:
                break
            raw = src.read(1, window=Window(0, start, src.width, rows))
            classes = LOOKUP[raw].ravel()
            weight = np.repeat(np.cos(np.radians(lats)), src.width)
            projected = {}
            if "M" in families:
                projected["M"] = (np.tile(xs_global, rows), np.repeat(global_y(lats), src.width))
            if "N" in families:
                radius = polar_radius(lats)[:, None]
                projected["N"] = ((radius * sin_lon).ravel(), (-radius * cos_lon).ravel())
            for accumulator in accumulators:
                accumulator.add(*projected[accumulator.grid.family], classes, weight)
            del projected
            if (start // CHUNK_ROWS) % 10 == 0:
                progress(f"latitude {lats[0]:6.1f} done")
    written = []
    for accumulator in accumulators:
        grid = accumulator.grid
        path = outputs[grid.name]
        temporary = path.with_name(path.name + ".tmp")
        with rasterio.open(temporary, "w", driver="GTiff", width=grid.columns, height=grid.rows,
                           count=7, dtype="uint16", crs=grid.crs, transform=grid.transform(),
                           compress="deflate", tiled=True, blockxsize=256, blockysize=256) as out:
            out.write(accumulator.bands())
            out.scales = (1.0, *([FRACTION_SCALE] * 6))
            out.descriptions = ("dominant_class", *(f"{name}_fraction" for name in CLASSES.values()))
            out.update_tags(source=Path(source).name, year=str(year),
                            classes=";".join(f"{code}={name}" for code, name in CLASSES.items()),
                            method="area-weighted count of 300 m CCI pixels per cell; SMOS FT six classes")
        temporary.replace(path)
        written.append(path)
        progress(f"wrote {path.name}")
    return written


def sensor_landcover(catalog: str | Path, source: str | Path, grid_dir: str | Path,
                     output: str | Path, year: int = 2015, grids: tuple[str, ...] = GRID_NAMES) -> int:
    """One row per sensor and grid: the sensor's own 300 m class and its cell's classes."""
    import rasterio

    with Path(catalog).open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    label = f"ESA CCI LC v2.0.7 {year}"
    with rasterio.open(source) as src:
        coords = [(float(r["longitude"]), float(r["latitude"])) for r in rows]
        raw = [int(v[0]) for v in src.sample(coords)]
    grid_files = {name: rasterio.open(Path(grid_dir) / f"landcover_cci{year}_EASE2_{name}.tif") for name in grids}
    count = 0
    output = Path(output)
    temporary = output.with_name(output.name + ".tmp")
    try:
        bands = {name: dataset.read() for name, dataset in grid_files.items()}
        with temporary.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=SENSOR_COLUMNS)
            writer.writeheader()
            for row, cci in zip(rows, raw):
                own = int(LOOKUP[cci])
                for name in grids:
                    record = {"sensor_id": row["sensor_id"], "source": row["source"],
                              "site_id": row["site_id"], "latitude": row["latitude"],
                              "longitude": row["longitude"], "cci_class": cci,
                              "sensor_class": CLASSES.get(own, "NaN"), "grid": name,
                              "land_cover_source": label}
                    try:
                        cell = grid_cell(float(row["latitude"]), float(row["longitude"]), name)
                    except ValueError:
                        record.update(cell_id="NaN", row="NaN", col="NaN", cell_class="NaN",
                                      eligible=False, reason="outside_grid")
                        writer.writerow(record)
                        count += 1
                        continue
                    values = bands[name][:, cell.row, cell.col]
                    fractions = values[1:] * FRACTION_SCALE
                    record.update(cell_id=cell.cell_id, row=cell.row, col=cell.col,
                                  cell_class=CLASSES.get(int(values[0]), "NaN"))
                    for code, fraction in zip(CLASSES, fractions):
                        record[f"{CLASSES[code]}_fraction"] = format(fraction, ".4f")
                    record["sensor_class_fraction"] = (format(fractions[own - 1], ".4f") if own else "NaN")
                    record["sensor_matches_cell"] = bool(own) and own == int(values[0])
                    screen = screen_land_cover(
                        row["sensor_id"], name, cell.cell_id, CLASSES.get(own),
                        CLASSES.get(int(values[0])),
                        float(fractions[own - 1]) if own else None,
                        float(fractions[4]), float(fractions[5]))
                    record.update(eligible=screen.eligible, reason=screen.reason)
                    writer.writerow(record)
                    count += 1
    finally:
        for dataset in grid_files.values():
            dataset.close()
    temporary.replace(output)
    return count
