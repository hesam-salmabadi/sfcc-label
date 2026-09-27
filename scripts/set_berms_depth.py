"""Set BS01/JP01 to source-confirmed 5 cm, backing up active metadata.

Run without --apply for a read-only preflight. No observations or original
BERMS files are modified.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import tempfile
from pathlib import Path

from verify_berms_depth import check


SOURCE_FILES = {
    "BS01": "OBS_Soil_2016_AG.csv;OBS_Soil_2021_AG.csv",
    "JP01": "OJP_Soil_2015-2021_AG.csv",
}
TIME_NOTE = "UTC in legacy level-0 (unverified; BERMS RData says America/Regina)"
EVIDENCE_COLUMNS = ("sensor_id", "depth_cm", "source_files", "source_column",
                    "matched_hours", "mismatches", "processing_notebook",
                    "independent_publication")


def update(root: Path, apply: bool) -> None:
    metadata = root / "metadata/local_sensors.csv"
    archive = root / "archive/berms_depth_correction_20260926"
    with metadata.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        columns = list(reader.fieldnames or ())
        rows = list(reader)
    found = {row["site_id"]: row for row in rows if row["site_id"] in SOURCE_FILES}
    if set(found) != set(SOURCE_FILES):
        raise ValueError("BS01/JP01 are not both active local sensors")
    if any(row["network"] != "BERMS" or row["depth_cm"].lower() != "nan"
           for row in found.values()):
        raise ValueError("expected two BERMS sensors with unknown depth")
    if archive.exists():
        raise FileExistsError(archive)
    evidence = []
    for site, files in SOURCE_FILES.items():
        matched, mismatches = check(site)
        if not matched or mismatches:
            raise ValueError(f"{site}: source-to-standardized comparison failed")
        evidence.append({
            "sensor_id": f"local_{site}", "depth_cm": "5",
            "source_files": files, "source_column": "SoilTemp_005cm",
            "matched_hours": matched, "mismatches": mismatches,
            "processing_notebook": "/Volumes/Expansion/UQAM/BERMS/Data/berms/proc.ipynb",
            "independent_publication":
                "https://water.usask.ca/hillslope/documents/pdfs/2022/nehemy_2022_2.pdf",
        })
    print("Confirmed BS01/JP01 5 cm against all 78,915 observed standardized hours")
    if not apply:
        return
    archive.mkdir(parents=True)
    shutil.copy2(metadata, archive / "local_sensors_before.csv")
    for row in found.values():
        row["depth_cm"] = row["depth_from_cm"] = row["depth_to_cm"] = "5.0"
        row["timezone_original"] = TIME_NOTE
    with tempfile.TemporaryDirectory(prefix=".sfcc-berms-depth-", dir=metadata.parent) as temp:
        staged = Path(temp) / metadata.name
        with staged.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        with (archive / "depth_evidence.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=EVIDENCE_COLUMNS)
            writer.writeheader()
            writer.writerows(evidence)
        staged.replace(metadata)
    print(f"Updated two active metadata records; backup and evidence: {archive}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    update(args.data_root.resolve(), args.apply)
