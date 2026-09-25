"""Inventory AmeriFlux BASE-BADM archives without modifying source downloads.

BASE timestamps are local standard time. BIF provides the fixed UTC offset and
site coordinates, but not necessarily measurement depths for TS/SWC variables.
"""

import csv
import gzip
import heapq
import io
import math
import os
import re
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

from .io import OBSERVATION_COLUMNS, write_metadata
from .models import SensorMetadata


_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_MEASUREMENT = re.compile(r"^(TS|SWC)(?:_PI)?(?:_\d+(?:_\d+_\d+)?)?$")


@dataclass(frozen=True)
class AmeriFluxArchive:
    path: Path
    site_code: str
    site_name: str
    latitude: float
    longitude: float
    utc_offset_hours: float
    csv_members: tuple[str, ...]
    temperature_columns: tuple[str, ...]
    moisture_columns: tuple[str, ...]
    location_ambiguous: bool


@dataclass(frozen=True)
class AmeriFluxSensor:
    sensor_id: str
    site_id: str
    temperature_column: str
    moisture_column: str | None
    depth_m: float | None
    pairing_method: str


def _bif_fields(data: bytes) -> tuple[dict[str, str], bool]:
    """Read the five-column BADM Interchange Format from its XLSX container."""
    with zipfile.ZipFile(io.BytesIO(data)) as workbook:
        strings = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
            strings = ["".join(item.itertext()) for item in root.findall("x:si", _NS)]
        sheet = ElementTree.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        fields = {}
        location_ambiguous = False
        for row in sheet.findall(".//x:row", _NS):
            values = []
            for cell in row.findall("x:c", _NS):
                value = cell.find("x:v", _NS)
                result = value.text if value is not None and value.text is not None else ""
                if cell.get("t") == "s" and result:
                    result = strings[int(result)]
                elif cell.get("t") == "inlineStr":
                    result = "".join(cell.itertext())
                values.append(result)
            if len(values) >= 5 and values[3] in {
                "SITE_NAME", "LOCATION_LAT", "LOCATION_LONG", "UTC_OFFSET"
            }:
                key = values[3]
                if key in fields and fields[key] != values[4]:
                    if key in {"LOCATION_LAT", "LOCATION_LONG"}:
                        location_ambiguous = True
                    else:
                        raise ValueError(f"conflicting BIF {key}")
                else:
                    fields[key] = values[4]
        return fields, location_ambiguous


def _header(archive: zipfile.ZipFile, member: str) -> list[str]:
    with archive.open(member) as binary:
        with io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as stream:
            for line in stream:
                if line.strip() and not line.startswith("#"):
                    return next(csv.reader([line]))
    raise ValueError(f"missing CSV header: {member}")


def inspect_archive(path: str | Path) -> AmeriFluxArchive:
    path = Path(path)
    match = re.fullmatch(r"AMF_([A-Za-z]{2}-[A-Za-z0-9]+)_BASE-BADM_\d+-\d+\.zip", path.name)
    if match is None:
        raise ValueError("unexpected BASE-BADM archive name")
    site_code = match.group(1)
    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        bif = [name for name in members if name.endswith(".xlsx")]
        csv_files = sorted(name for name in members if re.search(r"_BASE_(?:HH|HR)_.*\.csv$", name))
        if len(bif) != 1 or not csv_files:
            raise ValueError("expected one BIF workbook and at least one BASE HH/HR CSV")
        fields, location_ambiguous = _bif_fields(archive.read(bif[0]))
        try:
            latitude = float(fields["LOCATION_LAT"])
            longitude = float(fields["LOCATION_LONG"])
            utc_offset = float(fields["UTC_OFFSET"])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"missing or invalid BIF location/UTC offset: {exc}") from exc
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180 or not -14 <= utc_offset <= 14:
            raise ValueError("BIF location/UTC offset outside valid range")
        columns = set()
        for member in csv_files:
            header = _header(archive, member)
            if len(header) != len(set(header)) or header[:2] != ["TIMESTAMP_START", "TIMESTAMP_END"]:
                raise ValueError(f"invalid or duplicate CSV columns: {member}")
            columns.update(header)
        temperature = tuple(sorted(name for name in columns if _MEASUREMENT.fullmatch(name)
                                   and name.startswith("TS")))
        moisture = tuple(sorted(name for name in columns if _MEASUREMENT.fullmatch(name)
                                and name.startswith("SWC")))
    return AmeriFluxArchive(path, site_code, fields.get("SITE_NAME", site_code),
                           latitude, longitude, utc_offset, tuple(csv_files),
                           temperature, moisture, location_ambiguous)


