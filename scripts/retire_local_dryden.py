"""Archive local_DD01 only after its Dryden replacement is byte-identical.

Without --apply this is a read-only preflight. Original source and level-0
files are untouched; active local metadata/status are backed up in the archive.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import tempfile
from pathlib import Path


def _read(path: Path):
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or ()), list(reader)


def _write(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def retire(data_root: Path, archive: Path, apply: bool = False) -> None:
    if archive.parent != data_root / "archive" or archive.exists():
        raise ValueError("archive must be a new named folder directly under data_root/archive")
    metadata_dir = data_root / "metadata"
    local_metadata = metadata_dir / "local_sensors.csv"
    local_status = metadata_dir / "local_import_status.csv"
    dryden_metadata = metadata_dir / "dryden_sensors.csv"
    old_file = data_root / "standardized/local/local_DD01.csv"
    new_file = data_root / "standardized/dryden/dryden_Dryden_6.csv"
    metadata_columns, metadata_rows = _read(local_metadata)
    status_columns, status_rows = _read(local_status)
    _, dryden_rows = _read(dryden_metadata)
    targets = [row for row in metadata_rows if row["sensor_id"] == "local_DD01"]
    if len(targets) != 1 or targets[0]["network"] != "Dryden":
        raise ValueError("expected one active local_DD01 Dryden record")
    if [row["sensor_id"] for row in status_rows].count("local_DD01") != 1:
        raise ValueError("expected one active local_DD01 status record")
    if [row["sensor_id"] for row in dryden_rows].count("dryden_Dryden_6") != 1:
        raise ValueError("Dryden replacement metadata is missing or repeated")
    if not old_file.is_file() or not new_file.is_file():
        raise FileNotFoundError("old or replacement Dryden observation is missing")
    old_hash, new_hash = _hash(old_file), _hash(new_file)
    if old_hash != new_hash:
        raise ValueError("Dryden replacement is not byte-identical to local_DD01")
    print(f"Verified byte-identical Dryden replacement: {old_hash}")
    print(f"Archive destination: {archive}")
    if not apply:
        return
    archive.mkdir(parents=True)
    archived_files = archive / "observations"
    archived_files.mkdir()
    shutil.copy2(local_metadata, archive / local_metadata.name)
    shutil.copy2(local_status, archive / local_status.name)
    _write(archive / "match_manifest.csv",
           ["local_sensor_id", "replacement_sensor_id", "sha256"],
           [{"local_sensor_id": "local_DD01", "replacement_sensor_id": "dryden_Dryden_6",
             "sha256": old_hash}])
    remaining_metadata = [row for row in metadata_rows if row["sensor_id"] != "local_DD01"]
    remaining_status = [row for row in status_rows if row["sensor_id"] != "local_DD01"]
    with tempfile.TemporaryDirectory(prefix=".sfcc-dryden-retire-", dir=metadata_dir) as temporary:
        stage = Path(temporary)
        _write(stage / local_metadata.name, metadata_columns, remaining_metadata)
        _write(stage / local_status.name, status_columns, remaining_status)
        archived = archived_files / old_file.name
        try:
            old_file.replace(archived)
            (stage / local_metadata.name).replace(local_metadata)
            (stage / local_status.name).replace(local_status)
        except Exception:
            shutil.copy2(archive / local_metadata.name, local_metadata)
            shutil.copy2(archive / local_status.name, local_status)
            if archived.exists():
                archived.replace(old_file)
            raise
    print("Archived local_DD01 and updated active local metadata/status")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    retire(args.data_root.resolve(), args.archive.resolve(), args.apply)


if __name__ == "__main__":
    main()
