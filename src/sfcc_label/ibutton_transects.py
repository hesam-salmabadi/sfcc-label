"""Import iButton transect temperatures at 0 and 5 cm (James Bay, Montmorency, Kuujjuarapik).

The raw files arrived in a folder named after UQAM; the name carries no meaning here.
"""

from __future__ import annotations

import csv
import math
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from .io import OBSERVATION_COLUMNS, write_metadata
from .models import SensorMetadata
from .naming import sensor_id as make_sensor_id


NETWORKS = {"BJ": "James Bay", "FM": "Montmorency Forest", "KJ": "Kuujjuarapik"}
SOURCES = {"BJ": "james_bay", "FM": "montmorency", "KJ": "kuujjuarapik"}
CONTEXT_COLUMNS = ("sensor_id", "source_id", "site_id", "depth_cm", "source_csv",
                   "source_workbook", "source_rows", "observed_hours", "first_utc",
                   "last_utc", "original_minute_first", "hour_collisions", "time_normalization",
                   "timezone_evidence", "surface_note")


def _metadata(workbook: Path, network: str) -> dict[str, dict]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("iButton transect importer requires pip install 'sfcc-label[source-excel]'") from exc
    book = load_workbook(workbook, read_only=True, data_only=True)
    try:
        sheet = book["Metadata"]
        rows = sheet.values
        columns = next(rows)
        needed = {"Raw_data_identifier", "Latitude", "Longitude", "Sensor_height",
                  "Timezone", "Microclimate_measurement", "Unit", "Logger_type"}
        if not needed.issubset(columns):
            raise ValueError(f"missing workbook metadata columns: {sorted(needed - set(columns))}")
        records = {}
        for row in rows:
            record = dict(zip(columns, row))
            ident = record["Raw_data_identifier"]
            if not ident or not str(ident).startswith(f"CA_AR_{network}"):
                raise ValueError(f"unexpected identifier {ident!r} in {workbook}")
            if ident in records:
                raise ValueError(f"duplicate metadata identifier {ident}")
            suffix = str(ident).rsplit("_", 1)[-1]
            if suffix not in {"0", "5"} or record["Sensor_height"] != -int(suffix):
                raise ValueError(f"depth mismatch for {ident}")
            if record["Timezone"] != "UTC" or record["Microclimate_measurement"] != "Temperature":
                raise ValueError(f"unexpected time basis or measurement for {ident}")
            if record["Unit"] != "°C" or "Maxim" not in str(record["Logger_type"]):
                raise ValueError(f"unexpected instrument or unit for {ident}")
            records[str(ident)] = record
        return records
    finally:
        book.close()


def _write_hourly(path: Path, observations: dict[datetime, float]) -> None:
    first, last = min(observations), max(observations)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(OBSERVATION_COLUMNS)
        hour = first
        while hour <= last:
            value = observations.get(hour)
            writer.writerow((hour.strftime("%Y-%m-%dT%H:00:00Z"),
                             "NaN" if value is None else format(value, ".15g"), "NaN", "NaN"))
            hour += timedelta(hours=1)


