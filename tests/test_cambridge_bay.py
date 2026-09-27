import csv
import zipfile
from datetime import timedelta

from sfcc_label.cambridge_bay import (_write_hourly, read_cambridge_sites,
                                      read_retrieval_depths,
                                      read_temperature_samples)


def _write_book(path, rows):
    cells = []
    for row_number, values in enumerate(rows, 1):
        content = []
        for column, value in values.items():
            if isinstance(value, str):
                content.append(f'<c r="{column}{row_number}" t="inlineStr"><is><t>{value}</t></is></c>')
            else:
                content.append(f'<c r="{column}{row_number}"><v>{value}</v></c>')
        cells.append(f'<row r="{row_number}">{"".join(content)}</row>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml",
                         '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                         f'<sheetData>{"".join(cells)}</sheetData></worksheet>')


def test_deployment_and_retrieval_depths_are_distinct(tmp_path):
    deployment = tmp_path / "Metadata.xlsx"
    _write_book(deployment, [
        {"A": f"IP{number}", "C": 69.2 + number / 10000,
         "D": -104.9, "F": "Moss", "G": "Organic over clay",
         "I": "10:4, 29:12"}
        for number in range(1, 17)
    ])
    sites = read_cambridge_sites(deployment)
    assert len(sites) == 16
    assert sites["CB01"].deployment_buttons == {4: "10", 12: "29"}

    retrieval = tmp_path / "CB_ib_data.xlsx"
    _write_book(retrieval, [{"A": "IP1-2", "B": "1-0"},
                            {"A": "IP1-5", "B": "1-5"},
                            {"A": "IP13-0", "B": "13-0"}])
    assert read_retrieval_depths(retrieval) == {
        ("CB01", 0): 2, ("CB01", 5): 5, ("CB13", 0): 0,
    }


def test_three_hour_source_samples_leave_other_hours_missing(tmp_path):
    source = tmp_path / "CB1_5.csv"
    source.write_text("date/time,unite,value\n"
                      "19-07-22 00:51:01,C,10.692\n"
                      "19-07-22 03:51:01,C,11.225\n")
    samples = read_temperature_samples(source)
    assert samples[1][0] - samples[0][0] == timedelta(hours=3)
    output = tmp_path / "hourly.csv"
    sampled, hours, _, _ = _write_hourly(output, samples)
    with output.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert (sampled, hours) == (2, 4)
    assert [row["soil_temperature_c"] for row in rows] == [
        "10.692", "NaN", "NaN", "11.225",
    ]
    assert all(row["soil_moisture_m3_m3"] == "NaN" and row["raw_value"] == "NaN"
               for row in rows)
