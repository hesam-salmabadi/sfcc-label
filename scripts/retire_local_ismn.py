"""Archive local Alaska/RISMA copies after verifying direct ISMN replacements.

Run without --apply for a read-only preflight. The original level-0 tables are
never modified. The archive retains raw-value-bearing standardized files.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path


NETWORKS = {"Alaska ISMN", "RISMA ISMN"}
MANIFEST_COLUMNS = (
    "local_sensor_id", "ismn_site_id", "ismn_network", "ismn_station",
    "local_first_utc", "local_last_utc", "ismn_shallow_first_utc",
    "ismn_shallow_last_utc", "ismn_shallow_sensor_count",
)


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or ()), list(reader)


def write_table(path: Path, columns: list[str] | tuple[str, ...],
                rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def observation_span(path: Path) -> tuple[str, str]:
    with path.open("rb") as stream:
        stream.readline()
        first = stream.readline().split(b",", 1)[0].decode("ascii")
        size = stream.seek(0, 2)
        stream.seek(max(0, size - 16384))
        lines = [line for line in stream.read().splitlines() if line]
        last = lines[-1].split(b",", 1)[0].decode("ascii")
    if not first or not last:
        raise ValueError(f"empty observations: {path}")
    return first, last


def same_location(a: dict[str, str], b: dict[str, str]) -> bool:
    return (abs(float(a["latitude"]) - float(b["latitude"])) < 0.000001 and
            abs(float(a["longitude"]) - float(b["longitude"])) < 0.000001)


def retire(data_root: Path, archive: Path, apply: bool = False) -> None:
    local_dir = data_root / "standardized" / "local"
    ismn_dir = data_root / "standardized" / "ismn"
    metadata_dir = data_root / "metadata"
    local_metadata = metadata_dir / "local_sensors.csv"
    local_status = metadata_dir / "local_import_status.csv"
    if archive.parent != data_root / "archive":
        raise ValueError("archive must be a named folder directly under data_root/archive")
    if archive.exists():
        raise FileExistsError(f"archive already exists: {archive}")

    metadata_columns, metadata_rows = read_table(local_metadata)
    status_columns, status_rows = read_table(local_status)
    _, ismn_sites = read_table(metadata_dir / "ismn_sites.csv")
    _, ismn_sensors = read_table(metadata_dir / "ismn_sensors.csv")
    _, ismn_status = read_table(metadata_dir / "ismn_import_status.csv")
    imported_ids = {row["sensor_id"] for row in ismn_status if row["status"] == "imported"}
    by_site: dict[str, list[dict[str, str]]] = defaultdict(list)
    for sensor in ismn_sensors:
        if sensor["sensor_id"] in imported_ids and float(sensor["depth_cm"]) <= 10:
            by_site[sensor["site_id"]].append(sensor)

    targets = [row for row in metadata_rows if row["network"] in NETWORKS]
    target_ids = {row["sensor_id"] for row in targets}
    if len(targets) != 67 or len(target_ids) != 67:
        raise ValueError(f"expected 67 distinct Alaska/RISMA local sites; found {len(targets)}")
    status_by_id = {row["sensor_id"]: row for row in status_rows}
    manifest = []
    for local in targets:
        local_id = local["sensor_id"]
        local_file = local_dir / f"{local_id}.csv"
        if not local_file.is_file() or status_by_id.get(local_id, {}).get("status") != "imported":
            raise ValueError(f"missing active local observation or status for {local_id}")
        matches = [site for site in ismn_sites if same_location(local, site)]
        if len(matches) != 1:
            raise ValueError(f"expected one exact-coordinate ISMN site for {local_id}, got {len(matches)}")
        site = matches[0]
        shallow = by_site[site["site_id"]]
        if not shallow:
            raise ValueError(f"no imported shallow ISMN sensor for {local_id}")
        spans = []
        for sensor in shallow:
            path = ismn_dir / f"{sensor['sensor_id']}.csv"
            if not path.is_file():
                raise ValueError(f"missing imported ISMN file: {path}")
            spans.append(observation_span(path))
        local_first, local_last = (status_by_id[local_id]["first_utc"],
                                   status_by_id[local_id]["last_utc"])
        ismn_first = min(first for first, _ in spans)
        ismn_last = max(last for _, last in spans)
        if ismn_first > local_first or ismn_last < local_last:
            raise ValueError(f"ISMN time span does not cover local site {local_id}")
        manifest.append({
            "local_sensor_id": local_id,
            "ismn_site_id": site["site_id"],
            "ismn_network": site["network"],
            "ismn_station": site["station"],
            "local_first_utc": local_first,
            "local_last_utc": local_last,
            "ismn_shallow_first_utc": ismn_first,
            "ismn_shallow_last_utc": ismn_last,
            "ismn_shallow_sensor_count": str(len(shallow)),
        })

    print(f"Verified {len(manifest)} exact-location Alaska/RISMA sites with shallow ISMN coverage")
    print(f"Other local sensors to retain: {len(metadata_rows) - len(targets)}")
    print(f"Archive destination: {archive}")
    if not apply:
        return

    archive.mkdir(parents=True)
    archived_observations = archive / "observations"
    archived_observations.mkdir()
    shutil.copy2(local_metadata, archive / local_metadata.name)
    shutil.copy2(local_status, archive / local_status.name)
    write_table(archive / "match_manifest.csv", MANIFEST_COLUMNS, manifest)
    remaining_metadata = [row for row in metadata_rows if row["sensor_id"] not in target_ids]
    remaining_status = [row for row in status_rows if row["sensor_id"] not in target_ids]
    moved = []
    with tempfile.TemporaryDirectory(prefix=".sfcc-ismn-retire-", dir=metadata_dir) as temporary:
        stage = Path(temporary)
        staged_metadata = stage / local_metadata.name
        staged_status = stage / local_status.name
        write_table(staged_metadata, metadata_columns, remaining_metadata)
        write_table(staged_status, status_columns, remaining_status)
        try:
            for local_id in sorted(target_ids):
                original = local_dir / f"{local_id}.csv"
                destination = archived_observations / original.name
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
    print(f"Archived {len(moved)} local ISMN-derived CSVs and updated active metadata/status")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    retire(args.data_root.resolve(), args.archive.resolve(), args.apply)


if __name__ == "__main__":
    main()
