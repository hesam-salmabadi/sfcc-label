import csv

import pytest

from sfcc_label.io import load_metadata, read_observations
from sfcc_label.local import import_local, read_local_metadata


def test_berms_depth_from_source_column(tmp_path):
    metadata = tmp_path / "metadata.csv"
    metadata.write_text(
        "Site ID,Network Name,Coordinates_Lat,Coordinates_Lon,Sensor Depth (cm)\n"
        "BS01,BERMS,53.987,-105.118,\n"
        "JP01,BERMS,53.916,-104.692,\n"
    )
    sensors = read_local_metadata(metadata)
    assert {sensor.depth_cm for sensor in sensors.values()} == {5.0}
    assert all(sensor.depth_from_cm == 5.0 and sensor.depth_to_cm == 5.0
               for sensor in sensors.values())
    assert all("unverified" in sensor.timezone_original for sensor in sensors.values())
    metadata.write_text(
        "Site ID,Network Name,Coordinates_Lat,Coordinates_Lon,Sensor Depth (cm)\n"
        "BS01,BERMS,53.987,-105.118,10\n"
    )
    with pytest.raises(ValueError, match="conflicts"):
        read_local_metadata(metadata)


def test_local_import_splits_averages_deduplicates_and_fills_hours(tmp_path):
    metadata = tmp_path / "metadata.csv"
    with metadata.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("Site ID", "Network Name", "Coordinates_Lat",
                         "Coordinates_Lon", "Sensor Depth (cm)"))
        writer.writerow(("CP01", "CP", 47, -83, 10))
        writer.writerow(("MT01", "MT", 49, -80, ""))
    source = tmp_path / "level0"
    source.mkdir()
    with (source / "CP.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("datetime", "site_id", "soil_temp", "soil_moist", "bulk_edc"))
        writer.writerow(("2020-07-01 02:00:00", "CP01", 8, "", 4))
        writer.writerow(("2020-07-01 00:30:00", "CP01", 4, 0.2, 2))
        writer.writerow(("2020-07-01 00:30:00", "CP01", 4, 0.2, 2))
        writer.writerow(("2020-07-01 00:45:00", "CP01", 6, 9999.0, 4))
    with (source / "MT.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("datetime", "site_id", "soil_temp", "soil_moist", "bulk_edc"))
        writer.writerow(("2020-07-01 00:00:00", "MT01", "NaN", 0, ""))
    output = tmp_path / "out"
    sensors_file = tmp_path / "sensors.csv"
    status_file = tmp_path / "status.csv"
    rows = import_local(source, metadata, output, sensors_file, status_file)
    assert len(rows) == 2
    cp = read_observations(output / "local_cp01_000-010cm_s1.csv")
    assert len(cp) == 3
    assert (cp[0].soil_temperature_c, cp[0].soil_moisture_m3_m3,
            cp[0].raw_value) == (5, 0.2, 3)
    assert (cp[1].soil_temperature_c, cp[1].soil_moisture_m3_m3,
            cp[1].raw_value) == (None, None, None)
    assert (cp[2].soil_temperature_c, cp[2].soil_moisture_m3_m3,
            cp[2].raw_value) == (8, None, 4)
    mt = read_observations(output / "local_mt01_nodepth_s1.csv")
    assert (mt[0].soil_temperature_c, mt[0].soil_moisture_m3_m3,
            mt[0].raw_value) == (None, 0, None)
    sensors = load_metadata(sensors_file)
    assert (sensors["local_cp01_000-010cm_s1"].depth_cm,
            sensors["local_cp01_000-010cm_s1"].depth_from_cm,
            sensors["local_cp01_000-010cm_s1"].depth_to_cm) == (5, 0, 10)
    assert sensors["local_mt01_nodepth_s1"].depth_cm is None
    assert sensors["local_cp01_000-010cm_s1"].raw_variable == "bulk_edc"
    assert rows[0]["duplicate_samples"] == 1
    with pytest.raises(FileExistsError):
        import_local(source, metadata, output, sensors_file, status_file)


def test_local_import_rejects_conflicting_duplicate(tmp_path):
    metadata = tmp_path / "metadata.csv"
    metadata.write_text("Site ID,Network Name,Coordinates_Lat,Coordinates_Lon,Sensor Depth (cm)\n"
                        "AB01,AB,47,-83,5\n")
    source = tmp_path / "level0"
    source.mkdir()
    (source / "AB.csv").write_text(
        "datetime,site_id,soil_temp,soil_moist,bulk_edc\n"
        "2020-07-01 00:00:00,AB01,4,,\n"
        "2020-07-01 00:00:00,AB01,5,,\n")
    with pytest.raises(ValueError, match="conflicting samples"):
        import_local(source, metadata, tmp_path / "out", tmp_path / "sensors.csv",
                     tmp_path / "status.csv")
    assert not (tmp_path / "out" / "local_ab01_005cm_s1.csv").exists()
    rows = import_local(source, metadata, tmp_path / "out", tmp_path / "sensors.csv",
                        tmp_path / "status.csv", skip_conflicting_sites=True)
    assert rows[0]["status"] == "skipped_conflicting_samples"
    assert load_metadata(tmp_path / "sensors.csv") == {}
    assert not (tmp_path / "out" / "local_ab01_005cm_s1.csv").exists()


def test_local_import_excludes_publisher_ibutton_sites(tmp_path):
    metadata = tmp_path / "metadata.csv"
    metadata.write_text("Site ID,Network Name,Coordinates_Lat,Coordinates_Lon,Sensor Depth (cm)\n"
                        "NI01,Inuvik,68,-133,\n"
                        "NT01,Tuktoyaktuk,69,-133,\n"
                        "AL01,Alaska ISMN,60,-150,\n"
                        "RI01,RISMA ISMN,49,-82,\n"
                        "CB01,Cambridge Bay,69,-104,\n"
                        "CP01,CP,47,-83,10\n")
    source = tmp_path / "level0"
    source.mkdir()
    (source / "sites.csv").write_text(
        "datetime,site_id,soil_temp,soil_moist,bulk_edc\n"
        "2020-07-01 00:00:00,NI01,2,,\n"
        "2020-07-01 00:00:00,NT01,3,,\n"
        "2020-07-01 00:00:00,AL01,3,,\n"
        "2020-07-01 00:00:00,RI01,3,,\n"
        "2020-07-01 00:00:00,CB01,3,,\n"
        "2020-07-01 00:00:00,CP01,4,,\n")
    output = tmp_path / "out"
    rows = import_local(source, metadata, output, tmp_path / "sensors.csv",
                        tmp_path / "status.csv")
    assert [row["site_id"] for row in rows] == ["CP01"]
    assert set(load_metadata(tmp_path / "sensors.csv")) == {"local_cp01_000-010cm_s1"}
    assert sorted(path.name for path in output.glob("*.csv")) == ["local_cp01_000-010cm_s1.csv"]
