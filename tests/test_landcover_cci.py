import csv

import numpy as np
import rasterio
from rasterio.transform import from_origin

from sfcc_label.grid import ease_grid, grid_cell
from sfcc_label.landcover_cci import LOOKUP, aggregate_cci, sensor_landcover


def test_cci_codes_map_to_six_smos_classes():
    assert LOOKUP[70] == 1 and LOOKUP[160] == 1
    assert LOOKUP[140] == 2 and LOOKUP[180] == 3
    assert LOOKUP[30] == 4 and LOOKUP[210] == 5 and LOOKUP[220] == 6
    assert LOOKUP[0] == 0


def test_all_ten_grids_have_published_shapes():
    assert (ease_grid("9km").columns, ease_grid("9km").rows) == (2000, 2000)
    assert (ease_grid("N6p25km").columns, ease_grid("N36km").columns) == (2880, 500)
    assert (ease_grid("M36km").columns, ease_grid("M36km").rows) == (964, 406)
    assert (ease_grid("M25km").columns, ease_grid("M25km").rows) == (1388, 584)
    assert grid_cell(0, 0, "M36km").cell_id == "EASE2_M_36km_r0203_c0482"
    assert ease_grid("6.25km").name == "N6p25km"
    assert grid_cell(60, 10, "M12p5km").cell_id.startswith("EASE2_M_12p5km_")


def test_area_weighted_fractions_and_sensor_rows(tmp_path):
    # 0.01 degree pixels over 60-61 N, 10-11 E: west half forest, east 30 % water
    data = np.full((100, 100), 70, dtype="uint8")
    data[:, 70:] = 210
    source = tmp_path / "cci.tif"
    with rasterio.open(source, "w", driver="GTiff", width=100, height=100, count=1, dtype="uint8",
                       crs="EPSG:4326", transform=from_origin(10, 61, 0.01, 0.01), nodata=0) as out:
        out.write(data, 1)
    written = aggregate_cci(source, tmp_path / "grids", 2015, grids=("N36km", "M36km"),
                            progress=lambda message: None)
    assert len(written) == 2
    with rasterio.open(written[0]) as grid:
        bands = grid.read()
        scales = grid.scales
    occupied = bands[0] > 0
    fractions = bands[1:, occupied] * scales[1]
    assert np.allclose(fractions.sum(axis=0), 1, atol=1e-3)
    assert set(np.unique(bands[0][occupied])) <= {1, 5}
    catalog = tmp_path / "catalog.csv"
    with catalog.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("sensor_id", "source", "site_id", "latitude", "longitude"))
        writer.writerow(("local_a_005cm_s1", "local", "a", 60.5, 10.2))
    output = tmp_path / "sensor_landcover.csv"
    assert sensor_landcover(catalog, source, tmp_path / "grids", output,
                            grids=("N36km", "M36km")) == 2
    rows = list(csv.DictReader(output.open()))
    assert [row["grid"] for row in rows] == ["N36km", "M36km"]
    assert rows[0]["sensor_class"] == "forest"
    assert rows[0]["cci_class"] == "70"
