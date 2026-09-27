"""Archive two verified local BERMS copies after source-profile import.

Run without --apply for a read-only preflight. Original BERMS CSV/RData and
OneDrive level-0 inputs are never modified.
"""

from __future__ import annotations

import argparse
import csv
import math
import shutil
import tempfile
from pathlib import Path


REPLACEMENTS = {"BS01": "berms_BS01_T005cm", "JP01": "berms_JP01_T005cm"}


def read(path: Path):
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or ()), list(reader)


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def observed(path: Path, require_empty_other: bool = False) -> dict[str, float]:
    result = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if require_empty_other and (row["soil_moisture_m3_m3"].lower() != "nan"
                                        or row["raw_value"].lower() != "nan"):
                raise ValueError(f"{path}: unexpected local moisture or raw data")
            if row["soil_temperature_c"].lower() != "nan":
                result[row["timestamp_utc"]] = float(row["soil_temperature_c"])
    return result


def retire(root: Path, archive: Path, apply: bool = False) -> None:
    if archive.parent != root / "archive" or archive.exists():
        raise ValueError("archive must be a new named folder under data_root/archive")
    local_metadata = root / "metadata/local_sensors.csv"
    local_status = root / "metadata/local_import_status.csv"
    berms_metadata = root / "metadata/berms_sensors.csv"
    metadata_cols, metadata_rows = read(local_metadata)
    status_cols, status_rows = read(local_status)
    _, new_rows = read(berms_metadata)
    new_ids = {row["sensor_id"] for row in new_rows}
    targets = {f"local_{site}" for site in REPLACEMENTS}
    active = [row for row in metadata_rows if row["sensor_id"] in targets]
    if len(active) != 2 or any(row["network"] != "BERMS" or row["depth_cm"] != "5.0"
                                for row in active):
        raise ValueError("expected two active 5 cm local BERMS records")
    if {row["sensor_id"] for row in status_rows if row["sensor_id"] in targets} != targets:
        raise ValueError("missing local import status")
    manifest = []
    for site, replacement in REPLACEMENTS.items():
        if replacement not in new_ids:
            raise ValueError(f"missing replacement metadata: {replacement}")
        old = root / "standardized/local" / f"local_{site}.csv"
        new = root / "standardized/berms" / f"{replacement}.csv"
        original = observed(old, require_empty_other=True)
        replacement_values = observed(new)
        mismatches = sum(
            hour not in replacement_values or not math.isclose(
                value, replacement_values[hour], rel_tol=0, abs_tol=1e-9)
            for hour, value in original.items()
        )
        if not original or mismatches:
            raise ValueError(f"{site}: {mismatches} unmatched observations")
        manifest.append({"local_sensor_id": f"local_{site}",
                         "replacement_sensor_id": replacement,
                         "matched_observations": len(original), "mismatches": 0})
    print("Verified two local 5 cm BERMS copies against publisher-depth replacements")
    if not apply:
        return
    archive.mkdir(parents=True)
    (archive / "observations").mkdir()
    shutil.copy2(local_metadata, archive / local_metadata.name)
    shutil.copy2(local_status, archive / local_status.name)
    write(archive / "match_manifest.csv",
          ["local_sensor_id", "replacement_sensor_id", "matched_observations", "mismatches"],
          manifest)
    moved = []
    with tempfile.TemporaryDirectory(prefix=".sfcc-berms-retire-", dir=root / "metadata") as temp:
        stage = Path(temp)
        write(stage / local_metadata.name, metadata_cols,
              [row for row in metadata_rows if row["sensor_id"] not in targets])
        write(stage / local_status.name, status_cols,
              [row for row in status_rows if row["sensor_id"] not in targets])
        try:
            for site in REPLACEMENTS:
                old = root / "standardized/local" / f"local_{site}.csv"
                destination = archive / "observations" / old.name
                old.replace(destination)
                moved.append((destination, old))
            (stage / local_metadata.name).replace(local_metadata)
            (stage / local_status.name).replace(local_status)
        except Exception:
            shutil.copy2(archive / local_metadata.name, local_metadata)
            shutil.copy2(archive / local_status.name, local_status)
            for destination, old in reversed(moved):
                destination.replace(old)
            raise
    print(f"Archived two local BERMS files in {archive}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    retire(args.data_root.resolve(), args.archive.resolve(), args.apply)
