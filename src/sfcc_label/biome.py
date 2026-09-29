"""Terrestrial biome and ecoregion of every sensor from RESOLVE Ecoregions 2017.

RESOLVE Ecoregions 2017 (Dinerstein et al., 2017, BioScience 67, 534-545; CC BY 4.0) divides land into 846
ecoregions grouped into 14 biomes (e.g. Boreal Forests/Taiga, Tundra, Temperate Broadleaf & Mixed Forests).
ESA CCI land cover describes vegetation structure but not climate, so it cannot separate boreal from temperate
forest; the biome adds that. A sensor takes the ecoregion whose polygon contains it; a sensor just outside every
polygon (coast, lake shore) takes the nearest one within MAX_SNAP_M, and the distance is recorded.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

BIOME_COLUMNS = ("sensor_id", "source", "site_id", "latitude", "longitude", "biome_num", "biome", "ecoregion",
                 "realm", "snap_distance_m")
MAX_SNAP_M = 5000.0
_EARTH_RADIUS_M = 6371008.8


def _approx_distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance between two lon/lat points (m)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, a)))


def assign_ecoregions(points: list[tuple[float, float]], geometries, attributes: list[dict],
                      max_snap_m: float = MAX_SNAP_M) -> list[tuple[dict | None, float]]:
    """(attributes, snap distance in m) for each (lon, lat) point; (None, nan) when nothing is within reach.

    geometries: shapely geometries in lon/lat; attributes: one dict per geometry."""
    import numpy as np
    import shapely
    import shapely.ops
    from shapely import STRtree

    tree = STRtree(geometries)
    pts = shapely.points(np.asarray(points, dtype=float))
    inside_pt, inside_geom = tree.query(pts, predicate="intersects")
    found: dict[int, int] = {}
    for p, g in zip(inside_pt, inside_geom):
        found.setdefault(int(p), int(g))
    out: list[tuple[dict | None, float]] = []
    for i, (lon, lat) in enumerate(points):
        if i in found:
            out.append((attributes[found[i]], 0.0))
            continue
        # nearest polygon in degrees, then its true distance
        g = int(tree.nearest(pts[i]))
        near = shapely.ops.nearest_points(geometries[g], pts[i])[0]
        dist = _approx_distance_m(lon, lat, near.x, near.y)
        out.append((attributes[g], dist) if dist <= max_snap_m else (None, float("nan")))
    return out


def sensor_biomes(catalog: str | Path, shapefile: str | Path, output: str | Path) -> int:
    """Write one row per sensor with its RESOLVE biome and ecoregion; returns the number of rows."""
    from pyogrio.raw import read as read_vector
    import shapely

    _, _, wkb, fields = read_vector(shapefile, columns=["ECO_NAME", "BIOME_NUM", "BIOME_NAME", "REALM"])
    names = ("ECO_NAME", "BIOME_NUM", "BIOME_NAME", "REALM")
    geometries = shapely.from_wkb(wkb)
    attributes = [dict(zip(names, values)) for values in zip(*fields)]
    with Path(catalog).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    locations = sorted({(float(r["longitude"]), float(r["latitude"])) for r in rows})
    assigned = dict(zip(locations, assign_ecoregions(locations, geometries, attributes)))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=BIOME_COLUMNS)
        writer.writeheader()
        for r in rows:
            attrs, dist = assigned[(float(r["longitude"]), float(r["latitude"]))]
            writer.writerow({
                "sensor_id": r["sensor_id"], "source": r["source"], "site_id": r["site_id"],
                "latitude": r["latitude"], "longitude": r["longitude"],
                "biome_num": int(attrs["BIOME_NUM"]) if attrs else "NaN",
                "biome": attrs["BIOME_NAME"] if attrs else "NaN",
                "ecoregion": attrs["ECO_NAME"] if attrs else "NaN",
                "realm": attrs["REALM"] if attrs else "NaN",
                "snap_distance_m": "NaN" if math.isnan(dist) else format(dist, ".0f"),
            })
    return len(rows)
