"""Check legacy BS01/JP01 hourly temperatures against source 5 cm columns."""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path


SOURCE = Path("/Volumes/Expansion/UQAM/BERMS/Data")
STANDARDIZED = Path("/Volumes/Expansion/sfcc-label-data/standardized/local")
FILES = {
    "BS01": ("OBS_Soil_2016_AG.csv", "OBS_Soil_2021_AG.csv"),
    "JP01": ("OJP_Soil_2015-2021_AG.csv",),
}


def check(site: str) -> tuple[int, int]:
    source_hours: dict[str, list[float]] = defaultdict(list)
    for name in FILES[site]:
        with (SOURCE / name).open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if "SoilTemp_005cm" not in (reader.fieldnames or ()):
                raise ValueError(f"{name} has no 5 cm temperature column")
            for row in reader:
                value = float(row["SoilTemp_005cm"])
                if math.isfinite(value):
                    hour = datetime.fromisoformat(row["Time"]).replace(minute=0, second=0)
                    source_hours[hour.strftime("%Y-%m-%dT%H:00:00Z")].append(value)
    compared = mismatches = 0
    with (STANDARDIZED / f"local_{site}.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["soil_temperature_c"].lower() == "nan":
                continue
            compared += 1
            readings = source_hours.get(row["timestamp_utc"])
            if not readings or not math.isclose(
                float(row["soil_temperature_c"]), sum(readings) / len(readings),
                rel_tol=0, abs_tol=1e-9,
            ):
                mismatches += 1
    return compared, mismatches


if __name__ == "__main__":
    for site_id in FILES:
        total, failures = check(site_id)
        print(f"{site_id}: {total} observed hours, {failures} mismatches to SoilTemp_005cm")
        if failures:
            raise SystemExit(1)
