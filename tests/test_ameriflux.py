import csv
import gzip
import zipfile
from datetime import datetime, timezone

from sfcc_label.ameriflux import (AmeriFluxArchive, import_ameriflux_site,
                                  pair_ameriflux, sensor_metadata)
from sfcc_label.io import read_observations


def test_ameriflux_pairs_only_clear_depth_and_averages_half_hours(tmp_path):
    source = tmp_path / "AMF_US-Test_BASE-BADM_1-5.zip"
    member = "AMF_US-Test_BASE_HH_1-5.csv"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(member, "\n".join((
            "# Site: US-Test",
            "TIMESTAMP_START,TIMESTAMP_END,TS_1_1_1,SWC_1_1_1,TS_1_2_1",
            "202001010000,202001010030,-2,20,-9999",
            "202001010030,202001010100,-4,30,5",
            "202001010100,202001010130,-9999,-9999,7",
            "202001010130,202001010200,2,40,9",
        )) + "\n")
    site = AmeriFluxArchive(source, "US-Test", "Test site", 40, -120, -8,
                           (member,), ("TS_1_1_1", "TS_1_2_1"),
                           ("SWC_1_1_1",), False)
    heights = {("US-Test", "TS_1_1_1"): (-0.05,),
               ("US-Test", "SWC_1_1_1"): (-0.05,),
               ("US-Test", "TS_1_2_1"): (-0.1,)}
    sensors = pair_ameriflux(site, heights)
    paired = next(item for item in sensors if item.moisture_column)
    unpaired = next(item for item in sensors if not item.moisture_column)
    assert sensor_metadata(site, paired).depth_cm == 5
    assert unpaired.pairing_method == "temperature_only"
    hours, invalid = import_ameriflux_site(site, sensors, tmp_path / "observations", tmp_path / "flags")
    assert (hours, invalid) == (2, 0)
    output = read_observations(tmp_path / "observations" / f"{paired.sensor_id}.csv")
    assert [item.timestamp_utc for item in output] == [
        datetime(2020, 1, 1, 8, tzinfo=timezone.utc),
        datetime(2020, 1, 1, 9, tzinfo=timezone.utc)]
    assert [item.soil_temperature_c for item in output] == [-3, 2]
    assert [item.soil_moisture_m3_m3 for item in output] == [0.25, 0.4]
    assert [item.soil_moisture_m3_m3 for item in read_observations(
        tmp_path / "observations" / f"{unpaired.sensor_id}.csv")] == [None, None]
    with gzip.open(tmp_path / "flags" / f"{paired.sensor_id}.csv.gz", "rt") as stream:
        flags = list(csv.DictReader(stream))
    assert [float(row["temperature_source_minutes"]) for row in flags] == [60, 30]


def test_ameriflux_depth_ambiguity_is_not_assumed(tmp_path):
    site = AmeriFluxArchive(tmp_path / "unused.zip", "US-Test", "Test", 40, -120, -8,
                           (), ("TS_1_1_1",), ("SWC_1_1_1",), False)
    heights = {("US-Test", "TS_1_1_1"): (-0.05, -0.1),
               ("US-Test", "SWC_1_1_1"): (-0.05,)}
    sensor = pair_ameriflux(site, heights)[0]
    assert sensor.depth_m is None
    assert sensor.moisture_column is None


def test_fractional_utc_offset_splits_source_interval(tmp_path):
    source = tmp_path / "AMF_IN-Test_BASE-BADM_1-5.zip"
    member = "AMF_IN-Test_BASE_HR_1-5.csv"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(member, "TIMESTAMP_START,TIMESTAMP_END,TS_1\n"
                        "202001010000,202001010100,-2\n")
    site = AmeriFluxArchive(source, "IN-Test", "Test", 30, 70, 5.5,
                           (member,), ("TS_1",), (), False)
    sensor = pair_ameriflux(site, {})[0]
    assert import_ameriflux_site(site, [sensor], tmp_path / "obs", tmp_path / "flags") == (2, 0)
    output = read_observations(tmp_path / "obs" / f"{sensor.sensor_id}.csv")
    assert [item.timestamp_utc for item in output] == [
        datetime(2019, 12, 31, 18, tzinfo=timezone.utc),
        datetime(2019, 12, 31, 19, tzinfo=timezone.utc)]
    assert [item.soil_temperature_c for item in output] == [-2, -2]


def test_malformed_source_value_is_missing_and_counted(tmp_path):
    source = tmp_path / "AMF_US-Test_BASE-BADM_1-5.zip"
    member = "AMF_US-Test_BASE_HR_1-5.csv"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(member, "TIMESTAMP_START,TIMESTAMP_END,TS_1\n"
                        "202001010000,202001010100,0.05-999949\n")
    site = AmeriFluxArchive(source, "US-Test", "Test", 40, -120, -8,
                           (member,), ("TS_1",), (), False)
    sensor = pair_ameriflux(site, {})[0]
    assert import_ameriflux_site(site, [sensor], tmp_path / "obs", tmp_path / "flags") == (1, 1)
    assert read_observations(tmp_path / "obs" / f"{sensor.sensor_id}.csv")[0].soil_temperature_c is None
