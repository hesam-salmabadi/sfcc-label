"""ISMN header+values importer. Source data stays local under ISMN terms."""

import csv
import gzip
import hashlib
import math
import os
import re
import shlex
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .io import write_metadata, write_observations
from .models import Observation, SensorMetadata

_FILENAME = re.compile(
    r"^.+?_(?P<variable>sm|ts)_(?P<depth_from>-?\d+\.\d+)_"
    r"(?P<depth_to>-?\d+\.\d+)_(?P<instrument>.+)_"
    r"(?P<redundancy>\d+)_(?P<replacement>\d+)_"
    r"(?P<start>\d{8})_(?P<end>\d{8})\.stm$"
)


@dataclass(frozen=True)
class ISMNFile:
    path: Path
    network: str
    station: str
    variable: str
    depth_from_m: Decimal
    depth_to_m: Decimal
    instrument: str
    redundancy: int
    replacement: int
    latitude: float
    longitude: float
    elevation_m: float

    @property
    def site_key(self):
        return (self.network, self.station, self.latitude, self.longitude)

    @property
    def depth_key(self):
        return (*self.site_key, self.depth_from_m, self.depth_to_m)

    @property
    def stream_key(self):
        return (self.variable, *self.depth_key, self.instrument,
                self.redundancy, self.replacement)


@dataclass(frozen=True)
class ISMNStream:
    files: tuple[ISMNFile, ...]

    @property
    def first(self) -> ISMNFile:
        return self.files[0]


@dataclass(frozen=True)
class ISMNPair:
    sensor_id: str
    site_id: str
    temperature: ISMNStream | None
    moisture: ISMNStream | None
    pairing_method: str
    depth_key: tuple


@dataclass(frozen=True)
class ISMNRecord:
    value: float | None
    ismn_flag: str
    provider_flag: str


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-_" )[:28] or "unnamed"


def _digest(value: object) -> str:
    return hashlib.sha1(repr(value).encode("utf-8")).hexdigest()[:10]


def _parse_file(path: Path) -> ISMNFile:
    match = _FILENAME.match(path.name)
    if match is None:
        raise ValueError("unrecognized ISMN sm/ts filename")
    fields = match.groupdict()
    with path.open(encoding="utf-8", errors="replace") as stream:
        header = shlex.split(stream.readline())
    if len(header) < 9:
        raise ValueError("header has fewer than nine fields")
    latitude, longitude = float(header[-6]), float(header[-5])
    elevation = float(header[-4])
    depth_from = Decimal(fields["depth_from"])
    depth_to = Decimal(fields["depth_to"])
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("invalid coordinates in header")
    if abs(Decimal(header[-3]) - depth_from) > Decimal("0.001") or \
            abs(Decimal(header[-2]) - depth_to) > Decimal("0.001"):
        raise ValueError("filename and header depth bounds differ")
    return ISMNFile(path, path.parent.parent.name, path.parent.name,
                    fields["variable"], depth_from, depth_to,
                    fields["instrument"], int(fields["redundancy"]),
                    int(fields["replacement"]), latitude, longitude, elevation)


def scan_ismn(root: str | Path, *, north_only: bool = True
              ) -> tuple[list[ISMNFile], list[tuple[str, str]]]:
    """Read filenames and first header lines only; report every malformed target."""
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(root)
    files = []
    issues = []
    for path in sorted(root.rglob("*.stm")):
        if "_sm_" not in path.name and "_ts_" not in path.name:
            continue
        try:
            record = _parse_file(path)
        except (OSError, ValueError, IndexError) as exc:
            issues.append((str(path.relative_to(root)), str(exc)))
            continue
        if north_only and record.latitude < 0:
            continue
        if record.depth_from_m < 0 or record.depth_to_m < 0:
            issues.append((str(path.relative_to(root)), "excluded: negative soil depth"))
            continue
        files.append(record)
    return files, issues


def _pair_id(depth_key: tuple, temperature: ISMNStream | None,
             moisture: ISMNStream | None) -> tuple[str, str]:
    network, station, latitude, longitude, depth_from, depth_to = depth_key
    site_key = (network, station, latitude, longitude)
    site_id = f"ismn_{_slug(network)}_{_slug(station)}_{_digest(site_key)}"
    identity = (depth_key,
                (temperature.first.instrument, temperature.first.redundancy,
                 temperature.first.replacement) if temperature else None,
                (moisture.first.instrument, moisture.first.redundancy,
                 moisture.first.replacement) if moisture else None)
    depth_label = f"{depth_from * 100:g}-{depth_to * 100:g}cm"
    sensor_id = f"{site_id}_{_slug(depth_label)}_{_digest(identity)}"
    return site_id, sensor_id


