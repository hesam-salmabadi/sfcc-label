"""Archive superseded local temperature-only copies after source-series matching.

Without --apply, this is a read-only preflight. Publisher files and level-0
inputs are never modified. Every nonmissing local temperature must match one
publisher stream at the same normalized UTC hour; local moisture/raw must be
missing, so paired TEROS records are never selected.
"""

from __future__ import annotations

import argparse
import csv
import math
import shutil
import statistics
import tempfile
from pathlib import Path


NETWORKS = {"St_Marthe", "St_Maurice", "James Bay", "Montmorency Forest", "Kuujjuarapik"}


def read(path: Path):
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or ()), list(reader)


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def observed(path: Path) -> dict[str, float]:
    result = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            value = row["soil_temperature_c"]
            if value.lower() != "nan":
                result[row["timestamp_utc"]] = float(value)
    return result


def candidates(root: Path, site: str, network: str) -> list[Path]:
    base = root / "standardized"
    if network in {"St_Marthe", "St_Maurice"}:
        plot = ("SMT" if network == "St_Marthe" else "SMU") + chr(
            ord("A") + int(site[2:]) - 1)
        return sorted((base / "st_marthe_maurice").glob(f"st_{plot}_pit*.csv"))
    code = {"James Bay": "bj", "Montmorency Forest": "fm",
            "Kuujjuarapik": "kj"}[network]
    return sorted((base / f"uqam_ibutton_{code}").glob(f"uqam_{site}_*cm.csv"))


def retire(root: Path, archive: Path, apply: bool = False) -> None:
    if archive.parent != root / "archive" or archive.exists():
        raise ValueError("archive must be a new named folder directly under data_root/archive")
    metadata = root / "metadata/local_sensors.csv"
    status = root / "metadata/local_import_status.csv"
    metadata_columns, metadata_rows = read(metadata)
    status_columns, status_rows = read(status)
    targets = [row for row in metadata_rows if row["network"] in NETWORKS
               and row["depth_cm"].lower() == "nan"]
    if len(targets) != 53:
        raise ValueError(f"expected 53 depth-unknown local copies; found {len(targets)}")
    manifest = []
    for row in targets:
        site = row["site_id"]
        old = root / "standardized/local" / f"local_{site}.csv"
        if not old.is_file():
            raise FileNotFoundError(old)
        with old.open(newline="", encoding="utf-8") as stream:
            for sample in csv.DictReader(stream):
                if sample["soil_moisture_m3_m3"].lower() != "nan" or sample["raw_value"].lower() != "nan":
                    raise ValueError(f"{site}: local record has moisture or raw values; retain it")
        original = observed(old)
        if not original:
            raise ValueError(f"{site}: no original temperatures to verify")
        if row["network"] in {"St_Marthe", "St_Maurice"}:
            pit_files = [path for path in candidates(root, site, row["network"])
                         if path.stem.endswith("_2cm")]
            if len(pit_files) != 5:
                raise ValueError(f"{site}: expected five publisher 2 cm pit streams")
            pits = [observed(path) for path in pit_files]
            mismatches = 0
            for hour, value in original.items():
                readings = [pit[hour] for pit in pits if hour in pit]
                if not readings or not math.isclose(statistics.median(readings), value, abs_tol=1e-9):
                    mismatches += 1
            replacement = "median(" + ";".join(path.stem for path in pit_files) + ")"
        else:
            best = None
            for candidate in candidates(root, site, row["network"]):
                newer = observed(candidate)
                mismatch_count = sum(newer.get(hour) != value for hour, value in original.items())
                score = (mismatch_count, -len(newer), candidate.name)
                if best is None or score < best[0]:
                    best = (score, candidate)
            if best is None:
                raise ValueError(f"{site}: no publisher stream")
            mismatches = best[0][0]
            replacement = best[1].stem
        if mismatches:
            raise ValueError(f"{site}: publisher reconstruction differs at {mismatches} hours")
        manifest.append({"local_sensor_id": row["sensor_id"],
                         "replacement_sensor_id": replacement,
                         "matched_observations": len(original)})
    target_ids = {row["sensor_id"] for row in targets}
    if {row["sensor_id"] for row in status_rows if row["sensor_id"] in target_ids} != target_ids:
        raise ValueError("missing local import status for one or more targets")
    print(f"Verified {len(manifest)} local temperature streams against publisher streams")
    if not apply:
        return
    archive.mkdir(parents=True)
    (archive / "observations").mkdir()
    shutil.copy2(metadata, archive / metadata.name)
    shutil.copy2(status, archive / status.name)
    write(archive / "match_manifest.csv",
          ["local_sensor_id", "replacement_sensor_id", "matched_observations"], manifest)
    with tempfile.TemporaryDirectory(prefix=".sfcc-local-publisher-", dir=root / "metadata") as temporary:
        stage = Path(temporary)
        write(stage / metadata.name, metadata_columns,
              [row for row in metadata_rows if row["sensor_id"] not in target_ids])
        write(stage / status.name, status_columns,
              [row for row in status_rows if row["sensor_id"] not in target_ids])
        moved = []
        try:
            for row in targets:
                old = root / "standardized/local" / f'{row["sensor_id"]}.csv'
                archived = archive / "observations" / old.name
                old.replace(archived)
                moved.append((archived, old))
            (stage / metadata.name).replace(metadata)
            (stage / status.name).replace(status)
        except Exception:
            shutil.copy2(archive / metadata.name, metadata)
            shutil.copy2(archive / status.name, status)
            for archived, old in reversed(moved):
                archived.replace(old)
            raise
    print(f"Archived {len(manifest)} local copies; TEROS moisture streams remain active")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    retire(args.data_root.resolve(), args.archive.resolve(), args.apply)
