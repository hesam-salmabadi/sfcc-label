"""Conservative, read-only timestamp screening for soil-temperature data.

This is an anomaly screen, not a timezone converter. A reported shift must be
reviewed against source records before any timestamps are changed.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from statistics import median


MISSING = {"", "9999", "-9999", "nan", "NaN"}
MONTHS = {6, 7, 8, 9, 10}
REPORT_COLUMNS = (
    "site_id", "year", "latitude", "longitude", "depth_cm", "depth_from_cm",
    "depth_to_cm", "depth_band", "depth_source", "usable_days", "solar_status",
    "solar_peak_hour", "solar_flag_fraction", "solar_suggested_shift_h",
    "neighbor_status", "neighbors_checked", "neighbors_supporting",
    "neighbor_suggested_shift_h", "timestamp_status", "reason",
)


@dataclass(frozen=True)
class Site:
    site_id: str
    latitude: float
    longitude: float
    depth_cm: float | None
    depth_from_cm: float | None
    depth_to_cm: float | None
    depth_source: str
    biome: str = ""

    @property
    def depth_band(self) -> str:
        depth = self.depth_cm
        if depth is None:
            return "unknown"
        if depth < 0:
            return "unknown"
        if depth < 2:
            return "0-<2"
        if depth < 7:
            return "2-<7"
        if depth < 13:
            return "7-<13"
        lower = 13 + 5 * int((depth - 13) // 5)
        return f"{lower}-<{lower + 5}"

    @property
    def broad_support(self) -> bool:
        return (self.depth_from_cm is not None and self.depth_to_cm is not None
                and self.depth_to_cm - self.depth_from_cm > 3)

    @property
    def solar_eligible(self) -> bool:
        return (self.depth_cm is not None and self.depth_cm < 7
                and self.depth_to_cm is not None and self.depth_to_cm <= 7)


@dataclass
class DayBuilder:
    sums: list[float] = field(default_factory=lambda: [0.0] * 24)
    counts: list[int] = field(default_factory=lambda: [0] * 24)

    def add(self, hour: int, value: float) -> None:
        self.sums[hour] += value
        self.counts[hour] += 1


@dataclass(frozen=True)
class DailyProfile:
    phase_utc_h: float
    amplitude_c: float
    anomalies: tuple[float | None, ...]


def _number(value: str | None) -> float | None:
    if value is None or value.strip() in MISSING:
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def read_local_sites(metadata_path: str | Path, biome_path: str | Path | None = None) -> dict[str, Site]:
    """Read the supplied local metadata and the user-confirmed CP probe geometry."""
    biomes = {}
    if biome_path is not None:
        with Path(biome_path).open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                biomes[row["ID"]] = row.get("biome_2L", "") or ""
    sites = {}
    with Path(metadata_path).open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            site_id = row["Site ID"].strip()
            if site_id in sites:
                raise ValueError(f"duplicate site metadata: {site_id}")
            lat = _number(row["Coordinates_Lat"])
            lon = _number(row["Coordinates_Lon"])
            if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError(f"invalid coordinates for {site_id}")
            reported = _number(row.get("Sensor Depth (cm)"))
            if site_id in {"CP01", "CP02", "CP03", "CP04"}:
                if reported != 10:
                    raise ValueError(f"expected reported 10 cm probe length for {site_id}")
                depth, depth_from, depth_to = 5.0, 0.0, 10.0
                source = "user-confirmed 0-10 cm support; 5 cm midpoint"
            else:
                depth = depth_from = depth_to = reported
                source = "supplied metadata" if reported is not None else "unknown"
            sites[site_id] = Site(site_id, lat, lon, depth, depth_from, depth_to,
                                  source, biomes.get(site_id, ""))
    return sites


def _make_profile(day: DayBuilder, minimum_hours: int = 18,
                  minimum_amplitude_c: float = 0.5) -> DailyProfile | None:
    values = [day.sums[h] / day.counts[h] if day.counts[h] else None for h in range(24)]
    present = [(h, value) for h, value in enumerate(values) if value is not None]
    if len(present) < minimum_hours:
        return None
    mean = sum(value for _, value in present) / len(present)
    if mean <= 2:  # avoid frozen and zero-curtain days
        return None
    centered = [(h, value - mean) for h, value in present]
    variance = sum(value * value for _, value in centered) / len(centered)
    if variance <= 0:
        return None
    cosine = sum(value * math.cos(2 * math.pi * (h + 0.5) / 24)
                 for h, value in centered)
    sine = sum(value * math.sin(2 * math.pi * (h + 0.5) / 24)
               for h, value in centered)
    amplitude = 2 * math.hypot(cosine, sine) / len(centered)
    if amplitude < minimum_amplitude_c:
        return None
    phase = (math.atan2(sine, cosine) * 12 / math.pi) % 24
    scale = math.sqrt(variance)
    anomalies = tuple((value - mean) / scale if value is not None else None
                      for value in values)
    return DailyProfile(phase, amplitude, anomalies)


def load_level0_profiles(input_dir: str | Path, sites: dict[str, Site],
                         minimum_hours: int = 18,
                         minimum_amplitude_c: float = 0.5) -> tuple[dict, dict]:
    """Stream network CSVs into informative daily profiles and yearly row counts.

    The source's naive timestamps are interpreted as *declared* UTC, not
    converted. Subhourly readings are grouped into UTC hours for this screen.
    """
    profiles: dict[tuple[str, int], dict[date, DailyProfile]] = defaultdict(dict)
    counts: dict[tuple[str, int], dict[str, int]] = defaultdict(
        lambda: {"rows": 0, "valid_temperature": 0})
    files = sorted(Path(input_dir).glob("*.csv"))
    if not files:
        raise ValueError("no level-0 CSV files found")
    for path in files:
        builders: dict[tuple[str, int, date], DayBuilder] = {}
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not {"datetime", "site_id", "soil_temp"}.issubset(reader.fieldnames or ()):
                raise ValueError(f"missing required columns in {path.name}")
            for row in reader:
                site_id = row["site_id"].strip()
                if site_id not in sites:
                    raise ValueError(f"missing metadata for {site_id} in {path.name}")
                try:
                    stamp = datetime.fromisoformat(row["datetime"].strip())
                except ValueError as exc:
                    raise ValueError(f"invalid datetime in {path.name} line {reader.line_num}") from exc
                if stamp.tzinfo is not None:
                    raise ValueError(f"expected naive, declared-UTC timestamps in {path.name}")
                key = (site_id, stamp.year)
                counts[key]["rows"] += 1
                value = _number(row.get("soil_temp"))
                if value is None:
                    continue
                counts[key]["valid_temperature"] += 1
                if stamp.month not in MONTHS:
                    continue
                day_key = (site_id, stamp.year, stamp.date())
                builders.setdefault(day_key, DayBuilder()).add(stamp.hour, value)
        for (site_id, year, day), builder in builders.items():
            profile = _make_profile(builder, minimum_hours, minimum_amplitude_c)
            if profile is not None:
                profiles[(site_id, year)][day] = profile
    return dict(profiles), dict(counts)


def _equation_of_time_hours(day: date) -> float:
    angle = 2 * math.pi * (day.timetuple().tm_yday - 1) / 365
    minutes = 229.18 * (0.000075 + 0.001868 * math.cos(angle)
                        - 0.032077 * math.sin(angle) - 0.014615 * math.cos(2 * angle)
                        - 0.040849 * math.sin(2 * angle))
    return minutes / 60


def _signed_hours(value: float) -> float:
    return (value + 12) % 24 - 12


def _circular_mean(hours: list[float]) -> float:
    sine = sum(math.sin(math.pi * value / 12) for value in hours)
    cosine = sum(math.cos(math.pi * value / 12) for value in hours)
    return (math.atan2(sine, cosine) * 12 / math.pi) % 24


def screen_solar(site: Site, days: dict[date, DailyProfile],
                 minimum_days: int = 20) -> dict:
    if not site.solar_eligible:
        reason = "broad_depth_support" if site.broad_support and site.depth_cm is not None and site.depth_cm < 7 else "depth_not_0_to_7_cm"
        return {"status": "not_applicable", "days": len(days), "reason": reason,
                "peak": None, "fraction": None, "shift": None}
    if len(days) < minimum_days:
        return {"status": "inconclusive", "days": len(days), "reason": "too_few_usable_days",
                "peak": None, "fraction": None, "shift": None}
    center = 16.0 if site.depth_cm < 2 else 18.0
    phases = [(profile.phase_utc_h + site.longitude / 15
               + _equation_of_time_hours(day)) % 24 for day, profile in days.items()]
    deltas = [_signed_hours(phase - center) for phase in phases]
    positive = sum(delta >= 5 for delta in deltas) / len(deltas)
    negative = sum(delta <= -5 for delta in deltas) / len(deltas)
    fraction = max(positive, negative)
    shift = -median(deltas)
    suspect = fraction >= 0.7 and abs(shift) >= 5
    return {"status": "suspect_offset" if suspect else "no_obvious_offset",
            "days": len(days), "reason": "persistent_solar_phase_shift" if suspect else "",
            "peak": _circular_mean(phases), "fraction": fraction,
            "shift": shift if suspect else None}


def _distance_km(a: Site, b: Site) -> float:
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(b.longitude - a.longitude)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(value)))


def _comparable(a: Site, b: Site) -> bool:
    if a.depth_band == "unknown" or a.depth_band != b.depth_band:
        return False
    if a.broad_support != b.broad_support:
        return False
    if a.broad_support and abs((a.depth_to_cm or 0) - (b.depth_to_cm or 0)) > 3:
        return False
    return not (a.biome and b.biome and a.biome != b.biome)


def _pair_alignment(a: dict[date, DailyProfile], b: dict[date, DailyProfile],
                    minimum_days: int) -> dict | None:
    common = sorted(a.keys() & b.keys())
    if len(common) < minimum_days:
        return None
    scores = []
    for lag in range(-12, 13):
        products = 0.0
        n = 0
        for day in common:
            target = a[day].anomalies
            reference = b[day].anomalies
            for hour in range(24):
                x = target[(hour - lag) % 24]
                y = reference[hour]
                if x is not None and y is not None:
                    products += x * y
                    n += 1
        scores.append(products / n if n else float("-inf"))
    best_index = max(range(len(scores)), key=lambda index: scores[index])
    best_lag = best_index - 12
    best_score = scores[best_index]
    zero_score = scores[12]
    return {"days": len(common), "lag": best_lag, "best": best_score,
            "zero": zero_score, "improvement": best_score - zero_score,
            "strong": abs(best_lag) >= 3 and best_score >= 0.5
            and best_score - zero_score >= 0.15}


def screen_neighbors(site: Site, year: int, sites: dict[str, Site], profiles: dict,
                     radius_km: float = 100, minimum_days: int = 20,
                     minimum_neighbors: int = 2, max_neighbors: int = 8) -> dict:
    if site.depth_band == "unknown":
        return {"status": "not_applicable", "checked": 0, "supporting": 0,
                "shift": None, "reason": "unknown_depth"}
    own = profiles.get((site.site_id, year), {})
    if len(own) < minimum_days:
        return {"status": "inconclusive", "checked": 0, "supporting": 0,
                "shift": None, "reason": "too_few_usable_days"}
    candidates = sorted(((_distance_km(site, other), other.site_id, other) for other in sites.values()
                        if other.site_id != site.site_id and _comparable(site, other)
                        and (other.site_id, year) in profiles), key=lambda item: (item[0], item[1]))
    candidates = [(distance, other) for distance, _, other in candidates if distance <= radius_km]
    alignments = []
    for _, other in candidates:
        result = _pair_alignment(own, profiles[(other.site_id, year)], minimum_days)
        if result is not None:
            alignments.append((other.site_id, result))
            if len(alignments) >= max_neighbors:
                break
    strong = [(other_id, result) for other_id, result in alignments if result["strong"]]
    if len(strong) >= minimum_neighbors:
        shifts = [result["lag"] for _, result in strong]
        middle = median(shifts)
        supporting = sum(abs(shift - middle) <= 1 for shift in shifts)
        if supporting >= minimum_neighbors:
            return {"status": "suspect_offset", "checked": len(alignments),
                    "supporting": supporting, "shift": middle,
                    "reason": "neighbor_lag_consensus"}
    return {"status": "no_obvious_offset" if len(alignments) >= minimum_neighbors else "inconclusive",
            "checked": len(alignments), "supporting": 0, "shift": None,
            "reason": "" if len(alignments) >= minimum_neighbors else "too_few_comparable_neighbors"}


def screen_site_years(sites: dict[str, Site], profiles: dict, counts: dict,
                      radius_km: float = 100, minimum_days: int = 20) -> list[dict]:
    rows = []
    for site_id, year in sorted(counts):
        site = sites[site_id]
        days = profiles.get((site_id, year), {})
        solar = screen_solar(site, days, minimum_days)
        neighbor = screen_neighbors(site, year, sites, profiles, radius_km, minimum_days)
        solar_bad = solar["status"] == "suspect_offset"
        neighbor_bad = neighbor["status"] == "suspect_offset"
        if solar_bad and neighbor_bad:
            if abs((solar["shift"] or 0) - (neighbor["shift"] or 0)) <= 2:
                status, reason = "suspect_offset", "solar_and_neighbor_agree"
            else:
                status, reason = "review", "solar_neighbor_disagree"
        elif solar_bad or neighbor_bad:
            status, reason = "review", "single_test_suspects_offset"
        elif solar["status"] == "no_obvious_offset" or neighbor["status"] == "no_obvious_offset":
            status, reason = "no_obvious_offset", ""
        else:
            status, reason = "inconclusive", "insufficient_timing_evidence"
        rows.append({
            "site_id": site_id, "year": year, "latitude": site.latitude,
            "longitude": site.longitude, "depth_cm": site.depth_cm,
            "depth_from_cm": site.depth_from_cm, "depth_to_cm": site.depth_to_cm,
            "depth_band": site.depth_band, "depth_source": site.depth_source,
            "usable_days": solar["days"], "solar_status": solar["status"],
            "solar_peak_hour": _display(solar["peak"]),
            "solar_flag_fraction": _display(solar["fraction"]),
            "solar_suggested_shift_h": _display(solar["shift"]),
            "neighbor_status": neighbor["status"],
            "neighbors_checked": neighbor["checked"],
            "neighbors_supporting": neighbor["supporting"],
            "neighbor_suggested_shift_h": _display(neighbor["shift"]),
            "timestamp_status": status, "reason": reason or solar["reason"] or neighbor["reason"],
        })
    return rows


def _display(value: float | None) -> str:
    return "" if value is None else f"{value:.3f}"


def write_time_report(path: str | Path, rows: list[dict]) -> None:
    output = Path(path)
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


STANDARDIZED_SOLAR_COLUMNS = (
    "source", "sensor_id", "site_id", "network", "year", "depth_cm",
    "depth_from_cm", "depth_to_cm", "depth_band", "latitude", "longitude",
    "usable_days", "solar_status", "solar_peak_hour", "solar_flag_fraction",
    "solar_suggested_shift_h", "reason",
)


def read_standardized_shallow_sites(metadata_path: str | Path) -> dict[str, tuple[Site, dict]]:
    """Read every 0–7 cm stream whose documented support remains within 7 cm."""
    result = {}
    with Path(metadata_path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            sensor_id = row["sensor_id"]
            depth = _number(row["depth_cm"])
            depth_from = _number(row["depth_from_cm"])
            depth_to = _number(row["depth_to_cm"])
            if depth is None or depth_from is None or depth_to is None:
                continue
            if not (0 <= depth < 7 and 0 <= depth_from <= depth_to <= 7):
                continue
            site = Site(sensor_id, float(row["latitude"]), float(row["longitude"]),
                        depth, depth_from, depth_to, "source metadata")
            if sensor_id in result:
                raise ValueError(f"duplicate sensor ID: {sensor_id}")
            result[sensor_id] = (site, row)
    return result


def _standardized_sensor_profiles(path: Path,
                                  minimum_hours: int = 18,
                                  minimum_amplitude_c: float = 0.5) -> dict[int, dict[date, DailyProfile]]:
    """Stream one standardized sensor file; keep only its summer/fall daily profiles."""
    builders: dict[tuple[int, date], DayBuilder] = {}
    years: set[int] = set()
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.reader(stream)
        header = next(reader, None)
        if header != ["timestamp_utc", "soil_temperature_c", "soil_moisture_m3_m3", "raw_value"]:
            raise ValueError(f"unexpected standardized schema in {path.name}")
        for line_number, row in enumerate(reader, 2):
            if len(row) != 4 or len(row[0]) != 20 or row[0][10] != "T" or row[0][-1] != "Z":
                raise ValueError(f"invalid standardized row in {path.name} line {line_number}")
            stamp = row[0]
            try:
                year = int(stamp[:4])
                month = int(stamp[5:7])
            except ValueError as exc:
                raise ValueError(f"invalid timestamp in {path.name} line {line_number}") from exc
            years.add(year)
            if month not in MONTHS:
                continue
            value = _number(row[1])
            if value is None:
                continue
            try:
                day = date.fromisoformat(stamp[:10])
                hour = int(stamp[11:13])
                if not 0 <= hour <= 23:
                    raise ValueError("hour out of range")
            except ValueError as exc:
                raise ValueError(f"invalid timestamp in {path.name} line {line_number}") from exc
            builders.setdefault((year, day), DayBuilder()).add(hour, value)
    profiles: dict[int, dict[date, DailyProfile]] = {year: {} for year in years}
    for (year, day), builder in builders.items():
        profile = _make_profile(builder, minimum_hours, minimum_amplitude_c)
        if profile is not None:
            profiles[year][day] = profile
    return profiles


def benchmark_standardized_solar(metadata_path: str | Path, observations_dir: str | Path,
                                 output_path: str | Path, minimum_days: int = 20,
                                 max_sensors: int | None = None) -> dict[str, int]:
    """Apply the unchanged shallow solar screen to a known-UTC collection.

    This deliberately benchmarks the solar component alone. A neighbor agreement
    rule could hide a systematic error shared across a network.
    """
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(output)
    sites = read_standardized_shallow_sites(metadata_path)
    selected = sorted(sites.items())
    if max_sensors is not None:
        selected = selected[:max_sensors]
    observation_root = Path(observations_dir)
    missing = [sensor_id for sensor_id, _ in selected
               if not (observation_root / f"{sensor_id}.csv").is_file()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} standardized sensor files missing; first: {missing[0]}")
    summary: dict[str, int] = defaultdict(int)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=STANDARDIZED_SOLAR_COLUMNS)
        writer.writeheader()
        for number, (sensor_id, (site, metadata)) in enumerate(selected, 1):
            profiles = _standardized_sensor_profiles(observation_root / f"{sensor_id}.csv")
            for year, days in sorted(profiles.items()):
                solar = screen_solar(site, days, minimum_days)
                summary[solar["status"]] += 1
                writer.writerow({
                    "source": metadata["source"], "sensor_id": sensor_id,
                    "site_id": metadata["site_id"], "network": metadata["network"],
                    "year": year, "depth_cm": site.depth_cm,
                    "depth_from_cm": site.depth_from_cm, "depth_to_cm": site.depth_to_cm,
                    "depth_band": site.depth_band, "latitude": site.latitude,
                    "longitude": site.longitude, "usable_days": solar["days"],
                    "solar_status": solar["status"],
                    "solar_peak_hour": _display(solar["peak"]),
                    "solar_flag_fraction": _display(solar["fraction"]),
                    "solar_suggested_shift_h": _display(solar["shift"]),
                    "reason": solar["reason"],
                })
            if number % 100 == 0 or number == len(selected):
                print(f"Solar benchmark: {number}/{len(selected)} sensors; "
                      f"{dict(summary)} site-years", flush=True)
                stream.flush()
    return dict(summary)
