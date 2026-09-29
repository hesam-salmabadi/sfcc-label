"""Import ORNL DAAC 2123 logger temperature and calibrated CS625 moisture.

The dataset guide does not state the logger clock time zone. UTC offsets must
be supplied explicitly; the importer never silently treats source time as UTC.
"""

from __future__ import annotations

import csv
import math
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .io import OBSERVATION_COLUMNS, write_metadata
from .models import SensorMetadata
from .naming import sensor_id as make_sensor_id


CONTEXT_COLUMNS = ("sensor_id", "area", "logger_id", "source_file", "source_column",
                   "raw_column", "probe_metadata_file", "time_basis", "time_basis_evidence",
                   "source_rows", "valid_hours", "duplicate_hour_samples", "first_utc", "last_utc")
STATUS_COLUMNS = ("area", "logger_id", "status", "source_rows", "sensor_count",
                  "duplicate_hour_rows", "detail")


def _number(value: str) -> float | None:
    if value.strip().lower() in {"", "na", "nan", "-9999"}:
        return None
    number = float(value)
    return number if math.isfinite(number) and number != -9999 else None


def _write_hourly(path: Path, buckets: dict[datetime, list[list[float]]]):
    first, last = min(buckets), max(buckets)
    nonmissing = 0
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(OBSERVATION_COLUMNS)
        hour = first
        while hour <= last:
            cols = buckets.get(hour, [[], [], []])
            means = [math.fsum(col) / len(col) if col else None for col in cols]
            nonmissing += any(value is not None for value in means)
            writer.writerow((hour.strftime("%Y-%m-%dT%H:00:00Z"),
                             *("NaN" if value is None else format(value, ".15g")
                               for value in means)))
            hour += timedelta(hours=1)
    return first.strftime("%Y-%m-%dT%H:00:00Z"), last.strftime("%Y-%m-%dT%H:00:00Z"), nonmissing


