"""Archive legacy NI/NT level-0 exports after the publisher import succeeds.

Run without --apply for a read-only preflight. This affects only exact
local_NI<digits>/local_NT<digits> sensor IDs and leaves the level-0 source alone.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import tempfile
from pathlib import Path


LEGACY_ID = re.compile(r"local_N[IT]\d+")


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or ()), list(reader)


def write_table(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def retire(data_root: Path, archive: Path, apply: bool = False) -> None:
    legacy_dir = data_root / "standardized" / "local"
    publisher_dir = data_root / "standardized" / "nrcan_ibutton"
    local_metadata = data_root / "metadata" / "local_sensors.csv"
    local_status = data_root / "metadata" / "local_import_status.csv"
    publisher_metadata = data_root / "metadata" / "nrcan_ibutton_sensors.csv"
    if archive.exists():
        raise FileExistsError(f"archive already exists: {archive}")
    if archive.parent != data_root / "archive":
        raise ValueError("archive must be a named folder directly under data_root/archive")

    files = {path.stem: path for path in legacy_dir.iterdir()
             if path.is_file() and LEGACY_ID.fullmatch(path.stem) and path.suffix == ".csv"}
    metadata_columns, metadata_rows = read_table(local_metadata)
    status_columns, status_rows = read_table(local_status)
    _, publisher_rows = read_table(publisher_metadata)
    metadata_ids = {row["sensor_id"] for row in metadata_rows if LEGACY_ID.fullmatch(row["sensor_id"])}
    status_ids = {row["sensor_id"] for row in status_rows if LEGACY_ID.fullmatch(row["sensor_id"])}
    publisher_ids = {row["sensor_id"] for row in publisher_rows}
    if not files or set(files) != metadata_ids:
        raise ValueError("legacy observation files do not exactly match active local metadata")
    if len(metadata_ids) != 103 or len(status_ids) != 105:
        raise ValueError(f"unexpected NI/NT inventory: {len(metadata_ids)} files, {len(status_ids)} statuses")
    if any(row["status"] != "imported" for row in status_rows if row["sensor_id"] in files):
        raise ValueError("a legacy observation file lacks imported status")
    for legacy_id in status_ids:
        publisher_id = legacy_id.replace("local_", "nrcan_ibutton_", 1)
        if publisher_id not in publisher_ids or not (publisher_dir / f"{publisher_id}.csv").is_file():
            raise ValueError(f"publisher replacement missing for {legacy_id}")

    print(f"Publisher replacement verified for {len(status_ids)} NI/NT sites")
    print(f"Legacy files to remove from standardized/local: {len(files)}")
    print(f"Other local sensors to retain: {len(metadata_rows) - len(metadata_ids)}")
    print(f"Archive destination: {archive}")
    if not apply:
        return

    archive.mkdir(parents=True)
    archived_files = archive / "observations"
    archived_files.mkdir()
    shutil.copy2(local_metadata, archive / local_metadata.name)
    shutil.copy2(local_status, archive / local_status.name)

    remaining_metadata = [row for row in metadata_rows if row["sensor_id"] not in metadata_ids]
    remaining_status = [row for row in status_rows if row["sensor_id"] not in status_ids]
    moved = []
    with tempfile.TemporaryDirectory(prefix=".sfcc-nrcan-retire-", dir=local_metadata.parent) as temporary:
        stage = Path(temporary)
        new_metadata = stage / local_metadata.name
        new_status = stage / local_status.name
        write_table(new_metadata, metadata_columns, remaining_metadata)
        write_table(new_status, status_columns, remaining_status)
        try:
            for sensor_id, path in sorted(files.items()):
                destination = archived_files / path.name
                path.replace(destination)
                moved.append((destination, path))
            new_metadata.replace(local_metadata)
            new_status.replace(local_status)
        except Exception:
            shutil.copy2(archive / local_metadata.name, local_metadata)
            shutil.copy2(archive / local_status.name, local_status)
            for archived, original in reversed(moved):
                archived.replace(original)
            raise
    print(f"Archived {len(moved)} legacy CSVs and removed NI/NT rows from active metadata/status")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    retire(args.data_root.resolve(), args.archive.resolve(), args.apply)


if __name__ == "__main__":
    main()
