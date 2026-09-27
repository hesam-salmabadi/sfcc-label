"""Archive the legacy one-stream TVC local files after HydraProbe import.

The operation is recoverable: files and the previous local metadata/status are
copied under data_root/archive before the active local rows are removed.
Run without --apply for preflight.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import tempfile
from pathlib import Path


TARGETS = {"TV01", "TV02", "TV03", "TV04", "TV05", "TV06", "TV11", "TV33", "TV44", "TV55", "TV66"}
STATION_BY_SITE = {
    "TV01": "CalTarget", "TV11": "CalTarget", "TV02": "DriftSite",
    "TV03": "MainMet", "TV33": "MainMet", "TV04": "OldTrench",
    "TV44": "OldTrench", "TV05": "SouthTundra", "TV55": "SouthTundra",
    "TV06": "ValleyBottom", "TV66": "ValleyBottom",
}


def read(path: Path):
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or ()), list(reader)


def write(path: Path, columns, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader(); writer.writerows(rows)


def retire(root: Path, archive: Path, apply: bool = False) -> None:
    if archive.parent != root / "archive" or archive.exists():
        raise ValueError("archive must be a new named folder under data_root/archive")
    local_dir = root / "standardized/local"
    metadata = root / "metadata/local_sensors.csv"
    status = root / "metadata/local_import_status.csv"
    new_sensors = root / "metadata/tvc_hydraprobe_sensors.csv"
    new_observations = root / "standardized/tvc_hydraprobe"
    metadata_cols, metadata_rows = read(metadata)
    status_cols, status_rows = read(status)
    _, new_rows = read(new_sensors)
    stations = {row["site_id"] for row in new_rows}
    targets = [row for row in metadata_rows if row["site_id"] in TARGETS]
    if {row["site_id"] for row in targets} != TARGETS:
        raise ValueError(f"expected all {len(TARGETS)} legacy TVC sites in local metadata")
    if any(row["network"] != "Trail Valley Creek" or row["depth_cm"] != "5.0" for row in targets):
        raise ValueError("legacy TVC rows are not the expected 5 cm records")
    status_ids = {row["site_id"] for row in status_rows if row["site_id"] in TARGETS}
    if status_ids != TARGETS:
        raise ValueError("missing legacy TVC import status rows")
    manifest = []
    for site_id in sorted(TARGETS):
        path = local_dir / f"local_{site_id}.csv"
        if not path.is_file():
            raise ValueError(f"missing legacy observation {path}")
        station = STATION_BY_SITE[site_id]
        if station not in stations:
            raise ValueError(f"missing HydraProbe replacement station {station}")
        manifest.append({"legacy_site_id": site_id, "legacy_file": path.name,
                         "replacement_station": station,
                         "replacement_sensor_count": sum(row["site_id"] == station for row in new_rows)})
    print(f"Verified {len(manifest)} legacy TVC local files for archival")
    if not apply:
        return
    archive.mkdir(parents=True)
    (archive / "observations").mkdir()
    shutil.copy2(metadata, archive / metadata.name)
    shutil.copy2(status, archive / status.name)
    write(archive / "match_manifest.csv",
          ["legacy_site_id", "legacy_file", "replacement_station", "replacement_sensor_count"], manifest)
    remaining_metadata = [row for row in metadata_rows if row["site_id"] not in TARGETS]
    remaining_status = [row for row in status_rows if row["site_id"] not in TARGETS]
    moved = []
    with tempfile.TemporaryDirectory(prefix=".sfcc-tvc-retire-", dir=root / "metadata") as temp:
        stage = Path(temp)
        write(stage / metadata.name, metadata_cols, remaining_metadata)
        write(stage / status.name, status_cols, remaining_status)
        try:
            for site_id in sorted(TARGETS):
                original = local_dir / f"local_{site_id}.csv"
                destination = archive / "observations" / original.name
                original.replace(destination); moved.append((destination, original))
            (stage / metadata.name).replace(metadata)
            (stage / status.name).replace(status)
        except Exception:
            shutil.copy2(archive / metadata.name, metadata)
            shutil.copy2(archive / status.name, status)
            for archived, original in reversed(moved):
                archived.replace(original)
            raise
    print(f"Archived {len(moved)} legacy TVC files in {archive}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    retire(args.data_root.resolve(), args.archive.resolve(), args.apply)