def scan_ameriflux(root: str | Path) -> tuple[list[AmeriFluxArchive], list[tuple[str, str]]]:
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(root)
    archives = []
    issues = []
    for path in sorted(root.glob("AMF_*_BASE-BADM_*.zip")):
        try:
            archives.append(inspect_archive(path))
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            issues.append((path.name, str(exc)))
    codes = [item.site_code for item in archives]
    if len(codes) != len(set(codes)):
        raise ValueError("multiple BASE-BADM archives for the same site")
    return archives, issues


def read_measurement_heights(path: str | Path) -> dict[tuple[str, str], tuple[float, ...]]:
    """Return every distinct reported height; changing depths stay ambiguous."""
    heights = defaultdict(set)
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"Site_ID", "Variable", "Height"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("measurement-height CSV lacks Site_ID, Variable, or Height")
        for row in reader:
            if not row["Height"].strip():
                continue
            value = float(row["Height"])
            if not math.isfinite(value):
                raise ValueError("nonfinite measurement height")
            heights[(row["Site_ID"], row["Variable"])].add(value)
    return {key: tuple(sorted(values)) for key, values in heights.items()}


def _soil_depth(heights: dict, site_code: str, column: str) -> float | None:
    values = heights.get((site_code, column), ())
    return -values[0] if len(values) == 1 and values[0] < 0 else None


def pair_ameriflux(archive: AmeriFluxArchive, heights: dict) -> list[AmeriFluxSensor]:
    """Pair only a sole TS and sole SWC at the same documented depth."""
    by_depth = defaultdict(lambda: {"TS": [], "SWC": []})
    for column in archive.temperature_columns:
        depth = _soil_depth(heights, archive.site_code, column)
        if depth is not None:
            by_depth[depth]["TS"].append(column)
    for column in archive.moisture_columns:
        depth = _soil_depth(heights, archive.site_code, column)
        if depth is not None:
            by_depth[depth]["SWC"].append(column)
    matches = {}
    for depth, columns in by_depth.items():
        if len(columns["TS"]) == len(columns["SWC"]) == 1:
            matches[columns["TS"][0]] = columns["SWC"][0]
    result = []
    site_id = f"ameriflux_{archive.site_code}"
    for column in archive.temperature_columns:
        depth = _soil_depth(heights, archive.site_code, column)
        moisture = matches.get(column)
        result.append(AmeriFluxSensor(
            f"{site_id}_{column}", site_id, column, moisture, depth,
            "sole_at_depth" if moisture else "temperature_only"
        ))
    return result


def sensor_metadata(archive: AmeriFluxArchive, sensor: AmeriFluxSensor) -> SensorMetadata:
    depth_cm = sensor.depth_m * 100 if sensor.depth_m is not None else None
    return SensorMetadata(
        sensor_id=sensor.sensor_id, source="ameriflux", site_id=sensor.site_id,
        network="AmeriFlux", station=archive.site_name,
        latitude=archive.latitude, longitude=archive.longitude,
        depth_cm=depth_cm, depth_from_cm=depth_cm, depth_to_cm=depth_cm,
        source_id=archive.site_code,
        source_url=f"https://ameriflux.lbl.gov/sites/siteinfo/{archive.site_code}",
        timezone_original=f"UTC{archive.utc_offset_hours:+g} local standard time",
        soil_moisture_method="AmeriFlux BASE volumetric SWC divided by 100"
        if sensor.moisture_column else None,
    )


