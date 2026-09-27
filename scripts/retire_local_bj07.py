"""Archive the duplicate local BJ07 5 cm stream after publisher import."""
from __future__ import annotations
import argparse, csv, shutil, tempfile
from pathlib import Path

def read(path):
    with path.open(newline="", encoding="utf-8") as f:
        r=csv.DictReader(f); return list(r.fieldnames or ()), list(r)

def write(path, cols, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)

def retire(root: Path, archive: Path, apply=False):
    if archive.parent != root / "archive" or archive.exists():
        raise ValueError("archive must be a new folder directly under data_root/archive")
    old = root / "standardized/local/local_BJ07.csv"
    replacement = root / "standardized/uqam_ibutton_bj/uqam_BJ07_5cm.csv"
    if not old.is_file() or not replacement.is_file(): raise FileNotFoundError("BJ07 source or replacement missing")
    if old.read_bytes() != replacement.read_bytes(): raise ValueError("BJ07 files are not identical")
    metadata = root / "metadata/local_sensors.csv"; status = root / "metadata/local_import_status.csv"
    mcols, mrows = read(metadata); scols, srows = read(status)
    target = [r for r in mrows if r["sensor_id"] == "local_BJ07"]
    if len(target) != 1 or target[0]["depth_cm"] != "5.0" or target[0]["network"] != "James Bay": raise ValueError("unexpected local BJ07 metadata")
    if not any(r["sensor_id"] == "local_BJ07" for r in srows): raise ValueError("missing local BJ07 status")
    print("Verified local_BJ07 is byte-identical to uqam_BJ07_5cm")
    if not apply: return
    archive.mkdir(parents=True); (archive / "observations").mkdir()
    shutil.copy2(metadata, archive / metadata.name); shutil.copy2(status, archive / status.name)
    write(archive / "match_manifest.csv", ["local_sensor_id", "replacement_sensor_id", "byte_identical"], [{"local_sensor_id":"local_BJ07", "replacement_sensor_id":"uqam_BJ07_5cm", "byte_identical":"true"}])
    with tempfile.TemporaryDirectory(prefix=".sfcc-bj07-retire-", dir=root / "metadata") as temp:
        stage=Path(temp); write(stage / metadata.name, mcols, [r for r in mrows if r["sensor_id"] != "local_BJ07"]); write(stage / status.name, scols, [r for r in srows if r["sensor_id"] != "local_BJ07"])
        archived=archive / "observations/local_BJ07.csv"
        try:
            old.replace(archived); (stage / metadata.name).replace(metadata); (stage / status.name).replace(status)
        except Exception:
            shutil.copy2(archive / metadata.name, metadata); shutil.copy2(archive / status.name, status)
            if archived.exists(): archived.replace(old)
            raise
    print(f"Archived local_BJ07 in {archive}")

if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("data_root", type=Path); p.add_argument("archive", type=Path); p.add_argument("--apply", action="store_true"); a=p.parse_args(); retire(a.data_root.resolve(), a.archive.resolve(), a.apply)
