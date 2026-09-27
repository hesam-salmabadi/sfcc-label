"""Archive four local Chapleau copies only after byte-identical replacement.

Run without --apply for a read-only preflight. Original workbooks and level-0
tables are never changed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import tempfile
from pathlib import Path


REPLACEMENTS = {"CP01": "chapleau_MW1_T06", "CP02": "chapleau_JP1_T06",
                "CP03": "chapleau_AS3_T06", "CP04": "chapleau_BS1_T06"}


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
    chapleau_metadata = metadata_dir / "chapleau_sensors.csv"
    metadata_columns, metadata_rows = _read(local_metadata)
    status_columns, status_rows = _read(local_status)
    _, chapleau_rows = _read(chapleau_metadata)
    new_ids = {row["sensor_id"] for row in chapleau_rows}
    target_ids = {f"local_{site}" for site in REPLACEMENTS}
    active_targets = [row for row in metadata_rows if row["sensor_id"] in target_ids]
    if len(active_targets) != 4 or any(row["network"] != "Chapleau" for row in active_targets):
        raise ValueError("expected four active local Chapleau records")
    if {row["sensor_id"] for row in status_rows if row["sensor_id"] in target_ids} != target_ids:
        raise ValueError("missing active local Chapleau status")
    manifest = []
    for site, replacement in REPLACEMENTS.items():
        if replacement not in new_ids:
            raise ValueError(f"missing replacement metadata for {site}")
        old = data_root / "standardized/local" / f"local_{site}.csv"
        new = data_root / "standardized/chapleau" / f"{replacement}.csv"
        if not old.is_file() or not new.is_file():
            raise FileNotFoundError(f"missing old or replacement file for {site}")
        old_hash = _hash(old)
        if old_hash != _hash(new):
            raise ValueError(f"replacement is not byte-identical for {site}")
        manifest.append({"local_sensor_id": f"local_{site}",
                         "replacement_sensor_id": replacement, "sha256": old_hash})
    print("Verified four byte-identical Chapleau replacements")
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
    with tempfile.TemporaryDirectory(prefix=".sfcc-chapleau-retire-", dir=metadata_dir) as temporary:
        stage = Path(temporary)
        _write(stage / local_metadata.name, metadata_columns, remaining_metadata)
        _write(stage / local_status.name, status_columns, remaining_status)
        try:
            for site in REPLACEMENTS:
                original = data_root / "standardized/local" / f"local_{site}.csv"
                destination = archived_files / original.name
                original.replace(destination)
                moved.append((destination, original))
            (stage / local_metadata.name).replace(local_metadata)
            (stage / local_status.name).replace(local_status)
        except Exception:
            shutil.copy2(archive / local_metadata.name, local_metadata)
            shutil.copy2(archive / local_status.name, local_status)
            for archived, original in reversed(moved):
                archived.replace(original)
            raise
    print("Archived four local CP files and updated active local metadata/status")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    retire(args.data_root.resolve(), args.archive.resolve(), args.apply)


if __name__ == "__main__":
    main()
