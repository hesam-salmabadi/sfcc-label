import csv

import pytest

from sfcc_label.dryden import import_dryden
from sfcc_label.io import load_metadata, read_observations


openpyxl = pytest.importorskip("openpyxl")


def _source(path):
    book = openpyxl.Workbook()
    data = book.active
    data.title = "Raw time series data"
    data.append(("Raw_data_identifier", "Year", "Month", "Day", "Time (24h)",
                 "Temperature"))
    metadata = book.create_sheet("Metadata")
    metadata.append(("Raw_data_identifier", "Latitude", "Longitude", "Sensor_height",
                     "Timezone", "Unit", "Microclimate_measurement"))
    for source_depth in (6, 18, 30):
        ident = f"Dryden_{source_depth}"
        metadata.append((ident, 49.868744, -92.604012, -source_depth, "UTC", "°C",
                         "Temperature"))
        data.append((ident, 2019, 7, 24, "17:00:00", float(source_depth)))
        data.append((ident, 2019, 7, 24, "19:00:00", float(source_depth + 1)))
        data.append((ident, "NA", "NA", "NA", "NA", 99.0))
    book.save(path)


def test_import_requires_explicit_depths_and_preserves_missing_hour(tmp_path):
    source = tmp_path / "Dryden_SoilTemp.xlsx"
    _source(source)
    output = tmp_path / "observations"
    sensors = tmp_path / "sensors.csv"
    context = tmp_path / "context.csv"
    status = tmp_path / "status.csv"
    with pytest.raises(ValueError, match="assigned depths"):
        import_dryden(source, output, sensors, context, status, {6: 6}, "")
    rows = import_dryden(source, output, sensors, context, status,
                         {6: 10, 18: 14, 30: 18}, "owner confirmation")
    assert len(rows) == 3
    assert all(row["undated_rows"] == 1 and row["output_hours"] == 3 for row in rows)
    registry = load_metadata(sensors)
    assert registry["dryden_dryden_010cm_s1"].depth_cm == 10
    assert registry["dryden_dryden_018cm_s1"].depth_cm == 18
    observations = read_observations(output / "dryden_dryden_010cm_s1.csv")
    assert [row.soil_temperature_c for row in observations] == [6, None, 7]
    assert all(row.soil_moisture_m3_m3 is None and row.raw_value is None
               for row in observations)
    with context.open(newline="") as stream:
        context_rows = list(csv.DictReader(stream))
    assert context_rows[0]["workbook_depth_cm"] == "6"
    assert context_rows[0]["assigned_depth_cm"] == "10.0"
    with pytest.raises(FileExistsError):
        import_dryden(source, output, sensors, context, status,
                      {6: 10, 18: 14, 30: 18}, "owner confirmation")


def test_import_rejects_undeclared_timezone(tmp_path):
    source = tmp_path / "Dryden_SoilTemp.xlsx"
    _source(source)
    book = openpyxl.load_workbook(source)
    book["Metadata"]["E2"] = "local"
    book.save(source)
    with pytest.raises(ValueError, match="expected workbook UTC"):
        import_dryden(source, tmp_path / "obs", tmp_path / "sensors.csv",
                      tmp_path / "context.csv", tmp_path / "status.csv",
                      {6: 6, 18: 18, 30: 30}, "source metadata")
