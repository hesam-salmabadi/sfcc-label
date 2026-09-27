"""Tests for the published Trail Valley Creek profile importer."""

import csv

import pytest

from sfcc_label.io import load_metadata, read_observations
from sfcc_label.tvc_boike import import_tvc_boike


HEADER = "\t".join((
    "Date/Time (UTC)",
    *(f"T soil [°C] (at {depth}cm depth)" for depth in (2, 5, 10, 20)),
    *(f"Soil moisture vol (at {depth}cm depth)" for depth in (2, 5, 10, 20)),
    *("Soil moisture vol (vertical down, 0-15cm depth)" for _ in range(3)),
))


def _source(tmp_path, *, utc=True):
    source = tmp_path / "source"
    source.mkdir()
    file = source / "Boike-etal_2020_TVCsoil2018.tab"
    lines = [
        "/* DATA DESCRIPTION:",
        "Parameter(s): DATE/TIME (Date/Time) * COMMENT: UTC" if utc else
        "Parameter(s): DATE/TIME (Date/Time) * COMMENT: local",
        "*/", HEADER,
        "2018-01-01T00:00\t-6\t-5\t-4\t-3\t0.1\t0.2\t0.3\t0.4\t0.5\t\t0.7",
        "2018-01-01T01:00\t-7\t-6\t-5\t-4\t0.11\t0.21\t0.31\t0.41\t0.51\t0.61\t0.71",
    ]
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return source


def test_import_pairs_horizontal_and_keeps_vertical_separate(tmp_path):
    source = _source(tmp_path)
    observations = tmp_path / "observations"
    sensors_file = tmp_path / "sensors.csv"
    context_file = tmp_path / "context.csv"
    contexts = import_tvc_boike(source, observations, sensors_file, context_file)
    assert len(contexts) == 7
    sensors = load_metadata(sensors_file)
    assert len(sensors) == 7
    assert sensors["tvcb_tvc_005cm_s1"].depth_cm == 5
    assert sensors["tvcb_tvc_000-015cm_hummock"].depth_from_cm == 0
    assert sensors["tvcb_tvc_000-015cm_hummock"].depth_to_cm == 15
    paired = read_observations(observations / "tvcb_tvc_005cm_s1.csv")
    assert [(row.soil_temperature_c, row.soil_moisture_m3_m3, row.raw_value)
            for row in paired] == [(-5, 0.2, None), (-6, 0.21, None)]
    vertical = read_observations(observations / "tvcb_tvc_000-015cm_midway.csv")
    assert len(vertical) == 1
    assert vertical[0].soil_temperature_c is None
    assert vertical[0].soil_moisture_m3_m3 == 0.61
    assert vertical[0].timestamp_utc.isoformat() == "2018-01-01T01:00:00+00:00"
    with context_file.open() as stream:
        context = {row["sensor_id"]: row for row in csv.DictReader(stream)}
    assert context["tvcb_tvc_005cm_s1"]["temperature_hours"] == "2"
    assert context["tvcb_tvc_005cm_s1"]["moisture_hours"] == "2"


def test_refuses_unverified_time_basis(tmp_path):
    source = _source(tmp_path, utc=False)
    with pytest.raises(ValueError, match="time basis"):
        import_tvc_boike(source, tmp_path / "observations",
                         tmp_path / "sensors.csv", tmp_path / "context.csv")
