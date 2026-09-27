import csv
import math
from datetime import date, timedelta

from sfcc_label.time_qc import (DayBuilder, Site, _make_profile,
                                benchmark_standardized_solar, load_level0_profiles,
                                read_local_sites, screen_neighbors, screen_site_years,
                                screen_solar)


def _days(peak_hour, count=35):
    result = {}
    for index in range(count):
        builder = DayBuilder()
        for hour in range(24):
            builder.add(hour, 12 + 3 * math.cos(2 * math.pi * (hour + 0.5 - peak_hour) / 24))
        result[date(2021, 7, 1) + timedelta(days=index)] = _make_profile(builder)
    return result


def test_shallow_solar_and_neighbors_agree_on_obvious_seven_hour_offset():
    sites = {
        "A": Site("A", 50, 0, 5, 5, 5, "test", "forest"),
        "B": Site("B", 50, 0.2, 5, 5, 5, "test", "forest"),
        "C": Site("C", 50.1, 0, 5, 5, 5, "test", "forest"),
    }
    profiles = {("A", 2021): _days(11), ("B", 2021): _days(18),
                ("C", 2021): _days(18)}
    solar = screen_solar(sites["A"], profiles[("A", 2021)])
    neighbor = screen_neighbors(sites["A"], 2021, sites, profiles)
    assert solar["status"] == "suspect_offset"
    assert abs(solar["shift"] - 7) < 0.5
    assert neighbor["status"] == "suspect_offset"
    assert neighbor["shift"] == 7
    report = screen_site_years(sites, profiles, {(name, 2021): {} for name in sites})
    assert next(row for row in report if row["site_id"] == "A")["timestamp_status"] == "suspect_offset"


def test_deeper_unknown_and_broad_support_are_not_solar_tested():
    days = _days(11)
    deep = Site("deep", 50, 0, 10, 10, 10, "test")
    unknown = Site("unknown", 50, 0, None, None, None, "test")
    broad = Site("CP01", 50, 0, 5, 0, 10, "user")
    assert deep.depth_band == "7-<13"
    assert screen_solar(deep, days)["status"] == "not_applicable"
    assert screen_solar(unknown, days)["status"] == "not_applicable"
    assert screen_solar(broad, days)["reason"] == "broad_depth_support"


def test_cp_midpoint_and_level0_utc_input_are_preserved(tmp_path):
    metadata = tmp_path / "metadata.csv"
    with metadata.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("Site ID", "Coordinates_Lat", "Coordinates_Lon", "Sensor Depth (cm)"))
        writer.writerow(("CP01", 47, -83, 10))
    site = read_local_sites(metadata)["CP01"]
    assert (site.depth_cm, site.depth_from_cm, site.depth_to_cm) == (5, 0, 10)
    source = tmp_path / "level0"
    source.mkdir()
    with (source / "CP.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("datetime", "site_id", "soil_temp"))
        for hour in range(24):
            writer.writerow((f"2021-07-01 {hour:02d}:30:00", "CP01",
                             10 + 3 * math.cos(2 * math.pi * (hour - 15) / 24)))
    profiles, counts = load_level0_profiles(source, {"CP01": site})
    assert counts[("CP01", 2021)]["rows"] == 24
    assert len(profiles[("CP01", 2021)]) == 1


def test_sparse_site_is_inconclusive_not_a_time_error():
    site = Site("A", 50, 0, 5, 5, 5, "test")
    result = screen_solar(site, _days(11, count=3))
    assert result["status"] == "inconclusive"


def test_shared_network_shift_still_gets_a_solar_review():
    sites = {name: Site(name, 50, index * 0.1, 5, 5, 5, "test")
             for index, name in enumerate(("A", "B", "C"))}
    profiles = {(name, 2021): _days(11) for name in sites}
    assert screen_neighbors(sites["A"], 2021, sites, profiles)["status"] == "no_obvious_offset"
    report = screen_site_years(sites, profiles, {(name, 2021): {} for name in sites})
    assert all(row["timestamp_status"] == "review" for row in report)


def test_invalid_source_datetime_is_not_silently_dropped(tmp_path):
    source = tmp_path / "level0"
    source.mkdir()
    (source / "A.csv").write_text("datetime,site_id,soil_temp\nnot-a-date,A,10\n")
    site = Site("A", 50, 0, 5, 5, 5, "test")
    try:
        load_level0_profiles(source, {"A": site})
    except ValueError as exc:
        assert "invalid datetime" in str(exc)
    else:
        assert False, "invalid datetime should fail loudly"


def test_standardized_utc_benchmark_preserves_depth_and_inconclusive(tmp_path):
    metadata = tmp_path / "sensors.csv"
    with metadata.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("sensor_id", "source", "site_id", "network", "latitude",
                         "longitude", "depth_cm", "depth_from_cm", "depth_to_cm"))
        writer.writerow(("shallow", "test", "site", "network", 50, 0, 5, 5, 5))
        writer.writerow(("broad", "test", "site", "network", 50, 0, 5, 0, 10))
    observations = tmp_path / "observations"
    observations.mkdir()
    with (observations / "shallow.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("timestamp_utc", "soil_temperature_c", "soil_moisture_m3_m3", "raw_value"))
        for index in range(25):
            day = date(2021, 7, 1) + timedelta(days=index)
            for hour in range(24):
                temperature = 12 + 3 * math.cos(2 * math.pi * (hour + 0.5 - 18) / 24)
                writer.writerow((f"{day}T{hour:02d}:00:00Z", temperature, "", ""))
    output = tmp_path / "benchmark.csv"
    summary = benchmark_standardized_solar(metadata, observations, output)
    assert summary == {"no_obvious_offset": 1}
    with output.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["sensor_id"] == "shallow"
    assert rows[0]["usable_days"] == "25"
