from datetime import datetime, timezone

from openpyxl import Workbook

from sfcc_label.chapleau import _local_to_utc, _rounded_hour, import_chapleau
from sfcc_label.io import read_observations


def test_hour_rounding_for_publisher_seconds():
    assert _rounded_hour(datetime(2018, 1, 1, 4, 59, 59)) == datetime(2018, 1, 1, 5)
    assert _rounded_hour(datetime(2018, 1, 1, 5, 0, 9)) == datetime(2018, 1, 1, 5)


def test_fixed_standard_clock_keeps_dst_transition_hours():
    assert _local_to_utc(datetime(2017, 6, 2, 0)) == datetime(
        2017, 6, 2, 5, tzinfo=timezone.utc)
    assert _local_to_utc(datetime(2018, 1, 1, 0)) == datetime(
        2018, 1, 1, 5, tzinfo=timezone.utc)
    assert _local_to_utc(datetime(2022, 3, 13, 2)) == datetime(
        2022, 3, 13, 7, tzinfo=timezone.utc)
    assert _local_to_utc(datetime(2021, 11, 7, 1)) == datetime(
        2021, 11, 7, 6, tzinfo=timezone.utc)


def test_import_uses_only_chelene_plot_books(tmp_path):
    source = tmp_path / "Chelene"
    source.mkdir()
    for plot, suffix in (("AS3", "Aw"), ("BS1", "Sb"), ("JP1", "Pj"), ("MW1", "Mw")):
        book = Workbook()
        readme = book.active
        readme.title = "ReadMe"
        readme.append([plot])
        readme.append(["Chapleau, ON"])
        readme.append(["47.5, -83.5"])
        data = book.create_sheet("Data")
        header = ["timestamp", "p1_temp_6", "p3_temp_15", "p5_temp_30"]
        for subplot in (1, 3, 5):
            for replicate, extent in (("a", 10), ("b", 10), ("c", 18), ("d", 18)):
                header.extend((f"p{subplot}{replicate}_period_{extent}",
                               f"p{subplot}{replicate}_vwc.cal_{extent}"))
        data.append(header)
        data.append([datetime(2017, 6, 2, 0), 6.1, 15.2, 30.3] + [21.23, 26.5] * 12)
        book.save(source / f"Chapleau_{suffix}_soil.moisture.temp.xlsx")

    output = tmp_path / "observations"
    rows = import_chapleau(source, output, tmp_path / "sensors.csv",
                           tmp_path / "context.csv", tmp_path / "status.csv",
                           47.71472, -83.39722, "site document")
    assert len(rows) == 60
    assert read_observations(output / "chap_as3_006cm_t.csv")[0].soil_temperature_c == 6.1
    assert read_observations(output / "chap_as3_015cm_t.csv")[0].soil_temperature_c == 15.2
    moisture = read_observations(output / "chap_as3_000-010cm_p1a.csv")[0]
    assert moisture.timestamp_utc == datetime(2017, 6, 2, 5, tzinfo=timezone.utc)
    assert moisture.soil_temperature_c is None
    assert moisture.soil_moisture_m3_m3 == 0.265
    assert moisture.raw_value == 21.23