def pair_ismn(files: list[ISMNFile]) -> list[ISMNPair]:
    """Pair at exact depth, favoring instrument and position identifiers."""
    by_stream = defaultdict(list)
    for file in files:
        by_stream[file.stream_key].append(file)
    by_depth = defaultdict(lambda: {"ts": [], "sm": []})
    for shards in by_stream.values():
        shards.sort(key=lambda item: item.path.name)
        stream = ISMNStream(tuple(shards))
        by_depth[stream.first.depth_key][stream.first.variable].append(stream)
    result = []
    for depth_key, variables in sorted(by_depth.items()):
        temperatures = sorted(variables["ts"], key=lambda s: s.first.stream_key)
        moisture = sorted(variables["sm"], key=lambda s: s.first.stream_key)
        pairs = []

        def match_unique(predicate, method):
            nonlocal temperatures, moisture
            remaining_ts = []
            for temperature in temperatures:
                candidates = [item for item in moisture if predicate(temperature.first, item.first)]
                if len(candidates) == 1 and sum(predicate(other.first, candidates[0].first)
                                                for other in temperatures) == 1:
                    chosen = candidates[0]
                    pairs.append((temperature, chosen, method))
                    moisture.remove(chosen)
                else:
                    remaining_ts.append(temperature)
            temperatures = remaining_ts

        match_unique(lambda ts, sm: (ts.instrument, ts.redundancy, ts.replacement) ==
                     (sm.instrument, sm.redundancy, sm.replacement), "same_instrument")
        match_unique(lambda ts, sm: (ts.redundancy, ts.replacement) ==
                     (sm.redundancy, sm.replacement), "same_position")
        if len(temperatures) == len(moisture) == 1:
            pairs.append((temperatures.pop(), moisture.pop(), "sole_at_depth"))
        pairs.extend((item, None, "temperature_only") for item in temperatures)
        pairs.extend((None, item, "moisture_only") for item in moisture)
        for temperature, moist, method in pairs:
            site_id, sensor_id = _pair_id(depth_key, temperature, moist)
            result.append(ISMNPair(sensor_id, site_id, temperature, moist, method, depth_key))
    ids = [pair.sensor_id for pair in result]
    if len(ids) != len(set(ids)):
        raise ValueError("sensor ID collision in ISMN inventory")
    return sorted(result, key=lambda pair: pair.sensor_id)


def sensor_metadata(pair: ISMNPair) -> SensorMetadata:
    network, station, latitude, longitude, lower, upper = pair.depth_key
    return SensorMetadata(
        sensor_id=pair.sensor_id, source="ismn", latitude=latitude, longitude=longitude,
        site_id=pair.site_id, network=network, station=station,
        depth_cm=float((lower + upper) * 50),
        depth_from_cm=float(lower * 100), depth_to_cm=float(upper * 100),
        source_id=f"{network}/{station}", source_url="https://ismn.earth/",
        timezone_original="UTC", soil_moisture_method="ISMN harmonized m3/m3",
    )


