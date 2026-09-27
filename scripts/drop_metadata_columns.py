#!/usr/bin/env python3
"""Drop the retired land_cover/modeled_soil_* columns from every *_sensors.csv.

Those values now live in sensor_landcover_cci.csv and sensor_soil.csv. Run
without --apply for a read-only preflight; --apply backs up the files first.
"""
from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

from sfcc_label.io import METADATA_COLUMNS

RETIRED = ("land_cover", "land_cover_source", "modeled_soil_variable", "modeled_soil_value",
           "modeled_soil_unit", "modeled_soil_source")


def run(metadata_dir: Path, archive: Path, apply: bool) -> None:
    files = sorted(p for p in metadata_dir.glob("*_sensors.csv") if not p.name.startswith("._"))
    for path in files:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            fields = list(reader.fieldnames or ())
            rows = list(reader)
        if tuple(fields) == METADATA_COLUMNS:
            print(f"{path.name}: already current")
            continue
        if tuple(f for f in fields if f not in RETIRED) != METADATA_COLUMNS:
            raise ValueError(f"{path.name}: unexpected header {fields}")
        filled = {c: sum(r[c] not in ("", "NaN") for r in rows) for c in RETIRED}
        print(f"{path.name}: {len(rows)} rows; non-empty retired values {filled}")
        if not apply:
            continue
        archive.mkdir(parents=True, exist_ok=True)
        if not (archive / path.name).exists():
            shutil.copy2(path, archive / path.name)
        temporary = path.with_name(path.name + ".tmp")
        with temporary.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=METADATA_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metadata_dir", type=Path)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    run(args.metadata_dir, args.archive, args.apply)
