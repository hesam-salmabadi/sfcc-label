#!/usr/bin/env python3
"""Plot Northern Hemisphere standardized sensors at 2--7 cm."""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


def read_points(metadata_dir: Path):
    points = defaultdict(lambda: {"paired": False, "temperature": False, "sources": set()})
    for path in sorted(metadata_dir.glob("*_sensors.csv")):
        if path.name.startswith("._"):
            continue
        with path.open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                try:
                    depth = float(row["depth_cm"])
                    lat = float(row["latitude"])
                    lon = float(row["longitude"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not (2 <= depth <= 7 and lat >= 0):
                    continue
                key = (round(lat, 5), round(lon, 5))
                point = points[key]
                point["temperature"] = True
                point["sources"].add(row.get("source", "unknown"))
                moisture = row.get("soil_moisture_method", "")
                moisture_type = row.get("soil_moisture_sensor_type", "")
                if moisture not in ("", "NaN") or moisture_type not in ("", "NaN"):
                    point["paired"] = True
    return points


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    points = read_points(args.metadata_dir)
    paired = [(lat, lon) for (lat, lon), p in points.items() if p["paired"]]
    temperature = [(lat, lon) for (lat, lon), p in points.items() if not p["paired"]]

    import cartopy.crs as ccrs
    import cartopy.feature as cfeature

    figure = plt.figure(figsize=(15, 7.5), dpi=180)
    axis = figure.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    axis.set_extent([-180, 180, 0, 90], crs=ccrs.PlateCarree())
    axis.add_feature(cfeature.LAND, facecolor="#f1f3f4", zorder=0)
    axis.add_feature(cfeature.OCEAN, facecolor="#dcecf7", zorder=0)
    axis.add_feature(cfeature.COASTLINE, linewidth=0.45, edgecolor="#66727a", zorder=1)
    axis.add_feature(cfeature.BORDERS, linewidth=0.25, edgecolor="#a0a7ad", zorder=1)
    grid = axis.gridlines(draw_labels=True, linewidth=0.25, color="#9aa5ad", alpha=0.55, linestyle="--")
    grid.top_labels = False
    grid.right_labels = False
    if paired:
        axis.scatter([p[1] for p in paired], [p[0] for p in paired], s=8, c="#1261a0", alpha=0.62,
                     linewidths=0, label=f"Temperature + moisture ({len(paired):,} locations)",
                     transform=ccrs.PlateCarree(), zorder=3)
    if temperature:
        axis.scatter([p[1] for p in temperature], [p[0] for p in temperature], s=9, c="#d97706", alpha=0.65,
                     marker="^", linewidths=0, label=f"Temperature only ({len(temperature):,} locations)",
                     transform=ccrs.PlateCarree(), zorder=3)
    axis.set_title("Standardized Northern Hemisphere top-soil sensors (2–7 cm)", fontsize=14, pad=12)
    axis.legend(loc="lower left", frameon=True, framealpha=0.92, fontsize=9)
    figure.text(0.01, 0.01, "One marker per unique coordinate; metadata depth_cm between 2 and 7 cm; latitude ≥ 0°.\n"
                            "Paired status is based on a documented moisture method or moisture sensor type.", fontsize=8.5)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, bbox_inches="tight")
    print(f"paired_locations={len(paired)} temperature_only_locations={len(temperature)} total={len(points)}")


if __name__ == "__main__":
    main()
