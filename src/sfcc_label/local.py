"""Harmonize supplied local level-0 network tables into per-site UTC hours.

Source timestamps are accepted as declared UTC. This importer does not attempt
to infer a time zone or apply anomaly QA/QC.
"""

from __future__ import annotations

import csv
import math
import re
import tempfile
from collections import defaultdict
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path

from .io import OBSERVATION_COLUMNS, write_metadata
from .models import SensorMetadata
from .naming import sensor_id as make_sensor_id


REQUIRED_SOURCE_COLUMNS = {"datetime", "site_id", "soil_temp", "soil_moist", "bulk_edc"}
STATUS_COLUMNS = ("site_id", "sensor_id", "status", "detail", "source_file", "source_rows",
                  "duplicate_samples", "unique_samples", "observed_hours",
                  "output_hours", "temperature_hours", "moisture_hours",
                  "raw_hours", "first_utc", "last_utc")
MISSING_SENTINELS = {9999.0, -9999.0}
PUBLISHER_IBUTTON_SITE = re.compile(r"N[IT]\d+")
SEPARATE_SOURCE_NETWORKS = {"Alaska ISMN", "RISMA ISMN", "Cambridge Bay", "Dryden", "Chapleau", "St_Marthe", "St_Maurice", "BERMS"}
SEPARATE_IBUTTON_NETWORKS = {"James Bay", "Montmorency Forest", "Kuujjuarapik"}
# Level-0 tables whose probe temperature gaps were filled with the co-located iButton record: every
# soil_temp without bulk_edc equals the iButton file (checked for all BJ sites, 2014-2022). Keep only the
# probe's own temperature; the iButton series is imported separately (import-ibutton-transect).
IBUTTON_FILLED_NETWORKS = {"James Bay"}
BERMS_5CM_SITES = {"BS01", "JP01"}


class ConflictingSampleError(ValueError):
    """One site has incompatible values recorded at an identical timestamp."""


class NoProbeDataError(ValueError):
    """Nothing remains for a site once iButton-filled temperatures are removed."""


def _source_number(value: str | None, path: Path, line: int, column: str) -> float | None:
    if value is None or not value.strip() or value.strip().lower() in {"nan", "na", "null"}:
        return None
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"{path}:{line}: invalid {column}: {value!r}") from exc
    if math.isnan(number) or number in MISSING_SENTINELS:
        return None
    if not math.isfinite(number):
        raise ValueError(f"{path}:{line}: nonfinite {column}: {value!r}")
    return number


def _source_time(value: str, path: Path, line: int) -> datetime:
    try:
        stamp = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{path}:{line}: invalid datetime: {value!r}") from exc
    if stamp.tzinfo is not None:
        raise ValueError(f"{path}:{line}: expected naive, declared-UTC datetime")
    return stamp


