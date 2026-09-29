import csv
import pytest

from sfcc_label.above_moisture import import_above_moisture
from sfcc_label.io import load_metadata, read_observations
from sfcc_label.usarray_ground import import_usarray_ground


def test_usarray_keeps_duplicate_depth_columns_and_averages_repeated_hour(tmp_path):
    root = tmp_path / "1680"
    data = root / "data"
    data.mkdir(parents=True)
    (data / "USArray_Sites.csv").write_text(
        "site,latitude,longitude\nA19-1,70,-161\n", encoding="utf-8")
    (data / "A19K-1_2017-09-28_2017-09-29.csv").write_text(
        "date_time,timezone,tsoil_0,tsoil_0,tsoil_-1,tsoil_NaN\n"
        "2017-09-28 6:34,AKST,2,8,99,4\n"
        "2017-09-28 6:34,AKST,4,10,99,6\n", encoding="utf-8")
    output = tmp_path / "out"
    rows = import_usarray_ground(root, output, tmp_path / "sensors.csv",
                                tmp_path / "context.csv", tmp_path / "status.csv",
                                release="1680")
    assert len(rows) == 1 and rows[0]["imported_sensors"] == 3
    assert rows[0]["above_ground_columns_skipped"] == 1
    sensors = load_metadata(tmp_path / "sensors.csv")
    assert len(sensors) == 3
    assert {sensor.depth_cm for sensor in sensors.values()} == {0.0, None}
    first = read_observations(output / "usar_a19-1_000cm_c2.csv")[0]
    assert first.timestamp_utc.isoformat() == "2017-09-28T16:00:00+00:00"
    assert first.soil_temperature_c == 3
    assert read_observations(output / "usar_a19-1_000cm_c3.csv")[0].soil_temperature_c == 9


def test_older_profiles_keep_shared_site_separate(tmp_path):
    root = tmp_path / "1767"
    (root / "data").mkdir(parents=True)
    (root / "comp").mkdir()
    (root / "comp/USArray_site_metadata.csv").write_text(
        "USAR_Site,Latitude_WGS84,Longitude_WGS84\n"
        "E23K,68,-149\nC17K,68.5,-163\n", encoding="utf-8")
    for site in ("E23K", "C17K-1"):
        (root / "data" / f"{site}_2017-01-01_2017-01-02.csv").write_text(
            "date_time,tsoil_0.2m\n2017-01-01 0:00,-2\n", encoding="utf-8")
    output = tmp_path / "out"
    rows = import_usarray_ground(root, output, tmp_path / "sensors.csv",
                                tmp_path / "context.csv", tmp_path / "status.csv",
                                release="1767")
    assert sorted(row["status"] for row in rows) == ["imported", "imported"]
    assert len(list(output.glob("*.csv"))) == 2
    assert read_observations(output / "akpr_e23k_020cm_c1.csv")[0].soil_temperature_c == -2


def test_usarray_rejects_ambiguous_dst_hour(tmp_path):
    root = tmp_path / "1680"
    data = root / "data"
    data.mkdir(parents=True)
    (data / "USArray_Sites.csv").write_text(
        "site,latitude,longitude\nMRA-1,65,-149\n", encoding="utf-8")
    (data / "MRA-1_2018-10-18_2018-11-05.csv").write_text(
        "date_time,timezone,tsoil_0\n"
        "2018-11-04 1:00,AKST,-1\n"
        "2018-11-04 1:00,AKST,-2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="UTC is ambiguous"):
        import_usarray_ground(root, tmp_path / "out", tmp_path / "sensors.csv",
                              tmp_path / "context.csv", tmp_path / "status.csv",
                              release="1680")
    rows = import_usarray_ground(root, tmp_path / "safe", tmp_path / "safe_sensors.csv",
                                tmp_path / "safe_context.csv", tmp_path / "safe_status.csv",
                                release="1680", skip_ambiguous_clock_files=True)
    assert rows[0]["status"] == "clock_ambiguous_excluded"
    assert len(list((tmp_path / "safe").glob("*.csv"))) == 0


def test_above_logger_preserves_temperature_and_individual_moisture(tmp_path):
    root = tmp_path / "2123"
    data = root / "data"
    data.mkdir(parents=True)
    with (data / "probe_specific_soil_profile_model_coefficients.csv").open("w") as stream:
        writer = csv.writer(stream)
        writer.writerow(("area", "latitude", "longitude", "plot", "probe", "depth_cm"))
        for n, depth in enumerate((6, 10, 18, 30), 1):
            writer.writerow(("Alaska", 69, -148, "plot", f"123-{n}", depth))
    header = ("probe_id,time_stamp,record,batt_V_min,pa_us_avg_1,pa_us_avg_2,"
              "pa_us_avg_3,pa_us_avg_4,t109_c_avg,probe1_cal,probe2_cal,"
              "probe3_cal,probe4_cal\n")
    (data / "alaska_probe_period_temp_cal_vmc.csv").write_text(
        header + "123,2017-07-01 12:00:00,1,12,20,21,22,23,1,50,60,70,80\n"
        + "123,2017-07-01 12:00:00,2,12,22,23,24,25,3,60,70,80,90\n",
        encoding="utf-8")
    (data / "alberta_probe_period_temp_cal_vmc.csv").write_text(header, encoding="utf-8")
    output = tmp_path / "out"
    rows = import_above_moisture(root, output, tmp_path / "sensors.csv",
                                 tmp_path / "context.csv", tmp_path / "status.csv",
                                 alaska_utc_offset_hours=-9,
                                 alberta_utc_offset_hours=-7,
                                 time_basis_evidence="test fixture")
    assert sum(row["sensor_count"] for row in rows) == 5
    temperature = read_observations(output / "abvm_alaska-123_nodepth_t109.csv")[0]
    assert temperature.soil_temperature_c == 2
    moisture = read_observations(output / "abvm_alaska-123_000-006cm_p1.csv")[0]
    assert moisture.soil_temperature_c is None
    assert moisture.soil_moisture_m3_m3 == 0.55
    assert moisture.raw_value == 21