def import_above_moisture(source_root: str | Path, observations_dir: str | Path,
                          sensors_file: str | Path, context_file: str | Path,
                          status_file: str | Path, *, alaska_utc_offset_hours: int,
                          alberta_utc_offset_hours: int, time_basis_evidence: str) -> list[dict]:
    """Write per-probe moisture and separate logger temperature UTC streams."""
    if not time_basis_evidence.strip():
        raise ValueError("source clock offset evidence is required")
    offsets = {"Alaska": alaska_utc_offset_hours, "Alberta": alberta_utc_offset_hours}
    if any(not isinstance(value, int) or not -12 <= value <= 14 for value in offsets.values()):
        raise ValueError("UTC offsets must be whole hours between -12 and +14")
    root = Path(source_root)
    data_dir = root / "data"
    probe_file = data_dir / "probe_specific_soil_profile_model_coefficients.csv"
    by_logger = defaultdict(dict)
    with probe_file.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            area, logger, probe = row["area"], *row["probe"].split("-")
            if area not in offsets or not probe.isdigit() or int(probe) not in (1, 2, 3, 4):
                raise ValueError(f"invalid probe metadata identity: {row['probe']}")
            key = (area, logger)
            if int(probe) in by_logger[key]:
                raise ValueError(f"duplicate probe metadata: {key} probe {probe}")
            by_logger[key][int(probe)] = row
    if any(set(probes) != {1, 2, 3, 4} for probes in by_logger.values()):
        raise ValueError("each logger must have four probe metadata rows")
    destinations = (Path(observations_dir), Path(sensors_file), Path(context_file), Path(status_file))
    if any(path.exists() for path in destinations):
        raise FileExistsError("ABoVE moisture output already exists")
    for path in destinations:
        path.parent.mkdir(parents=True, exist_ok=True)
    sensors, contexts, statuses = [], [], []
    with tempfile.TemporaryDirectory(prefix=".sfcc-above-moisture-", dir=Path(observations_dir).parent) as temp:
        stage = Path(temp)
        for area, offset in offsets.items():
            path = data_dir / f"{area.lower()}_probe_period_temp_cal_vmc.csv"
            streams = defaultdict(lambda: defaultdict(lambda: [[], [], []]))
            row_counts = Counter()
            repeated = Counter()
            seen_hours = defaultdict(set)
            unknown = Counter()
            with path.open(newline="", encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                for line, row in enumerate(reader, 2):
                    logger = row["probe_id"].strip()
                    if (area, logger) not in by_logger:
                        unknown[logger] += 1
                        continue
                    if row["time_stamp"].strip().lower() in {"", "na"}:
                        continue
                    local = datetime.strptime(row["time_stamp"], "%Y-%m-%d %H:%M:%S")
                    utc = local - timedelta(hours=offset)
                    hour = utc.replace(minute=0, second=0, microsecond=0)
                    row_counts[logger] += 1
                    if hour in seen_hours[logger]:
                        repeated[logger] += 1
                    seen_hours[logger].add(hour)
                    temperature = _number(row["t109_c_avg"])
                    if temperature is not None:
                        streams[(logger, 0)][hour][0].append(temperature)
                    for probe in range(1, 5):
                        raw = _number(row[f"pa_us_avg_{probe}"])
                        moisture = _number(row[f"probe{probe}_cal"])
                        bucket = streams[(logger, probe)][hour]
                        if moisture is not None:
                            bucket[1].append(moisture / 100)
                        if raw is not None:
                            bucket[2].append(raw)
            for (key_area, logger), probes in sorted(by_logger.items()):
                if key_area != area:
                    continue
                site = f"{area}-{logger}"
                latitudes = {float(x["latitude"]) for x in probes.values()}
                longitudes = {float(x["longitude"]) for x in probes.values()}
                if len(latitudes) != 1 or len(longitudes) != 1:
                    raise ValueError(f"{site}: probe coordinates disagree")
                latitude, longitude = latitudes.pop(), longitudes.pop()
                sensor_count = 0
                for probe in range(5):
                    buckets = streams.get((logger, probe))
                    if not buckets:
                        continue
                    if probe == 0:
                        depth = None
                        sensor_id = make_sensor_id("above_moisture", site, None, tag="t109")
                        source_column, raw_column = "t109_c_avg", ""
                    else:
                        depth = float(probes[probe]["depth_cm"])
                        sensor_id = make_sensor_id("above_moisture", site, 0.0, depth,
                                                   tag=f"p{probe}")
                        source_column = f"probe{probe}_cal"
                        raw_column = f"pa_us_avg_{probe}"
                    first, last, valid_hours = _write_hourly(stage / f"{sensor_id}.csv", buckets)
                    sensors.append(SensorMetadata(
                        sensor_id=sensor_id, source="above_moisture", latitude=latitude,
                        longitude=longitude, site_id=site, network="ABoVE Alaska Alberta",
                        station=logger, depth_cm=depth / 2 if probe else None,
                        depth_from_cm=0.0 if probe else None,
                        depth_to_cm=depth, raw_variable="CS625_period" if probe else None,
                        raw_unit="microsecond" if probe else None,
                        source_id=f"{logger}-{probe}" if probe else logger,
                        source_url="https://doi.org/10.3334/ORNLDAAC/2123",
                        timezone_original=f"UTC{offset:+d} (owner-supplied clock basis)",
                        soil_moisture_method="source calibrated VMC percent / 100" if probe else None,
                        soil_temperature_sensor_type="Campbell 109" if probe == 0 else None,
                        soil_moisture_sensor_type="Campbell CS625" if probe else None,
                        sensor_type_source="ORNL DAAC 2123 user guide",
                        sensor_type_note="temperature depth unspecified" if probe == 0 else
                                         "30 cm rods span surface to installation depth"))
                    contexts.append({"sensor_id": sensor_id, "area": area, "logger_id": logger,
                                     "source_file": str(path), "source_column": source_column,
                                     "raw_column": raw_column, "probe_metadata_file": str(probe_file),
                                     "time_basis": f"source fixed UTC{offset:+d}; convert to UTC",
                                     "time_basis_evidence": time_basis_evidence,
                                     "source_rows": row_counts[logger], "valid_hours": valid_hours,
                                     "duplicate_hour_samples": repeated[logger],
                                     "first_utc": first, "last_utc": last})
                    sensor_count += 1
                statuses.append({"area": area, "logger_id": logger,
                                 "status": "imported" if sensor_count else "no_data",
                                 "source_rows": row_counts[logger], "sensor_count": sensor_count,
                                 "duplicate_hour_rows": repeated[logger], "detail": ""})
            for logger, count in sorted(unknown.items()):
                statuses.append({"area": area, "logger_id": logger or "<blank>",
                                 "status": "missing_probe_metadata", "source_rows": count,
                                 "sensor_count": 0, "duplicate_hour_rows": "",
                                 "detail": "source logger has no depth/coordinate mapping"})
        if len({s.sensor_id for s in sensors}) != len(sensors):
            raise ValueError("duplicate sensor IDs")
        write_metadata(stage / "sensors.csv", sensors)
        for name, columns, records in (("context.csv", CONTEXT_COLUMNS, contexts),
                                       ("status.csv", STATUS_COLUMNS, statuses)):
            with (stage / name).open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows(records)
        output = Path(observations_dir)
        output.mkdir()
        for sensor in sensors:
            (stage / f"{sensor.sensor_id}.csv").replace(output / f"{sensor.sensor_id}.csv")
        (stage / "sensors.csv").replace(sensors_file)
        (stage / "context.csv").replace(context_file)
        (stage / "status.csv").replace(status_file)
    return statuses
