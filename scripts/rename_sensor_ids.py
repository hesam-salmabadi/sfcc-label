"""Plan the consistent sensor naming scheme ``<src>_<site>_<depth>_<tag>``.

Default is a dry run: read the merged catalog and per-source metadata files,
derive a new sensor_id for every sensor, validate, and write the old->new map
plus a short report. Nothing on disk is renamed.

With ``--apply --map <reviewed map>``: back up metadata, rename standardized and
flag files/folders, rewrite sensor ids in metadata, rename the iButton transect
metadata files, and rebuild the catalog. Safe to re-run after an interruption.
"""

from __future__ import annotations

import argparse
import collections
import csv
import io
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from sfcc_label.naming import SENSOR_ID, SOURCE_CODES, ameriflux_tag, slug
from sfcc_label.naming import depth_token as naming_depth

IBUTTON_TRANSECTS = {"BJ": "james_bay", "FM": "montmorency", "KJ": "kuujjuarapik"}
SITE_OVERRIDES = {("tvc_boike", "N_Trail_Valley_Creek"): "tvc"}
NAME = SENSOR_ID


def depth_token(row: dict[str, str]) -> str:
    def parse(key: str) -> float:
        text = row[key]
        return math.nan if text in ("", "NaN") else float(text)
    return naming_depth(parse("depth_from_cm"), parse("depth_to_cm"))


def new_source(row: dict[str, str]) -> str:
    if row["source"] == "uqam_ibutton":
        return IBUTTON_TRANSECTS[row["site_id"][:2]]
    return row["source"]


def site_token(row: dict[str, str], source: str) -> str:
    if (source, row["site_id"]) in SITE_OVERRIDES:
        return SITE_OVERRIDES[(source, row["site_id"])]
    if source == "ismn":
        return slug(f"{row['network']} {row['station']}")
    if source == "ameriflux":
        return slug(row["source_id"])
    return slug(row["site_id"])


def tag_token(row: dict[str, str], source: str) -> str:
    old = row["sensor_id"]
    if source == "ameriflux":
        return ameriflux_tag(old[len(f"ameriflux_{row['source_id']}_"):] or "TS")
    if source == "ismn":
        return old.rsplit("_", 1)[1].lower()
    if source == "berms":
        return re.match(r"berms_[^_]+_(MR|M|T)", old).group(1).lower()
    if source == "cambridge_bay":
        return old.rsplit("_", 1)[1]
    if source == "chapleau":
        if m := re.search(r"_P(\d+[a-z])_M\d+$", old):
            return f"p{m.group(1)}"
        if re.search(r"_T\d+$", old):
            return "t"
    if source == "st_marthe_maurice":
        return re.search(r"_(pit\d+)_", old).group(1)
    if source == "tvc_boike":
        m = re.search(r"_v\d+to\d+cm_([a-z]+)$", old)
        return m.group(1) if m else "s1"
    if source == "tvc_hydraprobe":
        return re.search(r"_(h\d+)_", old).group(1)
    if source in ("dryden", "local", "nrcan_ibutton", *IBUTTON_TRANSECTS.values()):
        return "s1"
    raise ValueError(f"no tag rule for {old}")


def metadata_origins(metadata_dir: Path) -> dict[str, str]:
    origin = {}
    for path in sorted(metadata_dir.glob("*_sensors.csv")):
        if path.name.startswith("._"):
            continue
        with path.open(newline="") as stream:
            for row in csv.DictReader(stream):
                origin[row["sensor_id"]] = path.name
    return origin


def new_metadata_name(old_file: str, source: str) -> str:
    return f"{source}_sensors.csv" if old_file.startswith("uqam_ibutton_") else old_file


def find_file(root: Path, sensor_id: str, suffix: str) -> Path | None:
    hits = [p for p in root.glob(f"*/{sensor_id}{suffix}") if not p.name.startswith("._")]
    return hits[0] if len(hits) == 1 else None


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]], str]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    rows = list(reader)
    return list(reader.fieldnames or ()), rows, "\r\n" if b"\r\n" in raw[:4096] else "\n"


