"""Import the original NRCan Open File 66 iButton temperature records.

The source samples are nominally 255 minutes apart. Standardized hourly slots
without an actual sample remain missing; this module does not interpolate.
"""

from __future__ import annotations

import csv
import math
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .io import OBSERVATION_COLUMNS, write_metadata
from .models import SensorMetadata
from .naming import sensor_id as make_sensor_id


SOURCE_URL = "https://doi.org/10.4095/329207"
NOMINAL_DEPTH_CM = 13.0
SAMPLE_INTERVAL_MINUTES = 255
FILENAME_SITE_CORRECTIONS = {
    "T18_DD_36BF0221.csv": "T16",
    "T36_7A_36CA7521.csv": "T35",
}
CONTEXT_COLUMNS = (
    "sensor_id", "site_id", "organic_layer_cm", "depth_below_surface_cm",
    "estimated_interface_offset_cm", "estimated_medium", "raw_filename",
    "device_registration", "depth_source", "site_data_source",
)
STATUS_COLUMNS = (
    "sensor_id", "site_id", "raw_filename", "device_registration",
    "source_samples", "sampled_hours", "output_hours", "ambiguous_local_times",
    "site_id_corrected", "first_utc", "last_utc",
)
XML_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


@dataclass(frozen=True)
class PublisherSite:
    code: str
    latitude: float
    longitude: float
    organic_layer_cm: float


def read_site_data(path: str | Path) -> dict[str, PublisherSite]:
    """Read site coordinates and 2016 surface organic-layer thickness."""
    source = Path(path)
    with zipfile.ZipFile(source) as archive:
        strings_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = ["".join(item.itertext()) for item in strings_root.findall("m:si", XML_NS)]
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    result = {}
    for row in sheet.findall(".//m:sheetData/m:row", XML_NS):
        cells = {}
        for cell in row.findall("m:c", XML_NS):
            value = cell.find("m:v", XML_NS)
            if value is None or value.text is None:
                continue
            column = re.match(r"[A-Z]+", cell.attrib["r"]).group()
            cells[column] = (strings[int(value.text)] if cell.attrib.get("t") == "s"
                             else value.text)
        code = cells.get("A", "")
        if not re.fullmatch(r"[IT]\d+", code):
            continue
        if code in result:
            raise ValueError(f"duplicate site in {source}: {code}")
        latitude = float(cells["C"])
        longitude = -abs(float(cells["D"]))
        organic = float(cells["G"])
        if not (0 <= organic < 1000):
            raise ValueError(f"invalid organic-layer thickness for {code}")
        result[code] = PublisherSite(code, latitude, longitude, organic)
    if not result:
        raise ValueError(f"no site records in {source}")
    return result


def _utc_candidates(local: datetime, zone: ZoneInfo) -> list[datetime]:
    candidates = []
    for fold in (0, 1):
        aware = local.replace(tzinfo=zone, fold=fold)
        utc = aware.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) == local and utc not in candidates:
            candidates.append(utc)
    return sorted(candidates)


def _resolve_local_time(local: datetime, zone: ZoneInfo,
                        previous: datetime | None, path: Path) -> tuple[datetime, bool]:
    candidates = _utc_candidates(local, zone)
    if not candidates:
        raise ValueError(f"{path}: nonexistent local time {local}")
    if len(candidates) == 1:
        selected = candidates[0]
        if previous is not None and selected <= previous:
            raise ValueError(f"{path}: non-increasing source times at {local}")
        return selected, False
    if previous is None:
        raise ValueError(f"{path}: ambiguous first local time {local}")
    choices = [(abs((candidate - previous).total_seconds() / 60 - SAMPLE_INTERVAL_MINUTES),
                candidate) for candidate in candidates if candidate > previous]
    if not choices:
        raise ValueError(f"{path}: ambiguous local time cannot follow previous at {local}")
    choices.sort()
    if len(choices) > 1 and choices[0][0] == choices[1][0]:
        raise ValueError(f"{path}: cannot resolve ambiguous local time {local}")
    return choices[0][1], True


def read_raw_samples(path: str | Path) -> tuple[str, list[tuple[datetime, float]], int]:
    """Read native local timestamps, resolving DST folds by logger cadence."""
    source = Path(path)
    zone = ZoneInfo("America/Toronto")
    with source.open(encoding="utf-8", errors="replace", newline="") as stream:
        lines = stream.readlines()
    if len(lines) < 16 or not lines[1].startswith("1-Wire/iButton Registration Number:"):
        raise ValueError(f"{source}: unexpected iButton header")
    registration = lines[1].split(":", 1)[1].strip()
    if not re.fullmatch(r"[0-9A-F]{16}", registration):
        raise ValueError(f"{source}: invalid registration number")
    reader = csv.reader(lines[14:])
    if next(reader, None) != ["Date/Time", "Unit", "Value"]:
        raise ValueError(f"{source}: unexpected observation columns")
    samples = []
    previous = None
    ambiguous = 0
    for line_number, row in enumerate(reader, 16):
        if not row:
            continue
        if len(row) != 3 or row[1] != "C":
            raise ValueError(f"{source}:{line_number}: invalid temperature row")
        try:
            local = datetime.strptime(row[0], "%d/%m/%y %I:%M:%S %p")
            value = float(row[2])
        except ValueError as exc:
            raise ValueError(f"{source}:{line_number}: invalid date or temperature") from exc
        if not math.isfinite(value):
            raise ValueError(f"{source}:{line_number}: nonfinite temperature")
        utc, resolved = _resolve_local_time(local, zone, previous, source)
        ambiguous += resolved
        samples.append((utc, value))
        previous = utc
    if not samples:
        raise ValueError(f"{source}: no temperature samples")
    return registration, samples, ambiguous


