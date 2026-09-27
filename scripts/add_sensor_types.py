#!/usr/bin/env python3
"""Add documented instrument types to existing sfcc-label metadata CSVs.

The migration is deliberately conservative: an instrument type is filled only
when it is explicit in the importer/source documentation.  Otherwise the
field is left as ``NaN`` and a note records that the model was not identified.
"""
from __future__ import annotations

import argparse
import csv
import io
import shutil
from datetime import datetime, timezone
from pathlib import Path

NEW_COLUMNS = (
    "soil_temperature_sensor_type",
    "soil_moisture_sensor_type",
    "sensor_type_source",
    "sensor_type_note",
)
NA = "NaN"


def classify(row: dict[str, str]) -> dict[str, str]:
    source = row.get("source", "")
    sid = row.get("sensor_id", "")
    raw = row.get("raw_variable", "")
    result = {column: row.get(column, NA) or NA for column in NEW_COLUMNS}
    result["sensor_type_source"] = result["sensor_type_source"] if result["sensor_type_source"] != NA else NA
    if source == "tvc_hydraprobe":
        result.update(soil_temperature_sensor_type="HydraProbe", soil_moisture_sensor_type="HydraProbe",
                      sensor_type_source="TVC Soil Stations metadata workbook",
                      sensor_type_note="HydraProbe; H1/H3 support 5 cm and H2/H4 support 10 cm.")
    elif source == "tvc_boike":
        result["soil_moisture_sensor_type"] = "CS630"
        result["sensor_type_source"] = "PANGAEA Boike et al. 2020 metadata"
        if sid.startswith("tvc_boike_v0to15cm_"):
            result["sensor_type_note"] = "Vertical 0–15 cm moisture-only probe; no paired soil-temperature instrument."
        else:
            result["soil_temperature_sensor_type"] = "PT100"
    elif source in {"james_bay", "montmorency", "kuujjuarapik", "nrcan_ibutton"}:
        result["soil_temperature_sensor_type"] = "iButton"
        result["sensor_type_source"] = ("UQAM publisher workbook metadata" if source != "nrcan_ibutton"
                                         else "NRCan Open File 66 publisher metadata")
    elif source == "chapleau" and raw == "CS616_period":
        result.update(soil_moisture_sensor_type="CS616",
                      sensor_type_source="Chapleau source workbook/soil-profile metadata",
                      sensor_type_note="Raw period output is the CS616 measurement; VWC is separately calibrated.")
    if all(result[c] == NA for c in ("soil_temperature_sensor_type", "soil_moisture_sensor_type")):
        result["sensor_type_note"] = "Instrument model not identified in the imported source metadata."
    return result


def migrate(metadata_dir: Path, apply: bool) -> None:
    files = sorted(path for path in metadata_dir.glob("*_sensors.csv") if not path.name.startswith("._"))
    if not files:
        raise SystemExit(f"No *_sensors.csv files found under {metadata_dir}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = metadata_dir.parent / "archive" / f"metadata_sensor_types_{stamp}"
    changed = 0
    for path in files:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            # A few publisher exports contain degree symbols in cp1252 headers.
            text = raw.decode("cp1252")
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
        for column in NEW_COLUMNS:
            if column not in fieldnames:
                fieldnames.append(column)
        output = []
        filled = 0
        for row in rows:
            values = classify(row)
            if any(values[c] != NA for c in NEW_COLUMNS[:2]):
                filled += 1
            row.update(values)
            output.append(row)
        changed += filled
        print(f"{path.name}: {len(rows)} rows; {filled} rows with documented type")
        if apply:
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup / path.name)
            temporary = path.with_suffix(path.suffix + ".tmp")
            with temporary.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader(); writer.writerows(output)
            temporary.replace(path)
    print(f"Documented sensor types populated for {changed} rows.")
    if apply:
        print(f"Backups written to {backup}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata_dir", type=Path)
    parser.add_argument("--apply", action="store_true", help="rewrite files and create an archive backup")
    args = parser.parse_args()
    migrate(args.metadata_dir, args.apply)
