import csv
from datetime import datetime

from openpyxl import Workbook

from sfcc_label.io import load_metadata, read_observations
from sfcc_label.tvc_hydraprobe import import_tvc_hydraprobe


def _workbook(path):
    wb = Workbook()
    ws = wb.active
    ws.append(["TOA5"])
    headers = ["TIMESTAMP"]
    for probe in ("H1", "H2", "H3", "H4"):
        headers.extend((f"{probe}_Soil_Moisture", f"{probe}_Soil_Temperature_C",
                        f"{probe}_Cor_Real_Permittivity", f"{probe}_Cor_Imaginary_Permittivity"))
    ws.append(headers); ws.append(["TS"] + [None] * 16); ws.append([None] * 17); ws.append(["Date"] + [None] * 16); ws.append(
        [datetime(2018, 1, 1), 0.2, -1, 4, 3, 0.3, -2, 5, 4,
         0.4, -3, 6, 5, 0.5, -4, 7, 6])
    ws.append([datetime(2018, 1, 1, 0, 30), 0.4, -3, 8, 6, 0.5, -4, 9, 7,
               0.6, -5, 10, 8, 0.7, -6, 11, 9])
    wb.save(path)


def test_imports_depths_and_paper_permittivity(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    for station in ("CalTarget", "DriftSite", "MainMet", "OldTrench", "SouthTundra", "ValleyBottom"):
        _workbook(source / f"{station}_TimeSeries.xlsx")
    out = tmp_path / "out"
    contexts = import_tvc_hydraprobe(source, out, tmp_path / "sensors.csv", tmp_path / "context.csv")
    assert len(contexts) == 24
    sensors = load_metadata(tmp_path / "sensors.csv")
    assert sensors["tvch_caltarget_005cm_h1"].depth_cm == 5
    assert sensors["tvch_caltarget_010cm_h2"].depth_cm == 10
    rows = read_observations(out / "tvch_caltarget_005cm_h1.csv")
    assert rows[0].soil_temperature_c == -2
    assert rows[0].soil_moisture_m3_m3 == 0.3
    expected = ((4 + (4**2 + 3**2) ** 0.5) / 2 + (8 + (8**2 + 6**2) ** 0.5) / 2) / 2
    assert abs(rows[0].raw_value - expected) < 1e-12
    assert len(rows) == 1
    with (tmp_path / "context.csv").open() as stream:
        row = next(csv.DictReader(stream))
    assert "sqrt" in row["permittivity_formula"]
