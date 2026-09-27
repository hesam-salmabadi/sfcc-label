"""Import BERMS Old Black Spruce and Old Jack Pine soil profiles.

Temperature depths are point measurements. Soil VWC intervals and nominal
depths are separate moisture-only streams; they are not paired to nearby
temperature points. CSV clocks follow the existing UTC interpretation; RData
POSIX times are converted from epoch seconds to UTC.
"""

from __future__ import annotations

import csv
import math
import re
import tempfile
import warnings
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .io import OBSERVATION_COLUMNS, write_metadata
from .models import SensorMetadata
from .naming import sensor_id as make_sensor_id


COORDINATES = {"BS01": (53.987, -105.118), "JP01": (53.916, -104.692)}
TEMP_DEPTHS = (2, 5, 10, 20, 50, 100)
BS_CSV_MOISTURE = {
    "SoilVWC_02d5cm": ("M02d5cm", 2.5, 2.5, 2.5),
    "SoilVWC_07d5cm": ("M07d5cm", 7.5, 7.5, 7.5),
    "SoilVWC_22d5cm": ("M22d5cm", 22.5, 22.5, 22.5),
    "SoilVWC_45cm": ("M45cm", 45.0, 45.0, 45.0),
    "SoilVWC_60to90cm": ("M60to90cm", 75.0, 60.0, 90.0),
}
JP_CSV_MOISTURE = {
    "SoilVWC_000to015cm": ("M000to015cm", 7.5, 0.0, 15.0),
    "SoilVWC_015to030cm": ("M015to030cm", 22.5, 15.0, 30.0),
    "SoilVWC_030to060cm": ("M030to060cm", 45.0, 30.0, 60.0),
    "SoilVWC_060to090cm": ("M060to090cm", 75.0, 60.0, 90.0),
    "SoilVWC_090to120cm": ("M090to120cm", 105.0, 90.0, 120.0),
    "SoilVWC_120to150cm": ("M120to150cm", 135.0, 120.0, 150.0),
}
BS_R_MOISTURE = {
    "vwc02.cm3cm3": ("MR02cm", 2.0, 2.0, 2.0),
    "vwc07.cm3cm3": ("MR07cm", 7.0, 7.0, 7.0),
    "vwc22.cm3cm3": ("MR22cm", 22.0, 22.0, 22.0),
    "vwc45.cm3cm3": ("MR45cm", 45.0, 45.0, 45.0),
    "vwc60.cm3cm3": ("MR60cm", 60.0, 60.0, 60.0),
}
CONTEXT_COLUMNS = ("sensor_id", "site_id", "measurement", "source_columns",
                   "source_files", "timezone_basis", "observed_hours", "first_utc",
                   "last_utc", "support_note")


def _number(raw: object) -> float | None:
    if raw is None or str(raw).strip().lower() in {"", "nan", "na", "null"}:
        return None
    value = float(raw)
    if math.isnan(value) or value in {9999.0, -9999.0}:
        return None
    if not math.isfinite(value):
        raise ValueError(f"nonfinite BERMS value {raw!r}")
    return value


def _write_hourly(path: Path, values: dict[datetime, tuple[float, int]],
                  measurement: str) -> None:
    first, last = min(values), max(values)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(OBSERVATION_COLUMNS)
        hour = first
        while hour <= last:
            pair = values.get(hour)
            value = "NaN" if pair is None else format(pair[0] / pair[1], ".15g")
            writer.writerow((hour.strftime("%Y-%m-%dT%H:00:00Z"),
                             value if measurement == "temperature" else "NaN",
                             value if measurement == "moisture" else "NaN", "NaN"))
            hour += timedelta(hours=1)


