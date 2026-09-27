"""Import the published, UTC-hourly Trail Valley Creek soil profile.

The four horizontal CS630/PT100 positions have paired moisture and
temperature. Three vertical CS630 probes integrate moisture over 0–15 cm and
remain moisture-only streams. The separate TVC_Boike_2013_2020.csv is not read.
"""

from __future__ import annotations

import csv
import math
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .io import OBSERVATION_COLUMNS, write_metadata
from .models import SensorMetadata
from .naming import sensor_id as make_sensor_id


LATITUDE = 68.745483
LONGITUDE = -133.499070
COLLECTION_URL = "https://doi.org/10.1594/PANGAEA.923373"
DEPTHS = (2, 5, 10, 20)
VERTICAL_CODES = (
    ("hummock", "next to horizontal profile (hummock)"),
    ("midway", "midway between hummock and shrub water pathway"),
    ("shrub", "in shrub water pathway"),
)
CONTEXT_COLUMNS = (
    "sensor_id", "measurement_support", "source_files", "source_columns",
    "source_rows", "observed_hours", "temperature_hours", "moisture_hours",
    "first_utc", "last_utc", "time_basis", "source_doi",
)


def _number(raw: str) -> float | None:
    if raw.strip().lower() in {"", "nan", "na"}:
        return None
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"nonfinite TVC measurement {raw!r}")
    return value