def read_local_metadata(path: str | Path) -> dict[str, SensorMetadata]:
    """Build sensor registry from local site metadata; preserve unknown depths."""
    result = {}
    source = Path(path)
    with source.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"Site ID", "Network Name", "Coordinates_Lat", "Coordinates_Lon",
                    "Sensor Depth (cm)"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError(f"{source}: missing metadata columns {sorted(required - set(reader.fieldnames or ())) }")
        for line, row in enumerate(reader, 2):
            site_id = row["Site ID"].strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]+", site_id):
                raise ValueError(f"{source}:{line}: invalid site ID {site_id!r}")
            if site_id in result:
                raise ValueError(f"{source}:{line}: duplicate site ID {site_id}")
            try:
                latitude = float(row["Coordinates_Lat"])
                longitude = float(row["Coordinates_Lon"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{source}:{line}: invalid coordinates for {site_id}") from exc
            depth = _source_number(row["Sensor Depth (cm)"], source, line, "Sensor Depth (cm)")
            if site_id in BERMS_5CM_SITES and row["Network Name"].strip() == "BERMS":
                # The source BERMS notebook selects SoilTemp_005cm for both sites.
                if depth not in (None, 5.0):
                    raise ValueError(f"{source}:{line}: {site_id} conflicts with BERMS 5 cm source")
                depth = 5.0
            if site_id in {"CP01", "CP02", "CP03", "CP04"}:
                if depth != 10:
                    raise ValueError(f"{source}:{line}: expected 10 cm CP probe length for {site_id}")
                depth, depth_from, depth_to = 5.0, 0.0, 10.0
            else:
                depth_from = depth_to = depth
            result[site_id] = SensorMetadata(
                sensor_id=make_sensor_id("local", site_id, depth_from, depth_to), source="local", latitude=latitude,
                longitude=longitude, site_id=site_id,
                network=row["Network Name"].strip() or None, station=site_id,
                depth_cm=depth, depth_from_cm=depth_from, depth_to_cm=depth_to,
                raw_variable="bulk_edc", source_id=site_id,
                timezone_original=(
                    "UTC in legacy level-0 (unverified; BERMS RData says America/Regina)"
                    if site_id in BERMS_5CM_SITES else "UTC (declared, unverified)"
                ),
            )
    return result


def _write_site(spool: Path, output: Path, site_id: str, source_file: str,
                source_rows: int) -> dict:
    samples: dict[datetime, tuple[float | None, float | None, float | None]] = {}
    duplicates = 0
    with spool.open(newline="", encoding="utf-8") as stream:
        for line, row in enumerate(csv.reader(stream), 1):
            stamp = _source_time(row[0], spool, line)
            values = tuple(_source_number(value, spool, line, column)
                           for value, column in zip(row[1:], ("soil_temp", "soil_moist", "bulk_edc")))
            existing = samples.get(stamp)
            if existing is not None:
                duplicates += 1
                merged = []
                for old, new in zip(existing, values):
                    if old is not None and new is not None and old != new:
                        raise ConflictingSampleError(f"{site_id}: conflicting samples at {stamp}")
                    merged.append(old if old is not None else new)
                samples[stamp] = tuple(merged)
            else:
                samples[stamp] = values
    if not samples:
        raise ValueError(f"no observations for {site_id}")

    hourly: dict[datetime, list[list[float]]] = defaultdict(lambda: [[], [], []])
    for stamp, values in samples.items():
        hour = stamp.replace(minute=0, second=0, microsecond=0)
        for index, value in enumerate(values):
            if value is not None:
                hourly[hour][index].append(value)
    if not hourly:
        raise NoProbeDataError(f"{site_id}: no probe measurements after removing iButton-filled temperature")
    first, last = min(hourly), max(hourly)
    counts = [0, 0, 0]
    total_hours = 0
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(OBSERVATION_COLUMNS)
        hour = first
        while hour <= last:
            buckets = hourly.get(hour, ((), (), ()))
            values = []
            for index, bucket in enumerate(buckets):
                if bucket:
                    counts[index] += 1
                    values.append(format(math.fsum(bucket) / len(bucket), ".15g"))
                else:
                    values.append("NaN")
            writer.writerow((hour.strftime("%Y-%m-%dT%H:00:00Z"), *values))
            total_hours += 1
            hour += timedelta(hours=1)
    return {
        "site_id": site_id, "sensor_id": output.stem,
        "status": "imported", "detail": "",
        "source_file": source_file, "source_rows": source_rows,
        "duplicate_samples": duplicates, "unique_samples": len(samples),
        "observed_hours": len(hourly), "output_hours": total_hours,
        "temperature_hours": counts[0], "moisture_hours": counts[1],
        "raw_hours": counts[2],
        "first_utc": first.strftime("%Y-%m-%dT%H:00:00Z"),
        "last_utc": last.strftime("%Y-%m-%dT%H:00:00Z"),
    }


def import_local(input_dir: str | Path, metadata_path: str | Path,
                 observations_dir: str | Path, sensors_file: str | Path,
                 status_file: str | Path,
                 skip_conflicting_sites: bool = False) -> list[dict]:
    """Split non-NRCan network tables by site into hourly UTC CSVs.

    Subhourly samples are independently averaged for each measurement in the
    containing UTC hour. No interpolation or physical-range filtering occurs.
    Original NRCan NI/NT iButtons must use import-nrcan-ibutton instead.
    Alaska and RISMA sites already represented in ISMN, and Cambridge Bay
    iButtons with a dedicated depth-specific importer, are also excluded.
    Existing outputs are never overwritten.
    """
    source_root = Path(input_dir)
    paths = sorted(source_root.glob("*.csv"))
    if not paths:
        raise ValueError(f"no level-0 CSVs in {source_root}")
    metadata = read_local_metadata(metadata_path)
    observations = Path(observations_dir)
    sensors_output = Path(sensors_file)
    status_output = Path(status_file)
    if sensors_output.exists() or status_output.exists():
        raise FileExistsError("local metadata or status output already exists")
    if observations.exists() and any(observations.glob("local_*.csv")):
        raise FileExistsError(f"local observations already exist in {observations}")
    observations.mkdir(parents=True, exist_ok=True)
    sensors_output.parent.mkdir(parents=True, exist_ok=True)
    status_output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".sfcc-local-", dir=observations) as temporary:
        staging = Path(temporary)
        spool_dir = staging / "spool"
        spool_dir.mkdir()
        counts: dict[str, int] = defaultdict(int)
        source_files = {}
        with ExitStack() as stack:
            writers = {}
            for path in paths:
                with path.open(newline="", encoding="utf-8-sig") as stream:
                    reader = csv.DictReader(stream)
                    if not REQUIRED_SOURCE_COLUMNS.issubset(reader.fieldnames or ()):
                        raise ValueError(f"{path}: missing required level-0 columns")
                    for row in reader:
                        site_id = row["site_id"].strip()
                        if PUBLISHER_IBUTTON_SITE.fullmatch(site_id):
                            continue
                        if site_id not in metadata:
                            raise ValueError(f"{path}:{reader.line_num}: no metadata for {site_id}")
                        if metadata[site_id].network in SEPARATE_SOURCE_NETWORKS:
                            continue
                        if (metadata[site_id].network in SEPARATE_IBUTTON_NETWORKS
                                and metadata[site_id].depth_cm is None):
                            continue
                        if site_id in source_files and source_files[site_id] != path.name:
                            raise ValueError(f"{site_id} appears in multiple network files")
                        source_files[site_id] = path.name
                        if site_id not in writers:
                            handle = stack.enter_context((spool_dir / f"{site_id}.csv").open(
                                "w", newline="", encoding="utf-8"))
                            writers[site_id] = csv.writer(handle)
                        temperature = row["soil_temp"]
                        if (metadata[site_id].network in IBUTTON_FILLED_NETWORKS
                                and _source_number(row["bulk_edc"], path, reader.line_num, "bulk_edc") is None):
                            temperature = ""
                        writers[site_id].writerow((row["datetime"], temperature,
                                                   row["soil_moist"], row["bulk_edc"]))
                        counts[site_id] += 1
                print(f"Local import staged {path.name}: {sum(counts.values())} source rows", flush=True)
        rows = []
        completed = []
        for site_id in sorted(counts):
            output = staging / f"{metadata[site_id].sensor_id}.csv"
            try:
                rows.append(_write_site(spool_dir / f"{site_id}.csv", output, site_id,
                                        source_files[site_id], counts[site_id]))
                completed.append(site_id)
            except NoProbeDataError as exc:
                rows.append({"site_id": site_id, "sensor_id": metadata[site_id].sensor_id,
                             "status": "skipped_no_probe_data", "detail": str(exc),
                             "source_file": source_files[site_id], "source_rows": counts[site_id]})
                print(f"Skipped {site_id}: {exc}", flush=True)
            except ConflictingSampleError as exc:
                if not skip_conflicting_sites:
                    raise
                rows.append({"site_id": site_id, "sensor_id": metadata[site_id].sensor_id,
                             "status": "skipped_conflicting_samples", "detail": str(exc),
                             "source_file": source_files[site_id],
                             "source_rows": counts[site_id]})
                print(f"Skipped {site_id}: {exc}", flush=True)
        staged_sensors = staging / "local_sensors.csv"
        write_metadata(staged_sensors, [metadata[site_id] for site_id in completed])
        staged_status = staging / "local_import_status.csv"
        with staged_status.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=STATUS_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        for site_id in completed:
            name = f"{metadata[site_id].sensor_id}.csv"
            (staging / name).replace(observations / name)
        staged_sensors.replace(sensors_output)
        staged_status.replace(status_output)
    return rows
