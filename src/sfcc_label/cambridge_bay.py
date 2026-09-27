"""Import curated, depth-specific Cambridge Bay iButton temperature records.

The supplied source has 2018-19 and 2019-20 campaigns. Logger timestamps are
kept as declared/previously used UTC; that assumption has not been independently
verified. The 3-hour samples are placed in hourly slots without interpolation.
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

from .io import OBSERVATION_COLUMNS, write_metadata
from .models import SensorMetadata
from .naming import sensor_id as make_sensor_id


XML_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CONTEXT_COLUMNS = (
    "sensor_id", "site_id", "campaign", "nominal_depth_cm", "retrieval_depth_cm",
    "depth_basis", "source_tag", "source_file", "site_land_cover", "site_soil",
    "source_metadata_file", "timezone_assumption",
)
STATUS_COLUMNS = (
    "sensor_id", "site_id", "campaign", "status", "detail", "source_file",
    "source_samples", "sampled_hours", "output_hours", "first_utc", "last_utc",
)


@dataclass(frozen=True)
class CambridgeSite:
    code: str
    latitude: float
    longitude: float
    land_cover: str
    soil: str
    deployment_buttons: dict[int, str]


def _xlsx_rows(path: Path, sheet_number: int = 1) -> list[dict[str, str]]:
    """Read only cell values from one source workbook sheet, including strings."""
    with zipfile.ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            strings = ["".join(item.itertext()) for item in root.findall("m:si", XML_NS)]
        sheet = ET.fromstring(archive.read(f"xl/worksheets/sheet{sheet_number}.xml"))
    result = []
    for row in sheet.findall(".//m:sheetData/m:row", XML_NS):
        values = {}
        for cell in row.findall("m:c", XML_NS):
            column = re.match(r"[A-Z]+", cell.attrib["r"]).group()
            value = cell.find("m:v", XML_NS)
            if cell.attrib.get("t") == "inlineStr":
                inline = cell.find("m:is", XML_NS)
                values[column] = "".join(inline.itertext()) if inline is not None else ""
            elif value is not None and value.text is not None:
                values[column] = (strings[int(value.text)] if cell.attrib.get("t") == "s"
                                  else value.text)
        result.append(values)
    return result


def read_cambridge_sites(metadata_workbook: str | Path) -> dict[str, CambridgeSite]:
    """Use the 2018 deployment workbook, not its stale Metadata.csv export."""
    result = {}
    for row in _xlsx_rows(Path(metadata_workbook)):
        match = re.fullmatch(r"IP(\d+)", row.get("A", ""))
        if not match:
            continue
        code = f"CB{int(match[1]):02d}"
        if code in result:
            raise ValueError(f"duplicate Cambridge Bay site {code}")
        buttons = {}
        for button, depth_text in re.findall(r"(\d+)\s*:\s*(\d+)", row.get("I", "")):
            depth = int(depth_text)
            if depth in buttons:
                raise ValueError(f"duplicate deployment depth at {code}: {depth}")
            buttons[depth] = button
        if not buttons:
            raise ValueError(f"no deployment depths for {code}")
        result[code] = CambridgeSite(
            code, float(row["C"]), float(row["D"]), row.get("F", ""),
            row.get("G", ""), buttons,
        )
    if len(result) != 16:
        raise ValueError(f"expected 16 Cambridge Bay sites, found {len(result)}")
    return result


def read_retrieval_depths(workbook: str | Path) -> dict[tuple[str, int], int]:
    """Read 2020 retrieval labels; some nominal 0-cm loggers became 2 cm."""
    result = {}
    for row in _xlsx_rows(Path(workbook)):
        label = re.fullmatch(r"IP(\d+)-(\d+)", row.get("A", ""))
        tag = re.fullmatch(r"(\d+)-(\d+)", row.get("B", ""))
        if not label or not tag:
            continue
        if int(label[1]) != int(tag[1]):
            raise ValueError(f"site/tag disagreement in retrieval workbook: {label[0]}, {tag[0]}")
        key = (f"CB{int(tag[1]):02d}", int(tag[2]))
        if key in result:
            raise ValueError(f"duplicate retrieval tag {key}")
        result[key] = int(label[2])
    return result


def read_temperature_samples(path: str | Path) -> list[tuple[datetime, float]]:
    source = Path(path)
    samples = []
    with source.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["date/time", "unite", "value"]:
            raise ValueError(f"{source}: unexpected cleaned columns {reader.fieldnames}")
        previous = None
        for row in reader:
            if row["unite"] != "C":
                raise ValueError(f"{source}:{reader.line_num}: unexpected unit")
            try:
                stamp = datetime.strptime(row["date/time"], "%y-%m-%d %H:%M:%S")
                value = float(row["value"])
            except ValueError as exc:
                raise ValueError(f"{source}:{reader.line_num}: invalid temperature row") from exc
            if not math.isfinite(value):
                raise ValueError(f"{source}:{reader.line_num}: nonfinite temperature")
            stamp = stamp.replace(tzinfo=timezone.utc)
            if previous is not None and stamp <= previous:
                raise ValueError(f"{source}:{reader.line_num}: non-increasing timestamps")
            samples.append((stamp, value))
            previous = stamp
    if not samples:
        raise ValueError(f"{source}: no temperature samples")
    return samples


def _write_hourly(path: Path, samples: list[tuple[datetime, float]]) -> tuple[int, int, str, str]:
    buckets = defaultdict(list)
    for stamp, value in samples:
        buckets[stamp.replace(minute=0, second=0, microsecond=0)].append(value)
    first, last = min(buckets), max(buckets)
    hours = 0
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(OBSERVATION_COLUMNS)
        stamp = first
        while stamp <= last:
            values = buckets.get(stamp)
            temperature = format(math.fsum(values) / len(values), ".15g") if values else "NaN"
            writer.writerow((stamp.strftime("%Y-%m-%dT%H:00:00Z"), temperature, "NaN", "NaN"))
            hours += 1
            stamp += timedelta(hours=1)
    return len(buckets), hours, first.strftime("%Y-%m-%dT%H:00:00Z"), last.strftime("%Y-%m-%dT%H:00:00Z")


def import_cambridge_bay(source_root: str | Path, observations_dir: str | Path,
                         sensors_file: str | Path, context_file: str | Path,
                         status_file: str | Path) -> list[dict]:
    """Import 64 curated site-depth streams from both Cambridge Bay campaigns."""
    root = Path(source_root) / "Cambridge Bay" / "ib" / "data"
    sites = read_cambridge_sites(root / "CB_ib_2018-2019" / "Metadata.xlsx")
    retrieval = read_retrieval_depths(root / "CB_ib_2019-2020" / "CB_ib_data.xlsx")
    old = sorted(path for path in (root / "CB_ib_2018-2019" / "cleaned").glob("CB*.csv")
                 if not path.name.startswith("._"))
    new = sorted(path for path in (root / "CB_ib_2019-2020" / "cleaned").glob("CB*.csv")
                 if not path.name.startswith("._"))
    if len(old) != 47 or len(new) != 19:
        raise ValueError(f"unexpected Cambridge Bay source inventory: {len(old)} old, {len(new)} new")
    destinations = [Path(observations_dir), Path(sensors_file),
                    Path(context_file), Path(status_file)]
    if any(path.exists() for path in destinations):
        raise FileExistsError("Cambridge Bay output already exists; use new destinations")
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".sfcc-cambridge-", dir=Path(observations_dir).parent) as temporary:
        stage = Path(temporary)
        sensors = []
        contexts = []
        statuses = []
        for campaign, paths in (("2018-2019", old), ("2019-2020", new)):
            for path in paths:
                match = re.fullmatch(r"CB(\d+)_(\d+)\.csv", path.name)
                if match is None:
                    if campaign == "2019-2020" and path.name in {"CBEC_5.csv", "CBEC_10.csv"}:
                        statuses.append({"sensor_id": "", "site_id": "EC", "campaign": campaign,
                                         "status": "excluded_no_coordinates",
                                         "detail": "EC tower site coordinates absent from deployment metadata",
                                         "source_file": str(path.relative_to(root))})
                        continue
                    raise ValueError(f"unexpected Cambridge Bay filename: {path.name}")
                site_id = f"CB{int(match[1]):02d}"
                nominal_depth = int(match[2])
                site = sites.get(site_id)
                if site is None:
                    raise ValueError(f"{path}: no site coordinates")
                if campaign == "2018-2019" and nominal_depth not in site.deployment_buttons:
                    raise ValueError(f"{path}: depth absent from deployment workbook")
                if campaign == "2019-2020" and nominal_depth not in {0, 5}:
                    raise ValueError(f"{path}: unexpected newer-campaign tag depth")
                measured_retrieval_depth = (retrieval.get((site_id, nominal_depth))
                                            if campaign == "2019-2020" else None)
                if campaign == "2019-2020" and measured_retrieval_depth is None:
                    raise ValueError(f"{path}: missing 2020 retrieval site label")
                sensor_id = make_sensor_id("cambridge_bay", site_id, float(nominal_depth), tag=campaign[:4])
                samples = read_temperature_samples(path)
                sampled, hours, first, last = _write_hourly(stage / f"{sensor_id}.csv", samples)
                source_tag = (site.deployment_buttons[nominal_depth] if campaign == "2018-2019"
                              else f"{int(match[1])}-{nominal_depth}")
                sensors.append(SensorMetadata(
                    sensor_id=sensor_id, source="cambridge_bay", latitude=site.latitude,
                    longitude=site.longitude, site_id=site_id, network="Cambridge Bay",
                    station=site_id, depth_cm=float(nominal_depth),
                    depth_from_cm=float(nominal_depth), depth_to_cm=float(nominal_depth),
                    source_id=source_tag, timezone_original="UTC (assumed; unverified)",
                ))
                contexts.append({
                    "sensor_id": sensor_id, "site_id": site_id, "campaign": campaign,
                    "nominal_depth_cm": nominal_depth,
                    "retrieval_depth_cm": (measured_retrieval_depth if measured_retrieval_depth is not None else "NaN"),
                    "depth_basis": ("2018 deployment metadata" if campaign == "2018-2019"
                                    else "2019 deployment tag; 2020 retrieval depth separate"),
                    "source_tag": source_tag, "source_file": str(path.relative_to(root)),
                    "site_land_cover": site.land_cover, "site_soil": site.soil,
                    "source_metadata_file": ("CB_ib_2018-2019/Metadata.xlsx" if campaign == "2018-2019"
                                             else "CB_ib_2019-2020/CB_ib_data.xlsx"),
                    "timezone_assumption": "source clock interpreted as UTC; not independently verified",
                })
                statuses.append({
                    "sensor_id": sensor_id, "site_id": site_id, "campaign": campaign,
                    "status": "imported", "detail": "", "source_file": str(path.relative_to(root)),
                    "source_samples": len(samples), "sampled_hours": sampled,
                    "output_hours": hours, "first_utc": first, "last_utc": last,
                })
            print(f"Prepared {campaign} Cambridge Bay streams", flush=True)
        if len(sensors) != 64 or len({sensor.sensor_id for sensor in sensors}) != 64:
            raise ValueError("expected 64 unique coordinate-supported Cambridge Bay streams")
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