def import_berms(source_dir: str | Path, observations_dir: str | Path,
                 sensors_file: str | Path, context_file: str | Path) -> list[dict]:
    """Read CSV profiles and Old Black Spruce RData without inventing depth pairs."""
    source = Path(source_dir)
    output = Path(observations_dir)
    destinations = (output, Path(sensors_file), Path(context_file))
    if any(path.exists() for path in destinations):
        raise FileExistsError("BERMS output already exists")
    streams: dict[str, dict[datetime, tuple[float, int]]] = defaultdict(dict)
    specs: dict[str, tuple[str, str, float, float, float]] = {}
    origins: dict[str, set[str]] = defaultdict(set)
    columns: dict[str, set[str]] = defaultdict(set)

    def add(site: str, code: str, measurement: str, depth: float,
            lower: float, upper: float, hour: datetime, raw: object,
            file: Path, column: str) -> None:
        value = _number(raw)
        if value is None:
            return
        key = f"berms_{site}_{code}"
        spec = (site, measurement, depth, lower, upper)
        if key in specs and specs[key] != spec:
            raise ValueError(f"conflicting specification for {key}")
        specs[key] = spec
        origins[key].add(str(file))
        columns[key].add(column)
        old = streams[key].get(hour)
        streams[key][hour] = (value, 1) if old is None else (old[0] + value, old[1] + 1)

    csv_sources = (("BS01", source / "OBS_Soil_2016_AG.csv"),
                   ("BS01", source / "OBS_Soil_2021_AG.csv"),
                   ("JP01", source / "OJP_Soil_2015-2021_AG.csv"))
    for site, file in csv_sources:
        with file.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            needed = {"Time", *(f"SoilTemp_{d:03d}cm" for d in TEMP_DEPTHS)}
            moisture = BS_CSV_MOISTURE if site == "BS01" else JP_CSV_MOISTURE
            needed.update(moisture)
            if not needed.issubset(reader.fieldnames or ()):
                raise ValueError(f"missing BERMS source columns in {file}")
            for row in reader:
                stamp = datetime.fromisoformat(row["Time"])
                if stamp.tzinfo is not None:
                    raise ValueError(f"unexpected timezone-bearing CSV timestamp in {file}")
                hour = stamp.replace(minute=0, second=0, microsecond=0)
                for depth in TEMP_DEPTHS:
                    column = f"SoilTemp_{depth:03d}cm"
                    add(site, f"T{depth:03d}cm", "temperature", float(depth),
                        float(depth), float(depth), hour, row[column], file, column)
                for column, (code, depth, lower, upper) in moisture.items():
                    add(site, code, "moisture", depth, lower, upper, hour,
                        row[column], file, column)

    r_file = source / "Hydrometric.OBS.20172020.Prc.AR.RData"
    try:
        import rdata
    except ImportError as exc:
        raise RuntimeError("BERMS RData import requires pip install 'sfcc-label[source-r]'") from exc
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Missing constructor for R class")
        r_objects = rdata.read_rda(r_file)
    for name in ("soiltemp1718.obs", "soiltemp1920.obs", "soilvwc1718.obs", "soilvwc1920.obs"):
        frame = r_objects[name]
        if "time" not in frame.columns:
            raise ValueError(f"{name} has no POSIXct time")
        is_temp = name.startswith("soiltemp")
        mapping = ({f"soiltemp.{depth:02d}.celsius":
                    (f"T{depth:03d}cm", float(depth), float(depth), float(depth))
                   for depth in TEMP_DEPTHS} if is_temp else BS_R_MOISTURE)
        if not set(mapping).issubset(frame.columns):
            raise ValueError(f"{name} has unexpected depth columns")
        for record in frame.itertuples(index=False, name=None):
            row = dict(zip(frame.columns, record))
            epoch = float(row["time"])
            if not math.isfinite(epoch):
                continue
            hour = datetime.fromtimestamp(epoch, timezone.utc).replace(
                minute=0, second=0, microsecond=0, tzinfo=None)
            for column, (code, depth, lower, upper) in mapping.items():
                add("BS01", code, "temperature" if is_temp else "moisture",
                    depth, lower, upper, hour, row[column], r_file, f"{name}/{column}")

    output.parent.mkdir(parents=True, exist_ok=True)
    sensors = []
    contexts = []
    with tempfile.TemporaryDirectory(prefix=".sfcc-berms-", dir=output.parent) as temp:
        stage = Path(temp)
        for key, spec in sorted(specs.items()):
            site, measurement, depth, lower, upper = spec
            code = key.rsplit("_", 1)[1]
            sensor_id = make_sensor_id("berms", site, lower, upper,
                                       tag=re.match(r"MR|M|T", code).group(0))
            latitude, longitude = COORDINATES[site]
            sensors.append(SensorMetadata(
                sensor_id=sensor_id, source="berms", latitude=latitude,
                longitude=longitude, site_id=site, network="BERMS", station=site,
                depth_cm=depth, depth_from_cm=lower, depth_to_cm=upper,
                source_id=f"{site}_{code}",
                source_url=str(source),
                timezone_original=("CSV interpreted UTC (legacy convention); "
                                   "RData POSIX epoch converted to UTC"),
                soil_moisture_method=("source volumetric water content"
                                      if measurement == "moisture" else None),
            ))
            values = streams[key]
            _write_hourly(stage / f"{sensor_id}.csv", values, measurement)
            contexts.append({
                "sensor_id": sensor_id, "site_id": site, "measurement": measurement,
                "source_columns": ";".join(sorted(columns[key])),
                "source_files": ";".join(sorted(origins[key])),
                "timezone_basis": "CSV UTC by legacy pipeline/diurnal phase; RData absolute POSIX time",
                "observed_hours": len(values), "first_utc": min(values).isoformat() + "Z",
                "last_utc": max(values).isoformat() + "Z",
                "support_note": ("VWC support interval, not a point"
                                 if measurement == "moisture" and lower != upper else
                                 "nominal source depth"),
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
