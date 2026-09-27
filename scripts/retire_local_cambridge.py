"""Archive nine local Cambridge Bay copies after byte-identical replacement.

Run without --apply for a read-only preflight. Original level-0 and Cambridge
Bay source files are never changed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import tempfile
from pathlib import Path


def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or ()), list(reader)


def _write(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def retire(data_root: Path, archive: Path, apply: bool = False) -> None:
    metadata_dir = data_root / "metadata"
    local_dir = data_root / "standardized" / "local"
    cambridge_dir = data_root / "standardized" / "cambridge_bay"
    local_metadata = metadata_dir / "local_sensors.csv"
    local_status = metadata_dir / "local_import_status.csv"
    cambridge_metadata = metadata_dir / "cambridge_bay_sensors.csv"
    if archive.parent != data_root / "archive":
        raise ValueError("archive must be a named folder directly under data_root/archive")
    if archive.exists():
        raise FileExistsError(f"archive already exists: {archive}")
    metadata_columns, metadata_rows = _read(local_metadata)
    status_columns, status_rows = _read(local_status)
    _, cambridge_rows = _read(cambridge_metadata)
    cambridge_ids = {row["sensor_id"] for row in cambridge_rows}
    targets = [row for row in metadata_rows if row["network"] == "Cambridge Bay"]
    if len(targets) != 9 or len({row["sensor_id"] for row in targets}) != 9:
        raise ValueError(f"expected 9 distinct local Cambridge Bay sites; found {len(targets)}")
    target_ids = {row["sensor_id"] for row in targets}
    status_by_id = {row["sensor_id"]: row for row in status_rows}
    manifest = []
    for row in targets:
        site_id = row["site_id"]
        old_id = row["sensor_id"]
        new_id = f"cambridge_bay_{site_id}_05cm_2019"
        if new_id not in cambridge_ids or status_by_id.get(old_id, {}).get("status") != "imported":
            raise ValueError(f"missing active replacement or import status for {old_id}")
        old_file = local_dir / f"{old_id}.csv"
        new_file = cambridge_dir / f"{new_id}.csv"
        if not old_file.is_file() or not new_file.is_file():
            raise ValueError(f"missing observation file for {old_id}")
        old_hash = _sha256(old_file)
        if old_hash != _sha256(new_file):
            raise ValueError(f"replacement is not byte-identical for {old_id}")
        manifest.append({"local_sensor_id": old_id,
                         "replacement_sensor_id": new_id,
                         "sha256": old_hash})
    print(f"Verified {len(manifest)} byte-identical Cambridge Bay replacements")
    print(f"Other local sensors to retain: {len(metadata_rows) - len(targets)}")
    print(f"Archive destination: {archive}")
    if not apply:
        return
    archive.mkdir(parents=True)
    archived_files = archive / "observations"
    archived_files.mkdir()
    shutil.copy2(local_metadata, archive / local_metadata.name)
    shutil.copy2(local_status, archive / local_status.name)
    _write(archive / "match_manifest.csv",
           ["local_sensor_id", "replacement_sensor_id", "sha256"], manifest)
    remaining_metadata = [row for row in metadata_rows if row["sensor_id"] not in target_ids]
    remaining_status = [row for row in status_rows if row["sensor_id"] not in target_ids]
    moved = []
    with tempfile.TemporaryDirectory(prefix=".sfcc-cambridge-retire-", dir=metadata_dir) as temporary:
        stage = Path(temporary)
        staged_metadata = stage / local_metadata.name
        staged_status = stage / local_status.name
        _write(staged_metadata, metadata_columns, remaining_metadata)
        _write(staged_status, status_columns, remaining_status)
        try:
            for old_id in sorted(target_ids):
                original = local_dir / f"{old_id}.csv"
                destination = archived_files / original.name
                original.replace(destination)
                moved.append((destination, original))
            staged_metadata.replace(local_metadata)
            staged_status.replace(local_status)
        except Exception:
            shutil.copy2(archive / local_metadata.name, local_metadata)
            shutil.copy2(archive / local_status.name, local_status)
            for archived, original in reversed(moved):
                archived.replace(original)
            raise
    print(f"Archived {len(moved)} local Cambridge Bay CSVs and updated active metadata/status")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    retire(args.data_root.resolve(), args.archive.resolve(), args.apply)


if __name__ == "__main__":
    main()