def write_ismn_inventory(root: str | Path, output_dir: str | Path,
                         pairs: list[ISMNPair], issues: list[tuple[str, str]]) -> None:
    """Write private site, sensor, source-pairing, and scan-issue tables."""
    root = Path(root)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    names = ("ismn_sensors.csv", "ismn_sites.csv", "ismn_pairing.csv", "ismn_scan_issues.csv")
    existing = [name for name in names if (output / name).exists()]
    if existing:
        raise FileExistsError(f"inventory already exists: {', '.join(existing)}")
    usable = [pair for pair in pairs if pair.temperature is not None]
    write_metadata(output / "ismn_sensors.csv", [sensor_metadata(pair) for pair in usable])
    sites = {}
    for pair in usable:
        first = (pair.temperature or pair.moisture).first
        sites[pair.site_id] = (pair.site_id, first.network, first.station,
                               first.latitude, first.longitude, first.elevation_m)
    with (output / "ismn_sites.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("site_id", "network", "station", "latitude", "longitude", "elevation_m"))
        writer.writerows(sites[key] for key in sorted(sites))
    with (output / "ismn_pairing.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("sensor_id", "site_id", "pairing_method", "depth_from_m",
                         "depth_to_m", "temperature_files", "moisture_files"))
        for pair in pairs:
            writer.writerow((pair.sensor_id, pair.site_id, pair.pairing_method,
                             pair.depth_key[-2], pair.depth_key[-1],
                             "|".join(str(file.path.relative_to(root)) for file in pair.temperature.files)
                             if pair.temperature else "",
                             "|".join(str(file.path.relative_to(root)) for file in pair.moisture.files)
                             if pair.moisture else ""))
    with (output / "ismn_scan_issues.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("relative_path", "issue"))
        writer.writerows(issues)


def _read_stream(stream: ISMNStream | None, start: datetime, end: datetime
                 ) -> dict[datetime, ISMNRecord]:
    if stream is None:
        return {}
    result = {}
    for source in stream.files:
        with source.path.open(encoding="utf-8", errors="replace") as file:
            next(file)
            for line_number, line in enumerate(file, start=2):
                fields = line.split()
                if not fields:
                    continue
                if len(fields) < 4:
                    raise ValueError(f"{source.path}:{line_number}: incomplete observation")
                timestamp = datetime.strptime(" ".join(fields[:2]), "%Y/%m/%d %H:%M")
                timestamp = timestamp.replace(tzinfo=timezone.utc)
                if not start <= timestamp < end:
                    continue
                if timestamp.minute:
                    raise ValueError(f"{source.path}:{line_number}: non-hourly timestamp")
                value = float(fields[2])
                record = ISMNRecord(value if math.isfinite(value) else None,
                                    fields[3], fields[4] if len(fields) > 4 else "")
                if timestamp in result and result[timestamp] != record:
                    raise ValueError(f"{source.path}:{line_number}: conflicting duplicate UTC hour")
                result[timestamp] = record
    return result


def import_ismn_pair(pair: ISMNPair, start: datetime, end: datetime,
                     observations_dir: str | Path, flags_dir: str | Path) -> int:
    """Write one hourly per-sensor CSV and a compressed original-flag sidecar."""
    if start.tzinfo is None or end.tzinfo is None or start.utcoffset() != timedelta(0) \
            or end.utcoffset() != timedelta(0) or start >= end:
        raise ValueError("start and end must define an increasing UTC interval")
    temperature = _read_stream(pair.temperature, start, end)
    moisture = _read_stream(pair.moisture, start, end)
    present = temperature.keys() | moisture.keys()
    if not present:
        return 0
    observation_path = Path(observations_dir) / f"{pair.sensor_id}.csv"
    flag_path = Path(flags_dir) / f"{pair.sensor_id}.csv.gz"
    if observation_path.exists() or flag_path.exists():
        raise FileExistsError(f"output already exists for {pair.sensor_id}")
    Path(observations_dir).mkdir(parents=True, exist_ok=True)
    Path(flags_dir).mkdir(parents=True, exist_ok=True)
    first, last = min(present), max(present)
    hours = []
    timestamp = first
    while timestamp <= last:
        ts = temperature.get(timestamp)
        sm = moisture.get(timestamp)
        hours.append(Observation(timestamp, ts.value if ts else None,
                                 sm.value if sm else None, None))
        timestamp += timedelta(hours=1)
    obs_fd, obs_temp = tempfile.mkstemp(prefix=f".{pair.sensor_id}.", suffix=".tmp",
                                        dir=observations_dir)
    os.close(obs_fd)
    flag_fd, flag_temp = tempfile.mkstemp(prefix=f".{pair.sensor_id}.", suffix=".tmp",
                                          dir=flags_dir)
    os.close(flag_fd)
    try:
        write_observations(obs_temp, hours)
        with gzip.open(flag_temp, "wt", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(("timestamp_utc", "soil_temperature_ismn_flag",
                             "soil_temperature_provider_flag", "soil_moisture_ismn_flag",
                             "soil_moisture_provider_flag"))
            for hour in hours:
                ts = temperature.get(hour.timestamp_utc)
                sm = moisture.get(hour.timestamp_utc)
                writer.writerow((hour.timestamp_utc.strftime("%Y-%m-%dT%H:00:00Z"),
                                 ts.ismn_flag if ts else "", ts.provider_flag if ts else "",
                                 sm.ismn_flag if sm else "", sm.provider_flag if sm else ""))
        os.replace(obs_temp, observation_path)
        os.replace(flag_temp, flag_path)
    finally:
        for temporary in (obs_temp, flag_temp):
            if os.path.exists(temporary):
                os.unlink(temporary)
    return len(hours)
