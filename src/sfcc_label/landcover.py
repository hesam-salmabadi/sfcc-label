"""Annual MODIS IGBP land-cover screening before spatial aggregation."""

import csv
from dataclasses import dataclass
from pathlib import Path

from .grid import grid_cell
from .models import SensorMetadata

SENSOR_COLUMNS = ("sensor_id", "year", "igbp_class", "product", "collection")
SCREEN_COLUMNS = ("sensor_id", "year", "resolution", "cell_id", "sensor_igbp_class",
                  "grid_igbp_class", "eligible", "reason")


@dataclass(frozen=True)
class SensorLandCover:
    sensor_id: str
    year: int
    igbp_class: int | None
    product: str = "MCD12Q1"
    collection: str = "061"


@dataclass(frozen=True)
class LandCoverScreen:
    sensor_id: str
    year: int
    resolution: str
    cell_id: str
    sensor_igbp_class: int | None
    grid_igbp_class: int | None
    eligible: bool
    reason: str


def _class_code(value: int | str | None) -> int | None:
    if value is None or str(value).strip().lower() in {"", "nan", "255"}:
        return None
    code = int(value)
    if code not in range(1, 18):
        raise ValueError("MODIS IGBP class must be 1–17 or missing/fill")
    return code


def screen_land_cover(sensor: SensorMetadata, year: int, resolution: str,
                      sensor_class: int | None, grid_class: int | None) -> LandCoverScreen:
    """Apply the requested exact IGBP class match; unknown classes fail closed."""
    cell = grid_cell(sensor.latitude, sensor.longitude, resolution)
    sensor_class = _class_code(sensor_class)
    grid_class = _class_code(grid_class)
    if sensor_class is None:
        reason = "missing_sensor_class"
    elif grid_class is None:
        reason = "missing_grid_class"
    elif sensor_class != grid_class:
        reason = "class_mismatch"
    else:
        reason = "match"
    return LandCoverScreen(sensor.sensor_id, year, resolution, cell.cell_id,
                           sensor_class, grid_class, reason == "match", reason)


def read_sensor_land_cover(path: str | Path) -> dict[tuple[str, int], SensorLandCover]:
    result = {}
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != SENSOR_COLUMNS:
            raise ValueError(f"{path}: expected columns {', '.join(SENSOR_COLUMNS)}")
        for row in reader:
            record = SensorLandCover(row["sensor_id"], int(row["year"]),
                                     _class_code(row["igbp_class"]),
                                     row["product"], row["collection"])
            if (record.product, record.collection) != ("MCD12Q1", "061"):
                raise ValueError("sensor land cover must use MCD12Q1.061 IGBP")
            key = (record.sensor_id, record.year)
            if key in result:
                raise ValueError(f"duplicate sensor/year land cover: {key}")
            result[key] = record
    return result


def write_sensor_land_cover(path: str | Path, records: list[SensorLandCover]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(SENSOR_COLUMNS)
        for record in records:
            writer.writerow((record.sensor_id, record.year,
                             record.igbp_class if record.igbp_class is not None else "NaN",
                             record.product, record.collection))


def write_land_cover_screen(path: str | Path, records: list[LandCoverScreen]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(SCREEN_COLUMNS)
        for record in records:
            writer.writerow((record.sensor_id, record.year, record.resolution, record.cell_id,
                             record.sensor_igbp_class if record.sensor_igbp_class is not None else "NaN",
                             record.grid_igbp_class if record.grid_igbp_class is not None else "NaN",
                             int(record.eligible), record.reason))


def read_land_cover_screen(path: str | Path) -> dict[tuple[str, int, str], LandCoverScreen]:
    result = {}
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != SCREEN_COLUMNS:
            raise ValueError(f"{path}: expected columns {', '.join(SCREEN_COLUMNS)}")
        for row in reader:
            record = LandCoverScreen(row["sensor_id"], int(row["year"]),
                                     row["resolution"], row["cell_id"],
                                     _class_code(row["sensor_igbp_class"]),
                                     _class_code(row["grid_igbp_class"]),
                                     row["eligible"] == "1", row["reason"])
            key = (record.sensor_id, record.year, record.resolution)
            if key in result:
                raise ValueError(f"duplicate land-cover screen: {key}")
            result[key] = record
    return result


def is_representative(sensor_id: str, year: int, resolution: str,
                      cell_id: str,
                      screens: dict[tuple[str, int, str], LandCoverScreen]) -> bool:
    """A missing screen never grants eligibility."""
    record = screens.get((sensor_id, year, resolution))
    return bool(record and record.cell_id == cell_id and record.eligible
                and record.sensor_igbp_class is not None
                and record.sensor_igbp_class == record.grid_igbp_class)
