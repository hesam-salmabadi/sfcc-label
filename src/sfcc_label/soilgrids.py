"""Sample SoilGrids 2.0 (250 m) at sensor locations and match layers to sensor depth.

Values are read straight from ISRIC's cloud-optimized rasters over HTTP, so only
the pixels under the sensors are downloaded. Each raster is cached as one CSV,
which makes a long fetch resumable.

Depth matching is one SoilGrids layer per sensor: round ``depth_cm`` to the
nearest whole cm, then take the layer whose range includes it with the bottom
edge inclusive (0-5 holds 0..5, 5-15 holds 6..15, ...). Deeper than 200 cm uses
100-200. AmeriFlux sensors without a depth take the layer most often seen for
their vertical level (``v1``, ``v2``, ...) among AmeriFlux sensors whose depth
is known; sensors without a level take 0-5. Both are marked as assumed.
"""

from __future__ import annotations

import csv
import math
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

BASE_URL = "https://files.isric.org/soilgrids/latest/data"
VERSION = "SoilGrids 2.0 (ISRIC, 2020)"
LAYERS = ((0, 5), (5, 15), (15, 30), (30, 60), (60, 100), (100, 200))
# name -> (unit after conversion, divisor from SoilGrids mapped integer units)
PROPERTIES = {
    "clay": ("%", 10), "sand": ("%", 10), "silt": ("%", 10),
    "soc": ("g/kg", 10), "bdod": ("g/cm3", 100), "cfvo": ("%", 10),
}
WRB_CLASSES = (
    "Acrisols", "Albeluvisols", "Alisols", "Andosols", "Arenosols", "Calcisols", "Cambisols",
    "Chernozems", "Cryosols", "Durisols", "Ferralsols", "Fluvisols", "Gleysols", "Gypsisols",
    "Histosols", "Kastanozems", "Leptosols", "Lixisols", "Luvisols", "Nitisols", "Phaeozems",
    "Planosols", "Plinthosols", "Podzols", "Regosols", "Solonchaks", "Solonetz", "Stagnosols",
    "Umbrisols", "Vertisols",
)
WRB_PROBABILITIES = ("Cryosols", "Histosols")
SEARCH_PIXELS = 2  # nodata fallback: nearest valid pixel within +/-2 pixels (<= ~700 m)
GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".vrt,.tif,.ovr",
    "GDAL_HTTP_MULTIRANGE": "YES",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MAX_RETRY": "5",
    "GDAL_HTTP_RETRY_DELAY": "3",
    "VSI_CACHE": "TRUE",
}
POINT_COLUMNS = ("latitude", "longitude", "property", "statistic", "top_cm", "bottom_cm",
                 "raw_value", "value", "unit", "pixel_offset_m")
SENSOR_COLUMNS = (
    "sensor_id", "source", "latitude", "longitude", "depth_cm", "depth_basis", "depth_note",
    "soilgrids_top_cm", "soilgrids_bottom_cm",
    "clay_pct", "sand_pct", "silt_pct", "soc_g_kg", "bdod_g_cm3", "cfvo_pct",
    "clay_uncertainty", "sand_uncertainty", "silt_uncertainty", "soc_uncertainty",
    "bdod_uncertainty", "cfvo_uncertainty",
    "texture_class_usda", "wrb_class", "cryosols_probability_pct", "histosols_probability_pct",
    "max_pixel_offset_m", "soilgrids_version", "accessed",
)


def layer_for_depth(depth_cm: float) -> tuple[int, int]:
    rounded = max(0, round(depth_cm))
    for top, bottom in LAYERS:
        if rounded <= bottom:
            return top, bottom
    return LAYERS[-1]


def _missing(text: str | None) -> bool:
    return text in (None, "", "NaN", "nan")


def ameriflux_level(sensor_id: str) -> str | None:
    """Vertical level from the id tag: ``h1v2r1`` -> ``v2``; other tags have none."""
    match = re.fullmatch(r"h\d+v(\d+)r\d+", sensor_id.split("_")[-1])
    return f"v{match.group(1)}" if match else None


def ameriflux_level_layers(rows: list[dict[str, str]]) -> dict[str, tuple[tuple[int, int], int, int]]:
    """Most common layer per level among AmeriFlux sensors with a known depth.

    Returns level -> (layer, sensors in that layer, sensors at that level).
    """
    counts: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        if row["source"] != "ameriflux" or _missing(row["depth_cm"]):
            continue
        level = ameriflux_level(row["sensor_id"])
        if level:
            counts[level][layer_for_depth(float(row["depth_cm"]))] += 1
    result = {}
    for level, counter in counts.items():
        # ties go to the shallower layer
        layer, hits = min(counter.items(), key=lambda item: (-item[1], item[0]))
        result[level] = (layer, hits, sum(counter.values()))
    return result


