import csv
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sfcc_label.nrcan_ibutton import (_resolve_local_time, _sensor_id, _site_code,
                                      _write_hourly, read_raw_samples,
                                      read_site_data)


def test_corrected_filename_site_mapping_and_sensor_ids():
    assert _site_code(Path("T18_DD_36BF0221.csv")) == ("T16", True)
    assert _site_code(Path("T36_7A_36CA7521.csv")) == ("T35", True)
    assert _site_code(Path("T18_84_36BF0121.csv")) == ("T18", False)
    assert _sensor_id("T16") == "nrcan_nt16_013cm_s1"
    assert _sensor_id("I5") == "nrcan_ni05_013cm_s1"


def test_dst_fold_uses_255_minute_logger_cadence():
    zone = ZoneInfo("America/Toronto")
    target = datetime(2016, 11, 6, 1, 30)
    previous_edt = datetime(2016, 11, 5, 21, 15, tzinfo=zone).astimezone(timezone.utc)
    previous_est = datetime(2016, 11, 5, 22, 15, tzinfo=zone).astimezone(timezone.utc)
    first, flag = _resolve_local_time(target, zone, previous_edt, Path("raw.csv"))
    second, flag2 = _resolve_local_time(target, zone, previous_est, Path("raw.csv"))
    assert flag and flag2
    assert first == datetime(2016, 11, 6, 5, 30, tzinfo=timezone.utc)
    assert second == datetime(2016, 11, 6, 6, 30, tzinfo=timezone.utc)


def test_sparse_hourly_output_does_not_copy_temperature_to_empty_hours(tmp_path):
    start = datetime(2016, 8, 22, 1, 5, tzinfo=timezone.utc)
    path = tmp_path / "out.csv"
    sampled, hours, _, _ = _write_hourly(
        path, [(start, 7.5), (start + timedelta(minutes=255), 8.0)])
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert (sampled, hours) == (2, 5)
    assert [row["soil_temperature_c"] for row in rows] == ["7.5", "NaN", "NaN", "NaN", "8"]
    assert all(row["soil_moisture_m3_m3"] == "NaN" and row["raw_value"] == "NaN"
               for row in rows)


def test_read_original_header_and_site_workbook(tmp_path):
    raw = tmp_path / "T18_84_36BF0121.csv"
    raw.write_text("\n".join([
        "1-Wire/iButton Part Number: DS1921G-F5",
        "1-Wire/iButton Registration Number: 8400000036BF0121",
        *(["metadata"] * 12), "Date/Time,Unit,Value",
        "21/08/16 9:05:00 PM,C,7.5", "22/08/16 1:20:00 AM,C,8",
    ]) + "\n")
    registration, samples, ambiguous = read_raw_samples(raw)
    assert registration == "8400000036BF0121"
    assert (len(samples), ambiguous) == (2, 0)
    assert samples[1][0] - samples[0][0] == timedelta(minutes=255)

    book = tmp_path / "Site_data.xlsx"
    with zipfile.ZipFile(book, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", """
          <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
            <si><t>T18</t></si>
          </sst>""")
        archive.writestr("xl/worksheets/sheet1.xml", """
          <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
            <sheetData><row r="2">
              <c r="A2" t="s"><v>0</v></c>
              <c r="C2"><v>69.365939</v></c>
              <c r="D2"><v>133.036063</v></c>
              <c r="G2"><v>8</v></c>
            </row></sheetData>
          </worksheet>""")
    site = read_site_data(book)["T18"]
    assert (site.latitude, site.longitude, site.organic_layer_cm) == (
        69.365939, -133.036063, 8)