def _read_rows(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        utc_declared = False
        for line in stream:
            if "DATE/TIME (Date/Time)" in line and "COMMENT: UTC" in line:
                utc_declared = True
            if line.startswith("Date/Time (UTC)\t"):
                header = line.rstrip("\r\n").split("\t")
                break
        else:
            raise ValueError(f"missing UTC data header in {path}")
        if not utc_declared or len(header) != 12:
            raise ValueError(f"unexpected TVC time basis or columns in {path}")
        if not (all(header[i].startswith("T soil [°C]") for i in range(1, 5))
                and all(header[i].startswith("Soil moisture vol") for i in range(5, 12))):
            raise ValueError(f"unexpected TVC measurements in {path}")
        for row_number, row in enumerate(csv.reader(stream, delimiter="\t"), start=2):
            if len(row) != 12:
                raise ValueError(f"{path}: data row {row_number} has {len(row)} columns")
            stamp = datetime.strptime(row[0], "%Y-%m-%dT%H:%M")
            if stamp.minute:
                raise ValueError(f"{path}: non-hourly timestamp {row[0]}")
            if stamp.year != int(path.stem[-4:]):
                raise ValueError(f"{path}: timestamp outside filename year: {row[0]}")
            yield stamp, [_number(value) for value in row[1:]]


def _write_hourly(path: Path, values: dict[datetime, tuple[float | None, float | None]]) -> None:
    first, last = min(values), max(values)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(OBSERVATION_COLUMNS)
        hour = first
        while hour <= last:
            temperature, moisture = values.get(hour, (None, None))
            writer.writerow((hour.strftime("%Y-%m-%dT%H:00:00Z"),
                             "NaN" if temperature is None else format(temperature, ".15g"),
                             "NaN" if moisture is None else format(moisture, ".15g"),
                             "NaN"))
            hour += timedelta(hours=1)


def import_tvc_boike(source_dir: str | Path, observations_dir: str | Path,
                     sensors_file: str | Path, context_file: str | Path) -> list[dict]:
    """Create seven non-overlapping physical probe streams from PANGAEA tabs."""
    source = Path(source_dir)
    output = Path(observations_dir)
    destinations = (output, Path(sensors_file), Path(context_file))
    if any(path.exists() for path in destinations):
        raise FileExistsError("TVC Boike output already exists")
    files = sorted(path for path in source.glob("Boike-etal_2020_TVCsoil????.tab")
                   if not path.name.startswith("._"))
    if not files:
        raise FileNotFoundError(f"no PANGAEA TVC annual tabs in {source}")
    pairs = {depth: make_sensor_id("tvc_boike", "tvc", float(depth)) for depth in DEPTHS}
    verticals = {code: make_sensor_id("tvc_boike", "tvc", 0.0, 15.0, tag=code)
                 for code, _ in VERTICAL_CODES}
    streams: dict[str, dict[datetime, tuple[float | None, float | None]]] = defaultdict(dict)
    origins: dict[str, set[str]] = defaultdict(set)
    source_rows = 0
    seen: set[datetime] = set()
    for file in files:
        for stamp, values in _read_rows(file):
            if stamp in seen:
                raise ValueError(f"duplicate TVC UTC hour {stamp} in {file}")
            seen.add(stamp)
            source_rows += 1
            for index, depth in enumerate(DEPTHS):
                sensor_id = pairs[depth]
                origins[sensor_id].add(str(file))
                temperature, moisture = values[index], values[index + 4]
                if temperature is not None or moisture is not None:
                    streams[sensor_id][stamp] = temperature, moisture
            for index, (code, _) in enumerate(VERTICAL_CODES):
                sensor_id = verticals[code]
                origins[sensor_id].add(str(file))
                moisture = values[index + 8]
                if moisture is not None:
                    streams[sensor_id][stamp] = None, moisture
    if not all(streams[sensor_id] for sensor_id in (*pairs.values(), *verticals.values())):
        raise ValueError("one or more TVC probe streams contain no observations")
    output.parent.mkdir(parents=True, exist_ok=True)
    Path(sensors_file).parent.mkdir(parents=True, exist_ok=True)
    Path(context_file).parent.mkdir(parents=True, exist_ok=True)
    sensors = []
    contexts = []
    with tempfile.TemporaryDirectory(prefix=".sfcc-tvc-boike-", dir=output.parent) as temp:
        stage = Path(temp)
        probes = [(sensor_id, depth, None) for depth, sensor_id in pairs.items()]
        probes += [(sensor_id, None, code) for code, sensor_id in verticals.items()]
        for sensor_id, depth, code in probes:
            horizontal = code is None
            support = (f"horizontal point at {depth} cm below moss-air surface" if horizontal
                       else next(note for name, note in VERTICAL_CODES if name == code))
            bounds = (float(depth), float(depth)) if horizontal else (0.0, 15.0)
            sensors.append(SensorMetadata(
                sensor_id=sensor_id, source="tvc_boike", latitude=LATITUDE,
                longitude=LONGITUDE, site_id="N_Trail_Valley_Creek",
                network="PANGAEA", station="Trail Valley Creek Boike profile",
                depth_cm=float(depth) if horizontal else 7.5,
                depth_from_cm=bounds[0], depth_to_cm=bounds[1],
                source_id=(f"horizontal_{depth}cm" if horizontal else f"vertical_0to15cm_{code}"),
                source_url=COLLECTION_URL, timezone_original="UTC (publisher Date/Time)",
                soil_moisture_method="CS630 TDR; liquid volumetric water content",
                soil_temperature_sensor_type="PT100" if horizontal else None,
                soil_moisture_sensor_type="CS630",
                sensor_type_source="PANGAEA Boike et al. 2020 metadata",
                sensor_type_note=("vertical 0–15 cm moisture-only probe" if not horizontal else None),
            ))
            values = streams[sensor_id]
            _write_hourly(stage / f"{sensor_id}.csv", values)
            columns = (f"T soil at {depth}cm; Soil moisture vol at {depth}cm" if horizontal
                       else f"Soil moisture vol vertical 0-15cm column {list(verticals).index(code) + 1}")
            contexts.append({
                "sensor_id": sensor_id,
                "measurement_support": support if horizontal else f"vertical 0-15 cm; {support}",
                "source_files": ";".join(sorted(origins[sensor_id])),
                "source_columns": columns,
                "source_rows": source_rows,
                "observed_hours": len(values),
                "temperature_hours": sum(temperature is not None for temperature, _ in values.values()),
                "moisture_hours": sum(moisture is not None for _, moisture in values.values()),
                "first_utc": min(values).isoformat() + "Z",
                "last_utc": max(values).isoformat() + "Z",
                "time_basis": "publisher Date/Time (UTC); exact hour; no conversion",
                "source_doi": COLLECTION_URL,
            })
        write_metadata(stage / "sensors.csv", sensors)
        with (stage / "context.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=CONTEXT_COLUMNS)
            writer.writeheader()
            writer.writerows(contexts)
        output.mkdir()
        for sensor in sensors:
            (stage / f"{sensor.sensor_id}.csv").replace(output / f"{sensor.sensor_id}.csv")
        (stage / "sensors.csv").replace(sensors_file)
        (stage / "context.csv").replace(context_file)
    return contexts