def write_table(path: Path, fields: list[str], rows: list[dict[str, str]], newline: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator=newline)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def unimported_ismn_pairs(metadata_dir: Path, known: set[str]) -> list[dict[str, str]]:
    """Pairing candidates that never produced a file still get a new-style id."""
    _, sites, _ = read_table(metadata_dir / "ismn_sites.csv")
    names = {s["site_id"]: s for s in sites}
    _, pairs, _ = read_table(metadata_dir / "ismn_pairing.csv")
    records = []
    for pair in pairs:
        if pair["sensor_id"] in known or pair["sensor_id"] in ("", "NaN"):
            continue
        if pair["site_id"] in names:
            site = slug(f"{names[pair['site_id']]['network']} {names[pair['site_id']]['station']}")
        else:  # site dropped from ismn_sites.csv; id is ismn_<network>_<station>_<digest>
            site = slug(pair["site_id"].removeprefix("ismn_").rsplit("_", 1)[0])
        row = {"depth_from_cm": str(float(pair["depth_from_m"]) * 100),
               "depth_to_cm": str(float(pair["depth_to_m"]) * 100)}
        new_id = "_".join(("ismn", site, depth_token(row),
                           pair["sensor_id"].rsplit("_", 1)[1].lower()))
        records.append({"old_id": pair["sensor_id"], "new_id": new_id, "old_source": "ismn",
                        "new_source": "ismn", "old_path": "", "new_path": "", "old_flag_path": "",
                        "new_flag_path": "", "old_metadata_file": "ismn_pairing.csv",
                        "new_metadata_file": "ismn_pairing.csv"})
    return records


def plan(data_root: Path, map_out: Path, report_out: Path) -> int:
    metadata_dir = data_root / "metadata"
    _, rows, _ = read_table(metadata_dir / "catalog.csv")
    origin = metadata_origins(metadata_dir)
    standardized = {p.stem: p for p in (data_root / "standardized").glob("*/*.csv") if not p.name.startswith("._")}
    flags = {p.name[:-len(".csv.gz")]: p for p in (data_root / "flags").glob("*/*.csv.gz") if not p.name.startswith("._")}

    records, problems = [], []
    for row in rows:
        source = new_source(row)
        new_id = "_".join((SOURCE_CODES[source], site_token(row, source), depth_token(row), tag_token(row, source)))
        if not NAME.match(new_id):
            problems.append(f"bad pattern: {row['sensor_id']} -> {new_id}")
        old_std = standardized.get(row["sensor_id"])
        if old_std is None:
            problems.append(f"no standardized file: {row['sensor_id']}")
        old_flag = flags.get(row["sensor_id"])
        old_meta = origin.get(row["sensor_id"], "")
        if not old_meta:
            problems.append(f"not in any *_sensors.csv: {row['sensor_id']}")
        records.append({
            "old_id": row["sensor_id"], "new_id": new_id,
            "old_source": row["source"], "new_source": source,
            "old_path": str(old_std.relative_to(data_root)) if old_std else "",
            "new_path": f"standardized/{source}/{new_id}.csv",
            "old_flag_path": str(old_flag.relative_to(data_root)) if old_flag else "",
            "new_flag_path": f"flags/{source}/{new_id}.csv.gz" if old_flag else "",
            "old_metadata_file": old_meta,
            "new_metadata_file": new_metadata_name(old_meta, source),
        })

    extra = unimported_ismn_pairs(metadata_dir, {r["old_id"] for r in records})
    problems += [f"bad pattern: {r['old_id']} -> {r['new_id']}" for r in extra if not NAME.match(r["new_id"])]
    records += extra

    counts = collections.Counter(r["new_id"].lower() for r in records)
    for name, n in counts.items():
        if n > 1:
            problems.append(f"duplicate new id ({n}x): {name}")
    if len(records) - len(extra) != len(standardized):
        problems.append(f"catalog rows {len(records) - len(extra)} != standardized files {len(standardized)}")

    map_out.parent.mkdir(parents=True, exist_ok=True)
    with map_out.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)

    by_source = collections.defaultdict(list)
    for r in records:
        by_source[r["new_source"]].append(r)
    lines = [f"sensors: {len(records) - len(extra)} (+{len(extra)} unimported ISMN pairing ids)",
             f"standardized files: {len(standardized)}",
             f"flag files matched: {sum(1 for r in records if r['old_flag_path'])} of {len(flags)}",
             f"problems: {len(problems)}", ""]
    for source in sorted(by_source):
        group = [r for r in by_source[source] if r["old_path"]]
        folders = sorted({str(Path(r["old_path"]).parent) for r in group})
        lines.append(f"## {source} ({len(group)} sensors) from {', '.join(folders)} -> standardized/{source}")
        for r in group[:3]:
            lines.append(f"   {r['old_id']:<62} -> {r['new_id']}")
    lines += ["", *problems[:200]]
    report_out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 1 if problems else 0