def _site_code(path: Path) -> tuple[str, bool]:
    match = re.fullmatch(r"([IT])(\d+)_([0-9A-F]{2})_([0-9A-F]{8})\.csv", path.name)
    if not match:
        raise ValueError(f"unexpected iButton filename: {path.name}")
    original = f"{match[1]}{int(match[2])}"
    corrected = FILENAME_SITE_CORRECTIONS.get(path.name, original)
    return corrected, corrected != original


def _sensor_id(code: str) -> str:
    return make_sensor_id("nrcan_ibutton", f"N{code[0]}{int(code[1:]):02d}", NOMINAL_DEPTH_CM)


def _write_hourly(path: Path, samples: list[tuple[datetime, float]]) -> tuple[int, int, str, str]:
    buckets = defaultdict(list)
    for stamp, value in samples:
        hour = stamp.replace(minute=0, second=0, microsecond=0)
        buckets[hour].append(value)
    first, last = min(buckets), max(buckets)
    count = 0
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(OBSERVATION_COLUMNS)
        current = first
        while current <= last:
            values = buckets.get(current)
            temperature = format(math.fsum(values) / len(values), ".15g") if values else "NaN"
            writer.writerow((current.strftime("%Y-%m-%dT%H:00:00Z"),
                             temperature, "NaN", "NaN"))
            count += 1
            current += timedelta(hours=1)
    return len(buckets), count, first.isoformat(), last.isoformat()


def import_nrcan_ibutton(package_root: str | Path, observations_dir: str | Path,
                         sensors_file: str | Path, context_file: str | Path,
                         status_file: str | Path) -> list[dict]:
    """Import 107 published logger streams without copying observations between hours."""
    root = Path(package_root)
    sites = read_site_data(root / "Site_data.xlsx")
    paths = sorted((*((root / "iButton_Records/Boreal_area").glob("*.csv")),
                    *((root / "iButton_Records/Tundra_area").glob("*.csv"))))
    if not paths:
        raise ValueError(f"no publisher iButton records in {root}")
    destinations = [Path(observations_dir), Path(sensors_file),
                    Path(context_file), Path(status_file)]
    if any(path.exists() for path in destinations):
        raise FileExistsError("publisher output already exists; use a new destination")
    ids = [_site_code(path)[0] for path in paths]
    if len(ids) != len(set(ids)):
        raise ValueError("multiple raw files map to the same publisher site")
    missing = set(ids) - set(sites)
    if missing:
        raise ValueError(f"no Site_data.xlsx records for {sorted(missing)}")
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sfcc-ibutton-", dir=Path(observations_dir).parent) as temporary:
        stage = Path(temporary)
        sensors = []
        contexts = []
        statuses = []
        for number, (path, code) in enumerate(zip(paths, ids), 1):
            site = sites[code]
            sensor_id = _sensor_id(code)
            registration, samples, ambiguous = read_raw_samples(path)
            sampled, hours, first, last = _write_hourly(stage / f"{sensor_id}.csv", samples)
            original_code = f"{path.stem.split('_')[0][0]}{int(path.stem.split('_')[0][1:])}"
            offset = NOMINAL_DEPTH_CM - site.organic_layer_cm
            medium = ("organic" if offset < 0 else "interface" if offset == 0 else "mineral")
            sensors.append(SensorMetadata(
                sensor_id=sensor_id, source="nrcan_ibutton", latitude=site.latitude,
                longitude=site.longitude, site_id=f"N{code[0]}{int(code[1:]):02d}",
                network="NRCan Open File 66", station=code,
                depth_cm=NOMINAL_DEPTH_CM, depth_from_cm=NOMINAL_DEPTH_CM,
                depth_to_cm=NOMINAL_DEPTH_CM, source_id=registration,
                source_url=SOURCE_URL, timezone_original="America/Toronto",
                soil_temperature_sensor_type="iButton",
                sensor_type_source="NRCan Open File 66 publisher metadata",
            ))
            contexts.append({
                "sensor_id": sensor_id, "site_id": f"N{code[0]}{int(code[1:]):02d}",
                "organic_layer_cm": site.organic_layer_cm,
                "depth_below_surface_cm": NOMINAL_DEPTH_CM,
                "estimated_interface_offset_cm": offset,
                "estimated_medium": medium, "raw_filename": path.name,
                "device_registration": registration,
                "depth_source": "NRCan Open File 66 field protocol",
                "site_data_source": "Site_data.xlsx: Top_Organic_Layer_Thickness(cm)",
            })
            statuses.append({
                "sensor_id": sensor_id, "site_id": f"N{code[0]}{int(code[1:]):02d}",
                "raw_filename": path.name, "device_registration": registration,
                "source_samples": len(samples), "sampled_hours": sampled,
                "output_hours": hours, "ambiguous_local_times": ambiguous,
                "site_id_corrected": code != original_code,
                "first_utc": first, "last_utc": last,
            })
            if number % 25 == 0 or number == len(paths):
                print(f"Prepared {number}/{len(paths)} NRCan iButton streams", flush=True)
        write_metadata(stage / "sensors.csv", sensors)
        for filename, columns, rows in (("context.csv", CONTEXT_COLUMNS, contexts),
                                        ("status.csv", STATUS_COLUMNS, statuses)):
            with (stage / filename).open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
        output = Path(observations_dir)
        output.mkdir()
        for sensor in sensors:
            (stage / f"{sensor.sensor_id}.csv").replace(output / f"{sensor.sensor_id}.csv")
        (stage / "sensors.csv").replace(sensors_file)
        (stage / "context.csv").replace(context_file)
        (stage / "status.csv").replace(status_file)
    return statuses