def assign_layer(row: dict[str, str], level_layers: dict) -> tuple[tuple[int, int], str, str]:
    """Return (layer, depth_basis, depth_note) for one catalog row."""
    if not _missing(row["depth_cm"]):
        depth = float(row["depth_cm"])
        layer = layer_for_depth(depth)
        if round(depth) > LAYERS[-1][1]:
            return layer, "measured_below_soilgrids", f"{depth:g} cm is below 200 cm; 100-200 cm used"
        return layer, "measured", f"{depth:g} cm rounds to {max(0, round(depth))} cm"
    level = ameriflux_level(row["sensor_id"]) if row["source"] == "ameriflux" else None
    if level and level in level_layers:
        layer, hits, total = level_layers[level]
        share = 100 * hits / total
        return (layer, "assumed_from_level",
                f"{level}: {layer[0]}-{layer[1]} cm holds {share:.0f}% of {total} known-depth AmeriFlux {level} sensors")
    return LAYERS[0], "assumed_top", "depth unknown and no vertical level; 0-5 cm assumed"


def usda_texture(sand: float, silt: float, clay: float) -> str:
    total = sand + silt + clay
    if not total:
        return ""
    sand, silt, clay = (100 * value / total for value in (sand, silt, clay))
    if silt + 1.5 * clay < 15:
        return "sand"
    if silt + 2 * clay < 30:
        return "loamy sand"
    if (7 <= clay < 20 and sand > 52) or (clay < 7 and silt < 50):
        return "sandy loam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:
        return "loam"
    if (silt >= 50 and 12 <= clay < 27) or (50 <= silt < 80 and clay < 12):
        return "silt loam"
    if silt >= 80 and clay < 12:
        return "silt"
    if 20 <= clay < 35 and silt < 28 and sand > 45:
        return "sandy clay loam"
    if 27 <= clay < 40 and 20 < sand <= 45:
        return "clay loam"
    if 27 <= clay < 40 and sand <= 20:
        return "silty clay loam"
    if clay >= 35 and sand > 45:
        return "sandy clay"
    if clay >= 40 and silt >= 40:
        return "silty clay"
    return "clay"


def raster_jobs() -> list[dict]:
    jobs = []
    for name, (unit, divisor) in PROPERTIES.items():
        for top, bottom in LAYERS:
            for statistic in ("mean", "uncertainty"):
                jobs.append({
                    "key": f"{name}_{top}-{bottom}cm_{statistic}", "property": name,
                    "statistic": statistic, "top_cm": top, "bottom_cm": bottom,
                    "url": f"{BASE_URL}/{name}/{name}_{top}-{bottom}cm_{statistic}.vrt",
                    # uncertainty is (Q95 - Q05) / Q50 stored x10
                    "unit": unit if statistic == "mean" else "ratio", "divisor": divisor if statistic == "mean" else 10,
                })
    jobs.append({"key": "wrb_most_probable", "property": "wrb", "statistic": "class",
                 "top_cm": "", "bottom_cm": "", "url": f"{BASE_URL}/wrb/MostProbable.vrt",
                 "unit": "class", "divisor": None})
    for group in WRB_PROBABILITIES:
        jobs.append({"key": f"wrb_{group.lower()}_probability", "property": f"wrb_{group.lower()}",
                     "statistic": "probability", "top_cm": "", "bottom_cm": "",
                     "url": f"{BASE_URL}/wrb/{group}.vrt", "unit": "%", "divisor": 1})
    return jobs


def sample_raster(dataset, points: list[tuple[float, float]]) -> list[tuple[int | None, float]]:
    """Pixel value under each (lat, lon); nodata falls back to the nearest valid pixel."""
    import numpy as np
    from rasterio.warp import transform
    from rasterio.windows import Window

    nodata = dataset.nodata
    xs, ys = transform("EPSG:4326", dataset.crs, [p[1] for p in points], [p[0] for p in points])
    results = []
    for x, y, value in zip(xs, ys, dataset.sample(zip(xs, ys), indexes=1)):
        raw = int(value[0])
        if raw != nodata:
            results.append((raw, 0.0))
            continue
        row, col = dataset.index(x, y)
        window = Window(col - SEARCH_PIXELS, row - SEARCH_PIXELS, 2 * SEARCH_PIXELS + 1, 2 * SEARCH_PIXELS + 1)
        block = dataset.read(1, window=window, boundless=True, fill_value=nodata)
        valid = np.argwhere(block != nodata)
        if not len(valid):
            results.append((None, math.nan))
            continue
        offsets = valid - SEARCH_PIXELS
        distances = np.hypot(offsets[:, 0], offsets[:, 1])
        best = int(np.argmin(distances))
        results.append((int(block[tuple(valid[best])]), float(distances[best] * abs(dataset.res[0]))))
    return results


def _convert(job: dict, raw: int | None) -> str:
    if raw is None:
        return "NaN"
    if job["property"] == "wrb":
        return WRB_CLASSES[raw] if 0 <= raw < len(WRB_CLASSES) else "NaN"
    return format(raw / job["divisor"], ".6g")


