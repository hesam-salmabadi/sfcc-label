"""SMOS-style land-cover representativeness screen before spatial aggregation.

A sensor enters a cell summary on a grid only when all of these hold:

1. its own 300 m ESA CCI class equals the cell's dominant class,
2. that class covers at least 70 % of the cell,
3. open water covers at most 5 % of the cell,
4. "other" (permanent ice, bare, urban) covers at most 5 % of the cell.

Missing classes or fractions fail closed. Thresholds follow the SMOS L3 soil
freeze-thaw validation (Rautiainen et al., 2025, ESSD). SMOS applies the 70 %
test to the classes of all sensors in a cell together; here it is applied to
each sensor on its own. One representative land-cover year is used, so a
screen belongs to a sensor and a grid, not to a year.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from .grid import ease_grid

MIN_CLASS_FRACTION = 0.70
MAX_WATER_FRACTION = 0.05
MAX_OTHER_FRACTION = 0.05


@dataclass(frozen=True)
class LandCoverScreen:
    sensor_id: str
    grid: str
    cell_id: str
    sensor_class: str | None
    cell_class: str | None
    sensor_class_fraction: float | None
    water_fraction: float | None
    other_fraction: float | None
    eligible: bool
    reason: str


def screen_land_cover(sensor_id: str, grid: str, cell_id: str, sensor_class: str | None,
                      cell_class: str | None, sensor_class_fraction: float | None,
                      water_fraction: float | None, other_fraction: float | None) -> LandCoverScreen:
    """Apply the four checks in order; the reason names the first one that fails."""
    if not sensor_class:
        reason = "missing_sensor_class"
    elif not cell_class:
        reason = "missing_cell_class"
    elif sensor_class != cell_class:
        reason = "class_mismatch"
    elif sensor_class_fraction is None or sensor_class_fraction < MIN_CLASS_FRACTION:
        reason = "class_below_70pct"
    elif water_fraction is None or water_fraction > MAX_WATER_FRACTION:
        reason = "water_above_5pct"
    elif other_fraction is None or other_fraction > MAX_OTHER_FRACTION:
        reason = "other_above_5pct"
    else:
        reason = "representative"
    return LandCoverScreen(sensor_id, ease_grid(grid).name, cell_id, sensor_class, cell_class,
                           sensor_class_fraction, water_fraction, other_fraction,
                           reason == "representative", reason)


def _text(value: str | None) -> str | None:
    return None if value in (None, "", "NaN") else value


def _number(value: str | None) -> float | None:
    text = _text(value)
    return None if text is None else float(text)


def read_land_cover_screens(path: str | Path) -> dict[tuple[str, str], LandCoverScreen]:
    """Screens keyed by (sensor_id, grid) from ``sensor_landcover_cci.csv``.

    Eligibility is recomputed from the stored classes and fractions, so the
    thresholds above are the single source of truth.
    """
    result = {}
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            if _text(row["cell_id"]) is None:
                continue
            record = screen_land_cover(
                row["sensor_id"], row["grid"], row["cell_id"], _text(row["sensor_class"]),
                _text(row["cell_class"]), _number(row["sensor_class_fraction"]),
                _number(row["water_fraction"]), _number(row["other_fraction"]))
            key = (record.sensor_id, record.grid)
            if key in result:
                raise ValueError(f"duplicate land-cover screen: {key}")
            result[key] = record
    return result


def is_representative(sensor_id: str, resolution: str, cell_id: str,
                      screens: dict[tuple[str, str], LandCoverScreen]) -> bool:
    """A missing screen never grants eligibility."""
    record = screens.get((sensor_id, ease_grid(resolution).name))
    return bool(record and record.cell_id == cell_id and record.eligible)