def import_ibutton_transect(submission_dir: str | Path, network: str,
                            observations_dir: str | Path, sensors_file: str | Path,
                            context_file: str | Path) -> list[dict]:
    """Use the 2023 publisher workbook metadata and companion original CSV."""
    if network not in NETWORKS:
        raise ValueError(f"network must be one of {sorted(NETWORKS)}")
    source = Path(submission_dir) / "Submission_2023"
    workbook = source / f"{network}.xlsx"
    source_csv = source / f"{network}.csv"
    output = Path(observations_dir)
    destinations = (output, Path(sensors_file), Path(context_file))
    if any(p.exists() for p in destinations):
        raise FileExistsError(f"{network} iButton output already exists")
    metadata = _metadata(workbook, network)
    output.parent.mkdir(parents=True, exist_ok=True)
    sensors = []
    contexts = []
    seen = set()
    with tempfile.TemporaryDirectory(prefix=f".sfcc-{network.lower()}-", dir=output.parent) as temp:
        stage = Path(temp)

        def finish(ident: str, observations: dict[datetime, tuple[float, int]], count: int,
                   first_minute: int, collisions: int) -> None:
            if not observations:
                raise ValueError(f"{ident}: no usable observations")
            record = metadata[ident]
            site = ident.split("_")[2]
            depth = int(ident.rsplit("_", 1)[1])
            sensor_id = make_sensor_id(SOURCES[network], site, float(depth))
            sensors.append(SensorMetadata(
                sensor_id=sensor_id, source=SOURCES[network], site_id=site,
                network=NETWORKS[network], station=site,
                latitude=float(record["Latitude"]), longitude=float(record["Longitude"]),
                depth_cm=float(depth), depth_from_cm=float(depth), depth_to_cm=float(depth),
                source_id=ident, source_url=str(workbook),
                timezone_original="UTC (2023 workbook; 2022 metadata says Local)",
                soil_temperature_sensor_type="iButton",
                sensor_type_source="UQAM publisher workbook metadata",
            ))
            _write_hourly(stage / f"{sensor_id}.csv",
                          {hour: total / n for hour, (total, n) in observations.items()})
            contexts.append({
                "sensor_id": sensor_id, "source_id": ident, "site_id": site,
                "depth_cm": depth, "source_csv": str(source_csv),
                "source_workbook": str(workbook), "source_rows": count,
                "observed_hours": len(observations),
                "first_utc": min(observations).isoformat() + "Z",
                "last_utc": max(observations).isoformat() + "Z",
                "original_minute_first": first_minute,
                "hour_collisions": collisions,
                "time_normalization": "floor to containing UTC hour; colliding source readings averaged",
                "timezone_evidence": "Submission_2023 workbook Metadata/Timezone=UTC; Submission_2022 MetaData.csv says Local",
                "surface_note": "0 cm is ground surface beneath lichen" if depth == 0 else "5 cm below ground surface",
            })

        with source_csv.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != ["Raw_data_identifier", "Year", "Month", "Day",
                                     "Time (24h)", "Temperature"]:
                raise ValueError(f"unexpected CSV columns in {source_csv}")
            active = None
            observations: dict[datetime, tuple[float, int]] = {}
            count = 0
            first_minute = 0
            collisions = 0
            for line, row in enumerate(reader, 2):
                ident = row["Raw_data_identifier"]
                if ident not in metadata:
                    raise ValueError(f"{source_csv}:{line}: unknown identifier {ident}")
                if ident != active:
                    if active is not None:
                        finish(active, observations, count, first_minute, collisions)
                    if ident in seen:
                        raise ValueError(f"{source_csv}:{line}: noncontiguous identifier {ident}")
                    seen.add(ident)
                    active = ident
                    observations = {}
                    count = 0
                    first_minute = -1
                    collisions = 0
                stamp = datetime.fromisoformat(
                    f'{int(row["Year"]):04d}-{int(row["Month"]):02d}-{int(row["Day"]):02d}T{row["Time (24h)"]}'
                )
                if first_minute < 0:
                    first_minute = stamp.minute
                normalized = stamp.replace(minute=0, second=0, microsecond=0)
                value = float(row["Temperature"])
                if not math.isfinite(value):
                    raise ValueError(f"{source_csv}:{line}: nonfinite temperature")
                previous = observations.get(normalized)
                if previous is not None:
                    collisions += 1
                if previous is None:
                    observations[normalized] = (value, 1)
                else:
                    observations[normalized] = (previous[0] + value, previous[1] + 1)
                count += 1
            if active is not None:
                finish(active, observations, count, first_minute, collisions)
        if seen != set(metadata):
            raise ValueError(f"CSV does not match workbook metadata: {set(metadata) ^ seen}")
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
