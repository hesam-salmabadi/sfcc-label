"""Import publisher pit-level St-Marthe/St-Maurice temperatures (2 and 10 cm)."""

from __future__ import annotations

import csv
import math
import re
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .io import OBSERVATION_COLUMNS, write_metadata
from .models import SensorMetadata
from .naming import sensor_id as make_sensor_id


PIT_COLUMN = re.compile(r"SoilPit([1-5])at(2|10)cm_SoilTemp_Celsius")
CONTEXT_COLUMNS = ("sensor_id", "plot", "pit", "depth_cm", "source_files", "source_rows",
                   "observed_hours", "first_utc", "last_utc", "time_basis")


def _hourly(path: Path, values: dict[datetime, float]) -> None:
    first, last = min(values), max(values)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(OBSERVATION_COLUMNS)
        stamp = first
        while stamp <= last:
            value = values.get(stamp)
            writer.writerow((stamp.strftime("%Y-%m-%dT%H:00:00Z"),
                             "NaN" if value is None else format(value, ".15g"), "NaN", "NaN"))
            stamp += timedelta(hours=1)


def import_st_marthe_maurice(source_dir: str | Path, observations_dir: str | Path,
                             sensors_file: str | Path, context_file: str | Path) -> list[dict]:
    """Preserve each physical pit/depth; do not import publisher freeze probabilities."""
    source = Path(source_dir)
    output = Path(observations_dir)
    destinations = (output, Path(sensors_file), Path(context_file))
    if any(p.exists() for p in destinations):
        raise FileExistsError("St-Marthe/Maurice output already exists")
    locations = {}
    with (source / "Plotlocations.csv").open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            locations[row["Plots"]] = row
    files = sorted(source.glob("St_*20*/*.csv"))
    if len(files) != 36:
        raise ValueError(f"expected 36 plot-year CSVs; found {len(files)}")
    samples: dict[tuple[str, int, int], dict[datetime, float]] = defaultdict(dict)
    provenance: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    counts = defaultdict(int)
    for file in files:
        plot = file.name.split("_", 1)[0]
        if plot not in locations:
            raise ValueError(f"missing plot coordinates for {plot}")
        with file.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            columns = {key: (int(match[1]), int(match[2]))
                       for key in reader.fieldnames or () if (match := PIT_COLUMN.fullmatch(key))}
            if len(columns) != 10 or "Date_UTC" not in (reader.fieldnames or []):
                raise ValueError(f"unexpected publisher columns: {file}")
            for row in reader:
                if not row["Date_UTC"].strip():
                    if any(row[key].strip() for key in columns):
                        raise ValueError(f"undated temperature values in {file}")
                    continue
                stamp = datetime.strptime(row["Date_UTC"], "%m/%d/%Y %H:%M")
                if stamp.minute:
                    raise ValueError(f"non-hourly timestamp in {file}: {stamp}")
                for column, (pit, depth) in columns.items():
                    key = (plot, pit, depth)
                    provenance[key].add(str(file))
                    raw = row[column].strip()
                    if not raw or raw.lower() in {"nan", "na"}:
                        continue
                    value = float(raw)
                    if not math.isfinite(value):
                        continue
                    previous = samples[key].get(stamp)
                    if previous is not None and previous != value:
                        raise ValueError(f"conflicting duplicate {key} at {stamp}")
                    samples[key][stamp] = value
                    counts[key] += 1
    output.parent.mkdir(parents=True, exist_ok=True)
    sensors = []
    contexts = []
    with tempfile.TemporaryDirectory(prefix=".sfcc-st-plots-", dir=output.parent) as temp:
        stage = Path(temp)
        for (plot, pit, depth), values in sorted(samples.items()):
            loc = locations[plot]
            site = loc["Site"]
            sensor_id = make_sensor_id("st_marthe_maurice", plot, float(depth), tag=f"pit{pit}")
            sensors.append(SensorMetadata(
                sensor_id=sensor_id, source="st_marthe_maurice", site_id=plot,
                network=site, station=plot, latitude=float(loc["Lat"]),
                longitude=float(loc["Lon"]), depth_cm=float(depth),
                depth_from_cm=float(depth), depth_to_cm=float(depth),
                source_id=f"{plot}_pit{pit}_{depth}cm", source_url=str(source),
                timezone_original="UTC (publisher README/Date_UTC)",
            ))
            _hourly(stage / f"{sensor_id}.csv", values)
            contexts.append({
                "sensor_id": sensor_id, "plot": plot, "pit": pit, "depth_cm": depth,
                "source_files": ";".join(sorted(provenance[plot, pit, depth])),
                "source_rows": counts[plot, pit, depth], "observed_hours": len(values),
                "first_utc": min(values).isoformat() + "Z",
                "last_utc": max(values).isoformat() + "Z",
                "time_basis": "publisher Date_UTC; exact hour",
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