def fetch_job(job: dict, points: list[tuple[float, float]], cache_dir: Path) -> Path:
    import rasterio

    target = cache_dir / f"{job['key']}.csv"
    if target.exists():
        return target
    with rasterio.Env(**GDAL_ENV), rasterio.open(f"/vsicurl/{job['url']}") as dataset:
        samples = sample_raster(dataset, points)
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(POINT_COLUMNS)
        for (lat, lon), (raw, offset) in zip(points, samples):
            writer.writerow((lat, lon, job["property"], job["statistic"], job["top_cm"], job["bottom_cm"],
                             "NaN" if raw is None else raw, _convert(job, raw), job["unit"],
                             "NaN" if math.isnan(offset) else format(offset, ".0f")))
    temporary.replace(target)
    return target


def catalog_points(rows: list[dict[str, str]]) -> list[tuple[float, float]]:
    points = {(round(float(r["latitude"]), 5), round(float(r["longitude"]), 5)) for r in rows}
    return sorted(points)


def fetch_soilgrids(catalog: str | Path, output: str | Path, cache_dir: str | Path,
                    workers: int = 12, limit: int | None = None, progress=print) -> int:
    """Sample every raster at every catalog location and write the long points table."""
    with Path(catalog).open(newline="", encoding="utf-8-sig") as stream:
        points = catalog_points(list(csv.DictReader(stream)))
    if limit:
        step = max(1, len(points) // limit)
        points = points[::step][:limit]
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    jobs = raster_jobs()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_job, job, points, cache): job for job in jobs}
        for future in as_completed(futures):
            future.result()
            done += 1
            progress(f"[{done}/{len(jobs)}] {futures[future]['key']}")
    output = Path(output)
    temporary = output.with_name(output.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow(POINT_COLUMNS)
        for job in jobs:
            with (cache / f"{job['key']}.csv").open(newline="", encoding="utf-8") as part:
                reader = csv.reader(part)
                next(reader)
                writer.writerows(reader)
    temporary.replace(output)
    return len(points)


def match_sensors(catalog: str | Path, points_file: str | Path, output: str | Path,
                  accessed: str | None = None) -> dict[str, int]:
    """Write one row per sensor with SoilGrids values from its matched layer."""
    with Path(catalog).open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    values: dict[tuple, dict] = defaultdict(dict)
    with Path(points_file).open(newline="", encoding="utf-8") as stream:
        for record in csv.DictReader(stream):
            key = (round(float(record["latitude"]), 5), round(float(record["longitude"]), 5))
            layer = (int(record["top_cm"]), int(record["bottom_cm"])) if record["top_cm"] else None
            values[key][(record["property"], record["statistic"], layer)] = record
    level_layers = ameriflux_level_layers(rows)
    accessed = accessed or date.today().isoformat()
    summary: Counter = Counter()
    output = Path(output)
    temporary = output.with_name(output.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=SENSOR_COLUMNS)
        writer.writeheader()
        for row in rows:
            key = (round(float(row["latitude"]), 5), round(float(row["longitude"]), 5))
            layer, basis, note = assign_layer(row, level_layers)
            site = values.get(key, {})

            def get(prop: str, statistic: str, depth=layer) -> dict | None:
                return site.get((prop, statistic, depth))

            out = {"sensor_id": row["sensor_id"], "source": row["source"],
                   "latitude": row["latitude"], "longitude": row["longitude"],
                   "depth_cm": row["depth_cm"], "depth_basis": basis, "depth_note": note,
                   "soilgrids_top_cm": layer[0], "soilgrids_bottom_cm": layer[1],
                   "soilgrids_version": VERSION, "accessed": accessed}
            offsets = []
            for prop, column in (("clay", "clay_pct"), ("sand", "sand_pct"), ("silt", "silt_pct"),
                                 ("soc", "soc_g_kg"), ("bdod", "bdod_g_cm3"), ("cfvo", "cfvo_pct")):
                mean, spread = get(prop, "mean"), get(prop, "uncertainty")
                out[column] = mean["value"] if mean else "NaN"
                out[f"{prop}_uncertainty"] = spread["value"] if spread else "NaN"
                if mean and not _missing(mean["pixel_offset_m"]):
                    offsets.append(float(mean["pixel_offset_m"]))
            wrb = get("wrb", "class", None)
            out["wrb_class"] = wrb["value"] if wrb else "NaN"
            for group in WRB_PROBABILITIES:
                record = get(f"wrb_{group.lower()}", "probability", None)
                out[f"{group.lower()}_probability_pct"] = record["value"] if record else "NaN"
            texture = [out[c] for c in ("sand_pct", "silt_pct", "clay_pct")]
            out["texture_class_usda"] = ("NaN" if any(_missing(v) for v in texture)
                                         else usda_texture(*map(float, texture)))
            out["max_pixel_offset_m"] = format(max(offsets), ".0f") if offsets else "NaN"
            summary[basis] += 1
            summary["missing_texture"] += out["texture_class_usda"] == "NaN"
            summary["shifted_pixel"] += bool(offsets and max(offsets) > 0)
            writer.writerow(out)
    temporary.replace(output)
    summary["sensors"] = len(rows)
    return dict(summary)
