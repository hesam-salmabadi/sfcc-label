"""Standardize original Chapleau temperatures and CS616 moisture probes.

Temperature is from the UTC SoilTemp publisher workbook. Chelene plot books
carry local Ontario timestamps and distinct moisture probes; no false
same-depth temperature/moisture pairing or replicate averaging is performed.
"""

from __future__ import annotations

import csv
import math
import re
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .io import OBSERVATION_COLUMNS, write_metadata
from .models import SensorMetadata
from .naming import sensor_id as make_sensor_id


PLOTS = {"AS3": "Aw", "BS1": "Sb", "JP1": "Pj", "MW1": "Mw"}
TEMP_DEPTHS = {6, 15, 30}
MOISTURE_DEPTHS = {10, 18}
LOCAL_ZONE = ZoneInfo("America/Toronto")
CONTEXT_COLUMNS = ("sensor_id", "measurement", "plot", "subplot", "replicate",
                   "depth_basis", "installation_depth_cm", "support_from_cm",
                   "support_to_cm", "midpoint_cm", "source_column", "raw_column",
                   "source_file", "nearby_temperature_sensor_id",
                   "aspen_coordinate_note", "ambiguous_local_hours_skipped",
                   "nonexistent_local_hours_skipped", "undated_rows_skipped")
STATUS_COLUMNS = ("sensor_id", "status", "source_rows", "observed_hours", "output_hours",
                  "temperature_hours", "moisture_hours", "raw_hours", "first_utc",
                  "last_utc", "detail")


def _workbook(path: Path):
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("Chapleau importer requires pip install 'sfcc-label[source-excel]'") from exc
    return load_workbook(path, read_only=True, data_only=True)


def _rounded_hour(stamp: datetime) -> datetime:
    if stamp.tzinfo is not None:
        raise ValueError("expected a naive publisher timestamp")
    return (stamp + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)


def _numeric(value, where: str) -> float | None:
    if value is None or isinstance(value, str) and value.strip().upper() in {"", "NA", "NAN"}:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{where}: invalid numeric value {value!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"{where}: nonfinite numeric value")
    return result


def _local_to_utc(stamp: datetime, reference_temperature: float | None,
                  temperature_by_utc: dict[datetime, float]) -> tuple[datetime | None, str]:
    """Resolve DST fold only when the source temperature identifies one UTC hour."""
    candidates = []
    for fold in (0, 1):
        aware = stamp.replace(tzinfo=LOCAL_ZONE, fold=fold)
        utc = aware.astimezone(timezone.utc)
        if utc.astimezone(LOCAL_ZONE).replace(tzinfo=None) == stamp and utc not in candidates:
            candidates.append(utc)
    if not candidates:
        return None, "nonexistent"
    if len(candidates) == 1:
        return candidates[0], "unambiguous"
    if reference_temperature is not None:
        matches = [utc for utc in candidates if utc.replace(tzinfo=None) in temperature_by_utc
                   and abs(temperature_by_utc[utc.replace(tzinfo=None)] - reference_temperature) < 1e-8]
        if len(matches) == 1:
            return matches[0], "resolved_from_temperature"
    return None, "ambiguous"


def _put(buckets: dict, stamp: datetime, value, where: str) -> None:
    if stamp in buckets and buckets[stamp] != value:
        raise ValueError(f"{where}: conflicting rows for {stamp}")
    buckets[stamp] = value


def _write_hourly(path: Path, samples: dict[datetime, tuple[float | None, float | None, float | None]]):
    first, last = min(samples), max(samples)
    counts = [0, 0, 0]
    output_hours = 0
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(OBSERVATION_COLUMNS)
        stamp = first
        while stamp <= last:
            values = samples.get(stamp, (None, None, None))
            counts = [count + (value is not None) for count, value in zip(counts, values)]
            writer.writerow((stamp.strftime("%Y-%m-%dT%H:00:00Z"),
                             *("NaN" if value is None else format(value, ".15g") for value in values)))
            output_hours += 1
            stamp += timedelta(hours=1)
    return {"observed_hours": len(samples), "output_hours": output_hours,
            "temperature_hours": counts[0], "moisture_hours": counts[1],
            "raw_hours": counts[2],
            "first_utc": first.strftime("%Y-%m-%dT%H:00:00Z"),
            "last_utc": last.strftime("%Y-%m-%dT%H:00:00Z")}