def move(old: Path, new: Path) -> bool:
    """Rename a file or folder plus its macOS ``._`` sidecar; skip if already done."""
    if old == new:
        return False
    if not old.exists():
        if new.exists():
            return False
        raise FileNotFoundError(old)
    if new.exists():
        raise FileExistsError(new)
    new.parent.mkdir(parents=True, exist_ok=True)
    old.rename(new)
    sidecar = old.with_name("._" + old.name)
    if sidecar.exists():
        sidecar.rename(new.with_name("._" + new.name))
    return True


def apply(data_root: Path, map_path: Path, stamp: str) -> None:
    metadata_dir = data_root / "metadata"
    _, records, _ = read_table(map_path)
    by_old = {r["old_id"]: r for r in records}

    archive = data_root / "archive" / f"rename_{stamp}" / "metadata"
    archive.mkdir(parents=True, exist_ok=True)
    for path in sorted(metadata_dir.glob("*.csv")):
        if not path.name.startswith("._") and not (archive / path.name).exists():
            shutil.copy2(path, archive / path.name)
    print(f"Backed up metadata to {archive}")

    for kind, old_key, new_key in (("standardized", "old_path", "new_path"), ("flags", "old_flag_path", "new_flag_path")):
        folders = {}
        for r in records:
            if r[old_key]:
                folders.setdefault(Path(r[old_key]).parent, set()).add(Path(r[new_key]).parent)
        for old_folder, targets in sorted(folders.items()):
            if len(targets) != 1:
                raise ValueError(f"{old_folder} maps to several folders: {targets}")
            move(data_root / old_folder, data_root / next(iter(targets)))
        moved = 0
        for r in records:
            if r[old_key]:
                current = data_root / Path(r[new_key]).parent / Path(r[old_key]).name
                moved += move(current, data_root / r[new_key])
        print(f"{kind}: renamed {moved} files")

    id_columns = ("sensor_id", "nearby_temperature_sensor_id")
    for path in sorted(metadata_dir.glob("*.csv")):
        if path.name.startswith("._") or path.name.startswith("catalog") or path.name == "sensor_id_map.csv":
            continue
        fields, rows, newline = read_table(path)
        columns = [c for c in id_columns if c in fields]
        if not columns and "source" not in fields:
            continue
        changed = 0
        for row in rows:
            for column in columns:
                value = row[column]
                if value in by_old:
                    row[column] = by_old[value]["new_id"]
                    changed += 1
                elif value not in ("", "NaN") and not NAME.match(value):
                    raise ValueError(f"{path.name}: {column}={value} has no mapping")
            if row.get("source") == "uqam_ibutton":
                row["source"] = IBUTTON_TRANSECTS[row["site_id"][:2]]
                changed += 1
        if changed:
            write_table(path, fields, rows, newline)
            print(f"{path.name}: updated {changed} values")

    for campaign, source in (("bj", "james_bay"), ("fm", "montmorency"), ("kj", "kuujjuarapik")):
        for kind in ("sensors", "context"):
            old = metadata_dir / f"uqam_ibutton_{campaign}_{kind}.csv"
            if move(old, metadata_dir / f"{source}_{kind}.csv"):
                print(f"{old.name} -> {source}_{kind}.csv")

    shutil.copy2(map_path, metadata_dir / "sensor_id_map.csv")
    repo = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(repo / "scripts" / "build_catalog.py"), str(metadata_dir),
                    "--output", str(metadata_dir / "catalog.csv"),
                    "--manifest", str(metadata_dir / "catalog_manifest.csv"), "--apply"],
                   check=True, env={**os.environ, "PYTHONPATH": str(repo / "src")})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true", help="rename files and rewrite metadata using --map")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d"))
    args = parser.parse_args()
    if args.apply:
        apply(args.data_root, args.map, args.stamp)
        return
    if args.report is None:
        parser.error("--report is required for a dry run")
    raise SystemExit(plan(args.data_root, args.map, args.report))


if __name__ == "__main__":
    main()
