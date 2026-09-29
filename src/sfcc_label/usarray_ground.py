"""Import the two ORNL DAAC USArray soil-temperature releases.

Both releases are kept as separate streams, including their shared sites.
Source times are interpreted as Alaska standard time (UTC-9), as stated in
both dataset guides. The original clock labels are retained in context.
"""

from __future__ import annotations

import csv
import math
import re
import tempfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .io import OBSERVATION_COLUMNS, write_metadata
from .models import SensorMetadata
from .naming import sensor_id as make_sensor_id


ALIASES_1767 = {"C17K-1": "C17K", "C26-A": "C26A"}
ALIASES_1680 = {"A19K-1": "A19-1", "A22K-2": "A22-2", "K13K-1": "K13-1"}
FILE_RE = re.compile(r"(.+?)_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.csv$")
DEPTH_RE = re.compile(r"tsoil_(-?(?:\d+(?:\.\d*)?|\.\d+))m?", re.I)
CONTEXT_COLUMNS = ("sensor_id", "release", "source_file", "source_column",
                   "source_column_position", "source_site", "site_metadata_file",
                   "time_basis", "rounding", "source_rows", "valid_samples",
                   "duplicate_hour_samples", "unparseable_timestamps", "missing_values",
                   "first_utc", "last_utc")
STATUS_COLUMNS = ("source_file", "source_site", "status", "detail", "source_rows",
                  "unparseable_timestamps", "imported_sensors", "unknown_depth_sensors",
                  "above_ground_columns_skipped")


def _site_metadata(path: Path, release: str) -> dict[str, dict]:
    key = "site" if release == "1680" else "USAR_Site"
    result = {}
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as stream:
        for row in csv.DictReader(stream):
            site = row[key].strip()
            if not site:
                raise ValueError("missing site metadata ID")
            if site in result:
                # D23K-1 has two logger deployments and two metadata rows.
                lat = "latitude" if release == "1680" else "Latitude_WGS84"
                lon = "longitude" if release == "1680" else "Longitude_WGS84"
                if (row[lat], row[lon]) != (result[site][lat], result[site][lon]):
                    raise ValueError(f"conflicting site coordinates: {site}")
                continue
            result[site] = row
    return result


def _columns(header: list[str]):
    result = []
    skipped_above_ground = 0
    for position, name in enumerate(header):
        normalized = name.strip()
        if not normalized.lower().startswith("tsoil_"):
            continue
        if "nan" in normalized.lower():
            depth = None
        elif match := DEPTH_RE.fullmatch(normalized):
            depth = float(match[1]) * 100
            if depth < 0:
                skipped_above_ground += 1
                continue
        else:
            raise ValueError(f"unrecognized soil temperature column: {name!r}")
        result.append((position, name, depth))
    if not result:
        raise ValueError("no ground temperature columns")
    return result, skipped_above_ground


def _number(value: str) -> float | None:
    if value.strip().lower() in {"", "na", "nan", "-9999"}:
        return None
    number = float(value)
    return number if math.isfinite(number) and number != -9999 else None


def _write_hourly(path: Path, values: dict[datetime, float]):
    first, last = min(values), max(values)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(OBSERVATION_COLUMNS)
        hour = first
        while hour <= last:
            value = values.get(hour)
            writer.writerow((hour.strftime("%Y-%m-%dT%H:00:00Z"),
                             "NaN" if value is None else format(value, ".15g"), "NaN", "NaN"))
            hour += timedelta(hours=1)
    return first.strftime("%Y-%m-%dT%H:00:00Z"), last.strftime("%Y-%m-%dT%H:00:00Z")


