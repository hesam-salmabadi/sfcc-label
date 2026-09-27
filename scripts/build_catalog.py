#!/usr/bin/env python3
"""Build the schema-compatible merged metadata catalog."""
from __future__ import annotations

import argparse
import csv
import io
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sfcc_label.io import METADATA_COLUMNS


def read_rows(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != METADATA_COLUMNS:
        raise ValueError(f"{path}: metadata header does not match the package schema")
    return [{column: row[column] for column in METADATA_COLUMNS} for row in reader]


def build(metadata_dir: Path, output: Path, manifest: Path, apply: bool) -> None:
    files = sorted(p for p in metadata_dir.glob("*_sensors.csv") if not p.name.startswith("._"))
    if not files:
        raise SystemExit(f"No source metadata files found under {metadata_dir}")
    rows: list[dict[str, str]] = []
    manifest_rows = []
    seen: set[str] = set()
    for path in files:
        source_rows = read_rows(path)
        for row in source_rows:
            sensor_id = row["sensor_id"]
            if sensor_id in seen:
                raise ValueError(f"duplicate sensor_id in catalog: {sensor_id}")
            seen.add(sensor_id)
        rows.extend(source_rows)
        manifest_rows.append({"metadata_file": path.name, "rows": len(source_rows),
                              "source_values": ";".join(sorted({r["source"] for r in source_rows}))})
    rows.sort(key=lambda row: (row["source"], row["sensor_id"]))
    print(f"Catalog rows: {len(rows)} from {len(files)} metadata files")
    print("Source counts:", dict(sorted(Counter(row["source"] for row in rows).items())))
    if not apply:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = output.parent / "archive" / f"metadata_catalog_{stamp}"
    if output.exists() or manifest.exists():
        archive.mkdir(parents=True, exist_ok=True)
        if output.exists(): shutil.copy2(output, archive / output.name)
        if manifest.exists(): shutil.copy2(manifest, archive / manifest.name)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=METADATA_COLUMNS)
        writer.writeheader(); writer.writerows(rows)
    temporary.replace(output)
    temporary = manifest.with_suffix(manifest.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("metadata_file", "rows", "source_values"))
        writer.writeheader(); writer.writerows(manifest_rows)
    temporary.replace(manifest)
    print(f"Wrote {output}")
    print(f"Wrote {manifest}")
    if archive.exists(): print(f"Backed up previous catalog to {archive}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    build(args.metadata_dir, args.output, args.manifest, args.apply)