def _temperature_source(path: Path):
    book = _workbook(path)
    try:
        if "Metadata" not in book.sheetnames or "Raw time series data" not in book.sheetnames:
            raise ValueError("Chapleau temperature workbook has unexpected sheets")
        rows = book["Metadata"].values
        header = next(rows)
        metadata = {}
        for row in rows:
            record = dict(zip(header, row))
            ident = record["Raw_data_identifier"]
            match = re.fullmatch(r"Chapleau_(AS3|BS1|JP1|MW1)_(6|15|30)", str(ident))
            if not match or ident in metadata:
                raise ValueError(f"unexpected or repeated Chapleau temperature ID {ident!r}")
            depth = int(match[2])
            if record["Sensor_height"] != -depth or record["Timezone"] != "UTC" or record["Unit"] != "°C":
                raise ValueError(f"{ident}: unexpected depth, timezone, or unit")
            metadata[ident] = record
        if len(metadata) != 12:
            raise ValueError(f"expected 12 temperature streams, found {len(metadata)}")
        source_rows = defaultdict(int)
        undated = defaultdict(int)
        samples: dict[str, dict[datetime, float]] = defaultdict(dict)
        rows = book["Raw time series data"].values
        if next(rows)[:6] != ("Raw_data_identifier", "Year", "Month", "Day", "Time (24h)", "Temperature"):
            raise ValueError("unexpected Chapleau temperature columns")
        for line, row in enumerate(rows, 2):
            ident, year, month, day, clock, value = row[:6]
            if ident not in metadata:
                raise ValueError(f"temperature row {line}: unexpected ID {ident!r}")
            source_rows[ident] += 1
            if (year, month, day, clock) == ("NA", "NA", "NA", "NA"):
                undated[ident] += 1
                continue
            try:
                stamp = datetime.strptime(f"{year:04d}-{month:02d}-{day:02d} {clock}",
                                          "%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError) as exc:
                raise ValueError(f"temperature row {line}: invalid timestamp") from exc
            stamp = _rounded_hour(stamp)
            measured = _numeric(value, f"temperature row {line}")
            if measured is not None:
                _put(samples[ident], stamp, measured, f"temperature row {line}")
        return metadata, samples, source_rows, undated
    finally:
        book.close()


def import_chapleau(chelene_dir: str | Path, temperature_workbook: str | Path,
                    observations_dir: str | Path, sensors_file: str | Path,
                    context_file: str | Path, status_file: str | Path,
                    aspen_latitude: float, aspen_longitude: float,
                    aspen_coordinate_evidence: str) -> list[dict]:
    """Import 12 temperature and 48 distinct moisture streams, no forced pairing."""
    if not aspen_coordinate_evidence.strip():
        raise ValueError("provide evidence for selected Aspen coordinates")
    source_root = Path(chelene_dir)
    temperature_path = Path(temperature_workbook)
    destinations = [Path(observations_dir), Path(sensors_file), Path(context_file), Path(status_file)]
    if any(path.exists() for path in destinations):
        raise FileExistsError("Chapleau output already exists; use new destinations")
    metadata, temperatures, temp_rows, temp_undated = _temperature_source(temperature_path)
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
    sensors, contexts, statuses = [], [], []
    with tempfile.TemporaryDirectory(prefix=".sfcc-chapleau-", dir=Path(observations_dir).parent) as temporary:
        stage = Path(temporary)
        for plot in PLOTS:
            for depth in sorted(TEMP_DEPTHS):
                ident = f"Chapleau_{plot}_{depth}"
                record = metadata[ident]
                latitude = aspen_latitude if plot == "AS3" else float(record["Latitude"])
                longitude = aspen_longitude if plot == "AS3" else float(record["Longitude"])
                sensor_id = make_sensor_id("chapleau", plot, float(depth), tag="t")
                sensors.append(SensorMetadata(
                    sensor_id=sensor_id, source="chapleau", latitude=latitude,
                    longitude=longitude, site_id=plot, network="Chapleau", station=plot,
                    depth_cm=float(depth), depth_from_cm=float(depth), depth_to_cm=float(depth),
                    source_id=ident, source_url=str(temperature_path),
                    timezone_original="UTC (publisher workbook metadata)"))
                values = {stamp: (value, None, None) for stamp, value in temperatures[ident].items()}
                counts = _write_hourly(stage / f"{sensor_id}.csv", values)
                contexts.append({"sensor_id": sensor_id, "measurement": "temperature",
                                 "plot": plot, "subplot": "NaN", "replicate": "NaN",
                                 "depth_basis": "point temperature depth, publisher workbook metadata",
                                 "installation_depth_cm": depth, "support_from_cm": depth,
                                 "support_to_cm": depth, "midpoint_cm": depth,
                                 "source_column": ident, "raw_column": "NaN",
                                 "source_file": str(temperature_path),
                                 "nearby_temperature_sensor_id": "NaN",
                                 "aspen_coordinate_note": aspen_coordinate_evidence if plot == "AS3" else "",
                                 "ambiguous_local_hours_skipped": 0,
                                 "nonexistent_local_hours_skipped": 0,
                                 "undated_rows_skipped": temp_undated[ident]})
                statuses.append({"sensor_id": sensor_id, "status": "imported",
                                 "source_rows": temp_rows[ident], **counts,
                                 "detail": f"undated_rows={temp_undated[ident]}"})
            print(f"Prepared Chapleau {plot} temperatures", flush=True)
        for plot, suffix in PLOTS.items():
            paths = list(source_root.glob(f"Chapleau_{suffix}_soil.moisture.temp.xlsx"))
            if len(paths) != 1:
                raise ValueError(f"expected one Chelene workbook for {plot}, found {len(paths)}")
            path = paths[0]
            book = _workbook(path)
            try:
                data = book["Data"]
                header = next(data.values)
                columns = {name: i for i, name in enumerate(header) if name is not None}
                pattern = re.compile(r"p([135])([abcd])_vwc\.cal_(10|18)")
                probes = []
                for name in columns:
                    match = pattern.fullmatch(name)
                    if match:
                        subplot, replicate, extent = int(match[1]), match[2], int(match[3])
                        raw_name = f"p{subplot}{replicate}_period_{extent}"
                        if raw_name not in columns:
                            raise ValueError(f"{path}: {name} has no raw period")
                        probes.append((subplot, replicate, extent, name, raw_name))
                if len(probes) != 12:
                    raise ValueError(f"{path}: expected 12 moisture probes, found {len(probes)}")
                by_probe = {name: {} for _, _, _, name, _ in probes}
                ambiguous = nonexistent = undated = 0
                dated_rows = 0
                reference = temperatures[f"Chapleau_{plot}_6"]
                for line, row in enumerate(data.iter_rows(min_row=2, values_only=True), 2):
                    local = row[0]
                    if not isinstance(local, datetime):
                        undated += 1
                        continue
                    dated_rows += 1
                    local = _rounded_hour(local)
                    ref_temp = _numeric(row[columns["p1_temp_6"]], f"{path}:{line}:p1_temp_6")
                    utc, reason = _local_to_utc(local, ref_temp, reference)
                    if utc is None:
                        ambiguous += reason == "ambiguous"
                        nonexistent += reason == "nonexistent"
                        continue
                    stamp = utc.replace(tzinfo=None)
                    for _, _, _, name, raw_name in probes:
                        vwc = _numeric(row[columns[name]], f"{path}:{line}:{name}")
                        period = _numeric(row[columns[raw_name]], f"{path}:{line}:{raw_name}")
                        _put(by_probe[name], stamp,
                             (None, None if vwc is None else vwc / 100, period),
                             f"{path}:{line}:{name}")
                for subplot, replicate, extent, name, raw_name in probes:
                    midpoint = extent / 2
                    sensor_id = make_sensor_id("chapleau", plot, 0.0, float(extent), tag=f"p{subplot}{replicate}")
                    record = metadata[f"Chapleau_{plot}_6"]
                    latitude = aspen_latitude if plot == "AS3" else float(record["Latitude"])
                    longitude = aspen_longitude if plot == "AS3" else float(record["Longitude"])
                    sensors.append(SensorMetadata(
                        sensor_id=sensor_id, source="chapleau", latitude=latitude,
                        longitude=longitude, site_id=plot, network="Chapleau", station=plot,
                        depth_cm=midpoint, depth_from_cm=0.0, depth_to_cm=float(extent),
                        raw_variable="CS616_period", raw_unit="microsecond",
                        source_id=name, source_url=str(path),
                        timezone_original="America/Toronto (inferred against UTC temperature series)",
                        soil_moisture_method="calibrated VWC percent / 100; source soil-profile coefficients",
                        soil_moisture_sensor_type="CS616",
                        sensor_type_source="Chapleau source workbook/soil-profile metadata",
                        sensor_type_note="Raw period output is the CS616 measurement; VWC is separately calibrated."))
                    values = by_probe[name]
                    counts = _write_hourly(stage / f"{sensor_id}.csv", values)
                    contexts.append({"sensor_id": sensor_id, "measurement": "moisture",
                                     "plot": plot, "subplot": subplot, "replicate": replicate,
                                     "depth_basis": "30 cm CS616 rod inserted diagonally from surface",
                                     "installation_depth_cm": extent, "support_from_cm": 0,
                                     "support_to_cm": extent, "midpoint_cm": midpoint,
                                     "source_column": name, "raw_column": raw_name,
                                     "source_file": str(path),
                                     "nearby_temperature_sensor_id": make_sensor_id(
                                         "chapleau", plot, float({1: 6, 3: 15, 5: 30}[subplot]), tag="t"),
                                     "aspen_coordinate_note": aspen_coordinate_evidence if plot == "AS3" else "",
                                     "ambiguous_local_hours_skipped": ambiguous,
                                     "nonexistent_local_hours_skipped": nonexistent,
                                     "undated_rows_skipped": undated})
                    statuses.append({"sensor_id": sensor_id, "status": "imported",
                                     "source_rows": dated_rows + undated, **counts,
                                     "detail": f"ambiguous={ambiguous};nonexistent={nonexistent};undated={undated}"})
            finally:
                book.close()
            print(f"Prepared Chapleau {plot} moisture", flush=True)
        if len(sensors) != 60 or len({sensor.sensor_id for sensor in sensors}) != 60:
            raise ValueError("expected 60 unique Chapleau streams")
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