def write_ameriflux_inventory(output_dir: str | Path, archives: list[AmeriFluxArchive],
                              heights: dict, issues: list[tuple[str, str]]) -> None:
    output = Path(output_dir)
    names = ("ameriflux_sites.csv", "ameriflux_sensors.csv", "ameriflux_pairing.csv",
             "ameriflux_scan_issues.csv")
    if any((output / name).exists() for name in names):
        raise FileExistsError("AmeriFlux inventory already exists")
    output.mkdir(parents=True, exist_ok=True)
    northern = [item for item in archives if item.latitude >= 0 and item.temperature_columns]
    sensors = [(archive, sensor) for archive in northern
               for sensor in pair_ameriflux(archive, heights)]
    write_metadata(output / "ameriflux_sensors.csv",
                   [sensor_metadata(archive, sensor) for archive, sensor in sensors])
    with (output / "ameriflux_sites.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("site_id", "site_code", "site_name", "latitude", "longitude",
                         "utc_offset_hours", "location_ambiguous", "source_archive"))
        for archive in northern:
            writer.writerow((f"ameriflux_{archive.site_code}", archive.site_code,
                             archive.site_name, archive.latitude, archive.longitude,
                             archive.utc_offset_hours, archive.location_ambiguous,
                             archive.path.name))
    with (output / "ameriflux_pairing.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("sensor_id", "site_id", "temperature_column", "moisture_column",
                         "depth_m", "pairing_method", "temperature_height_values",
                         "moisture_height_values"))
        for archive, sensor in sensors:
            writer.writerow((sensor.sensor_id, sensor.site_id, sensor.temperature_column,
                             sensor.moisture_column or "", sensor.depth_m if sensor.depth_m is not None else "",
                             sensor.pairing_method,
                             "|".join(map(str, heights.get((archive.site_code, sensor.temperature_column), ()))),
                             "|".join(map(str, heights.get((archive.site_code, sensor.moisture_column), ())))
                             if sensor.moisture_column else ""))
    with (output / "ameriflux_scan_issues.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("archive", "issue"))
        writer.writerows(issues)


def _parse_local_timestamp(value: str, offset: timedelta) -> datetime:
    local = datetime.strptime(value, "%Y%m%d%H%M")
    return (local - offset).replace(tzinfo=timezone.utc)


def _iter_source_rows(archive: zipfile.ZipFile, member: str, offset: timedelta,
                      selected: set[str], parse_stats: dict[str, int]):
    kind = "HH" if "_BASE_HH_" in member else "HR"
    with archive.open(member) as binary:
        with io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(line for line in stream if line.strip() and not line.startswith("#"))
            header = next(reader)
            positions = {column: header.index(column) for column in selected if column in header}
            previous = None
            for line_number, row in enumerate(reader, 1):
                if len(row) != len(header):
                    raise ValueError(f"{member} row {line_number}: wrong column count")
                start = _parse_local_timestamp(row[0], offset)
                end = _parse_local_timestamp(row[1], offset)
                if not start < end <= start + timedelta(hours=1) or previous is not None and start < previous:
                    raise ValueError(f"{member} row {line_number}: nonchronological or invalid interval")
                previous = start
                values = {}
                for column, position in positions.items():
                    try:
                        value = float(row[position])
                    except ValueError:
                        parse_stats["invalid_numeric_cells"] += 1
                        continue
                    if math.isfinite(value) and value != -9999:
                        values[column] = value
                yield start, end, kind, values


def _source_hours(archive: AmeriFluxArchive, selected: set[str], parse_stats: dict[str, int]):
    offset = timedelta(hours=archive.utc_offset_hours)
    with zipfile.ZipFile(archive.path) as source:
        streams = [_iter_source_rows(source, member, offset, selected, parse_stats)
                   for member in archive.csv_members]
        yield from heapq.merge(*streams, key=lambda item: item[0])


def _hour_floor(instant: datetime) -> datetime:
    return instant.replace(minute=0, second=0, microsecond=0)


def _format(value: float | None) -> str:
    return "NaN" if value is None else str(value)


def import_ameriflux_site(archive: AmeriFluxArchive, sensors: list[AmeriFluxSensor],
                          observations_dir: str | Path, flags_dir: str | Path,
                          start: datetime | None = None, end: datetime | None = None) -> tuple[int, int]:
    """Stream source intervals into UTC hourly CSVs; HH wins over overlapping HR."""
    if not sensors:
        return 0, 0
    observations_dir, flags_dir = Path(observations_dir), Path(flags_dir)
    observations_dir.mkdir(parents=True, exist_ok=True)
    flags_dir.mkdir(parents=True, exist_ok=True)
    selected = {item.temperature_column for item in sensors}
    selected.update(item.moisture_column for item in sensors if item.moisture_column)
    parse_stats = {"invalid_numeric_cells": 0}
    temporary = []
    outputs = []
    try:
        for sensor in sensors:
            obs_path = observations_dir / f"{sensor.sensor_id}.csv"
            flag_path = flags_dir / f"{sensor.sensor_id}.csv.gz"
            if obs_path.exists() or flag_path.exists():
                raise FileExistsError(f"output already exists for {sensor.sensor_id}")
            obs_fd, obs_temp = tempfile.mkstemp(prefix=f".{sensor.sensor_id}.", suffix=".tmp",
                                                dir=observations_dir)
            flag_fd, flag_temp = tempfile.mkstemp(prefix=f".{sensor.sensor_id}.", suffix=".tmp",
                                                  dir=flags_dir)
            os.close(obs_fd)
            os.close(flag_fd)
            temporary.extend((obs_temp, flag_temp))
            outputs.append((sensor, obs_path, flag_path, obs_temp, flag_temp))
        from contextlib import ExitStack
        with ExitStack() as stack:
            writers = []
            for sensor, _, _, obs_temp, flag_temp in outputs:
                obs_writer = csv.writer(stack.enter_context(open(obs_temp, "w", newline="", encoding="utf-8")))
                flag_writer = csv.writer(stack.enter_context(gzip.open(flag_temp, "wt", newline="", encoding="utf-8")))
                obs_writer.writerow(OBSERVATION_COLUMNS)
                flag_writer.writerow(("timestamp_utc", "temperature_source_minutes",
                                      "moisture_source_minutes", "temperature_column",
                                      "moisture_column"))
                writers.append((sensor, obs_writer, flag_writer))
            buckets = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0.0, 0.0])))
            next_hour = None
            last_hour = None
            row_count = 0

            def emit(hour):
                nonlocal row_count
                bucket = buckets.pop(hour, {})
                stamp = hour.strftime("%Y-%m-%dT%H:00:00Z")
                for sensor, obs_writer, flag_writer in writers:
                    def measured(column):
                        if column is None:
                            return None, 0
                        sources = bucket.get(column, {})
                        weighted, minutes = sources.get("HH", [0.0, 0.0])
                        if minutes == 0:
                            weighted, minutes = sources.get("HR", [0.0, 0.0])
                        return (weighted / minutes if minutes else None), minutes
                    temperature, ts_minutes = measured(sensor.temperature_column)
                    moisture, sm_minutes = measured(sensor.moisture_column)
                    if moisture is not None:
                        moisture /= 100  # AmeriFlux BASE SWC is volumetric percent.
                    obs_writer.writerow((stamp, _format(temperature), _format(moisture), "NaN"))
                    flag_writer.writerow((stamp, _format(ts_minutes), _format(sm_minutes),
                                          sensor.temperature_column, sensor.moisture_column or ""))
                row_count += 1

            for interval_start, interval_end, kind, values in _source_hours(archive, selected, parse_stats):
                if end is not None and interval_start >= end:
                    break
                if start is not None and interval_end <= start:
                    continue
                interval_start = max(interval_start, start) if start is not None else interval_start
                interval_end = min(interval_end, end) if end is not None else interval_end
                if next_hour is not None:
                    while next_hour + timedelta(hours=1) <= interval_start:
                        emit(next_hour)
                        next_hour += timedelta(hours=1)
                cursor = interval_start
                while cursor < interval_end:
                    hour = _hour_floor(cursor)
                    boundary = min(hour + timedelta(hours=1), interval_end)
                    minutes = (boundary - cursor).total_seconds() / 60
                    if next_hour is None:
                        next_hour = hour
                    last_hour = hour
                    for column, value in values.items():
                        accumulator = buckets[hour][column][kind]
                        accumulator[0] += value * minutes
                        accumulator[1] += minutes
                    cursor = boundary
            if next_hour is not None and last_hour is not None:
                while next_hour <= last_hour:
                    emit(next_hour)
                    next_hour += timedelta(hours=1)
        if row_count:
            for _, obs_path, flag_path, obs_temp, flag_temp in outputs:
                os.replace(obs_temp, obs_path)
                os.replace(flag_temp, flag_path)
        return row_count, parse_stats["invalid_numeric_cells"]
    finally:
        for path in temporary:
            if os.path.exists(path):
                os.unlink(path)