def import_usarray_ground(source_root: str | Path, observations_dir: str | Path,
                          sensors_file: str | Path, context_file: str | Path,
                          status_file: str | Path, *, release: str,
                          skip_ambiguous_clock_files: bool = False) -> list[dict]:
    """Write separate UTC-hourly streams for each retained source column."""
    if release not in {"1680", "1767"}:
        raise ValueError("release must be 1680 or 1767")
    root = Path(source_root)
    metadata_path = root / ("data/USArray_Sites.csv" if release == "1680"
                            else "comp/USArray_site_metadata.csv")
    metadata = _site_metadata(metadata_path, release)
    files = sorted(p for p in (root / "data").glob("*.csv")
                   if not p.name.startswith("._") and FILE_RE.fullmatch(p.name))
    if not files:
        raise ValueError(f"release {release}: no source temperature files")
    destinations = (Path(observations_dir), Path(sensors_file), Path(context_file), Path(status_file))
    if any(p.exists() for p in destinations):
        raise FileExistsError("USArray output already exists")
    for path in destinations:
        path.parent.mkdir(parents=True, exist_ok=True)
    source = "usarray_ground" if release == "1680" else "ak_profiles"
    aliases = ALIASES_1680 if release == "1680" else ALIASES_1767
    sensors, contexts, statuses = [], [], []
    with tempfile.TemporaryDirectory(prefix=f".sfcc-usarray-{release}-", dir=Path(observations_dir).parent) as temp:
        stage = Path(temp)
        for path in files:
            source_site = FILE_RE.fullmatch(path.name)[1]
            site = aliases.get(source_site, source_site)
            if site not in metadata:
                raise ValueError(f"{path}: missing site metadata for {site}")
            with path.open(newline="", encoding="utf-8-sig", errors="replace") as stream:
                reader = csv.reader(stream)
                header = next(reader)
                columns, skipped = _columns(header)
                values = {position: {} for position, _, _ in columns}
                missing = Counter()
                duplicates = Counter()
                seen_local_times = set()
                ambiguous = None
                rows = bad_times = 0
                for line, row in enumerate(reader, start=2):
                    rows += 1
                    if len(row) != len(header):
                        raise ValueError(f"{path}:{line}: wrong column count")
                    try:
                        local = datetime.strptime(row[0].strip(), "%Y-%m-%d %H:%M")
                    except ValueError:
                        bad_times += 1
                        continue
                    if (release == "1680" and local in seen_local_times and
                            local.replace(tzinfo=ZoneInfo("America/Anchorage"), fold=0).utcoffset() !=
                            local.replace(tzinfo=ZoneInfo("America/Anchorage"), fold=1).utcoffset()):
                        ambiguous = (
                            f"{path}:{line}: repeated clock hour at daylight saving transition "
                            "contradicts source AKST label; UTC is ambiguous")
                        if not skip_ambiguous_clock_files:
                            raise ValueError(ambiguous)
                        break
                    seen_local_times.add(local)
                    hour = (local + timedelta(hours=9, minutes=30)).replace(
                        minute=0, second=0, microsecond=0)
                    for position, _, _ in columns:
                        value = _number(row[position])
                        if value is None:
                            missing[position] += 1
                            continue
                        bucket = values[position].setdefault(hour, [])
                        if bucket:
                            duplicates[position] += 1
                        bucket.append(value)
            if ambiguous:
                statuses.append({"source_file": str(path), "source_site": site,
                                 "status": "clock_ambiguous_excluded", "detail": ambiguous,
                                 "source_rows": rows, "unparseable_timestamps": bad_times,
                                 "imported_sensors": 0, "unknown_depth_sensors": 0,
                                 "above_ground_columns_skipped": skipped})
                continue
            lat_key = "latitude" if release == "1680" else "Latitude_WGS84"
            lon_key = "longitude" if release == "1680" else "Longitude_WGS84"
            latitude = float(metadata[site][lat_key])
            longitude = float(metadata[site][lon_key])
            deployment = path.name.split("_", 1)[1][:10] if source_site == "D23K-1" else ""
            imported = unknown = 0
            for position, name, depth in columns:
                if not values[position]:
                    continue
                hourly = {hour: math.fsum(bucket) / len(bucket)
                          for hour, bucket in values[position].items()}
                tag = f"{deployment}c{position}" if deployment else f"c{position}"
                sensor_id = make_sensor_id(source, site, depth, tag=tag)
                first, last = _write_hourly(stage / f"{sensor_id}.csv", hourly)
                sensors.append(SensorMetadata(
                    sensor_id=sensor_id, source=source, latitude=latitude,
                    longitude=longitude, site_id=site, network="USArray",
                    station=site, depth_cm=depth, depth_from_cm=depth,
                    depth_to_cm=depth, source_id=f"{source_site}:{position}:{name.strip()}",
                    source_url=f"https://doi.org/10.3334/ORNLDAAC/{release}",
                    timezone_original="AKST (fixed UTC-9)",
                    soil_temperature_sensor_type="HOBO temperature probe",
                    sensor_type_source=f"ORNL DAAC {release} user guide",
                    sensor_type_note="Depth absent in source column" if depth is None else None))
                contexts.append({"sensor_id": sensor_id, "release": release,
                                 "source_file": str(path), "source_column": name,
                                 "source_column_position": position, "source_site": source_site,
                                 "site_metadata_file": str(metadata_path),
                                 "time_basis": "AKST fixed UTC-9; add 9 hours",
                                 "rounding": "nearest UTC hour, half-hour upward",
                                 "source_rows": rows,
                                 "valid_samples": sum(map(len, values[position].values())),
                                 "duplicate_hour_samples": duplicates[position],
                                 "unparseable_timestamps": bad_times,
                                 "missing_values": missing[position],
                                 "first_utc": first, "last_utc": last})
                imported += 1
                unknown += depth is None
            statuses.append({"source_file": str(path), "source_site": site,
                             "status": "imported", "detail": "",
                             "source_rows": rows, "unparseable_timestamps": bad_times,
                             "imported_sensors": imported, "unknown_depth_sensors": unknown,
                             "above_ground_columns_skipped": skipped})
        if len({s.sensor_id for s in sensors}) != len(sensors):
            raise ValueError("duplicate standardized sensor ID")
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
