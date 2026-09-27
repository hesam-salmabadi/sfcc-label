import csv

import numpy as np
import rasterio
from rasterio.transform import from_origin

from sfcc_label.soilgrids import (POINT_COLUMNS, ameriflux_level_layers, assign_layer,
                                  layer_for_depth, match_sensors, sample_raster, usda_texture)

CATALOG_COLUMNS = ("sensor_id", "source", "latitude", "longitude", "depth_cm")


def test_depth_is_rounded_then_bottom_edge_inclusive():
    assert layer_for_depth(0) == (0, 5)
    assert layer_for_depth(5.4) == (0, 5)
    assert layer_for_depth(5.6) == (5, 15)
    assert layer_for_depth(15) == (5, 15)
    assert layer_for_depth(16) == (15, 30)
    assert layer_for_depth(250) == (100, 200)


def test_unknown_ameriflux_depth_uses_most_common_layer_for_level():
    rows = [
        {"sensor_id": "amf_x_003cm_h1v1r1", "source": "ameriflux", "depth_cm": "3"},
        {"sensor_id": "amf_x_010cm_h1v2r1", "source": "ameriflux", "depth_cm": "10"},
        {"sensor_id": "amf_y_004cm_h1v2r1", "source": "ameriflux", "depth_cm": "4"},
        {"sensor_id": "amf_z_012cm_h1v2r1", "source": "ameriflux", "depth_cm": "12"},
    ]
    levels = ameriflux_level_layers(rows)
    assert levels["v2"] == ((5, 15), 2, 3)
    layer, basis, note = assign_layer(
        {"sensor_id": "amf_q_nodepth_h2v2r1", "source": "ameriflux", "depth_cm": "NaN"}, levels)
    assert (layer, basis) == ((5, 15), "assumed_from_level")
    assert "67% of 3" in note
    layer, basis, _ = assign_layer(
        {"sensor_id": "amf_q_nodepth_i1", "source": "ameriflux", "depth_cm": "NaN"}, levels)
    assert (layer, basis) == ((0, 5), "assumed_top")


def test_usda_texture_classes():
    assert usda_texture(92, 5, 3) == "sand"
    assert usda_texture(40, 40, 20) == "loam"
    assert usda_texture(20, 65, 15) == "silt loam"
    assert usda_texture(28.2, 37, 34.8) == "clay loam"
    assert usda_texture(10, 30, 60) == "clay"


def test_nodata_pixel_falls_back_to_nearest_valid(tmp_path):
    path = tmp_path / "grid.tif"
    data = np.full((9, 9), -32768, dtype="int16")
    data[4, 6] = 250
    with rasterio.open(path, "w", driver="GTiff", width=9, height=9, count=1, dtype="int16",
                       crs="EPSG:3857", transform=from_origin(-1125, 1125, 250, 250),
                       nodata=-32768) as dataset:
        dataset.write(data, 1)
    with rasterio.open(path) as dataset:
        (value, offset), = sample_raster(dataset, [(0.0, 0.0)])
    assert (value, offset) == (250, 500.0)


def test_match_sensors_takes_values_from_matched_layer(tmp_path):
    catalog = tmp_path / "catalog.csv"
    with catalog.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CATALOG_COLUMNS)
        writer.writeheader()
        writer.writerow({"sensor_id": "local_a_010cm_s1", "source": "local",
                         "latitude": "60.0", "longitude": "-100.0", "depth_cm": "10"})
    points = tmp_path / "points.csv"
    with points.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(POINT_COLUMNS)
        for prop, top, bottom, value in (("clay", 0, 5, "10"), ("clay", 5, 15, "30"),
                                         ("sand", 5, 15, "30"), ("silt", 5, 15, "40")):
            writer.writerow((60.0, -100.0, prop, "mean", top, bottom, "", value, "%", "0"))
        writer.writerow((60.0, -100.0, "wrb", "class", "", "", "8", "Cryosols", "class", "0"))
    output = tmp_path / "sensor_soil.csv"
    summary = match_sensors(catalog, points, output, accessed="2026-09-27")
    row, = csv.DictReader(output.open())
    assert (row["soilgrids_top_cm"], row["soilgrids_bottom_cm"]) == ("5", "15")
    assert row["clay_pct"] == "30"
    assert row["texture_class_usda"] == "clay loam"
    assert row["wrb_class"] == "Cryosols"
    assert row["soc_g_kg"] == "NaN"
    assert summary["measured"] == 1
