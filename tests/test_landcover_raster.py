import pytest

rasterio = pytest.importorskip("rasterio")
import numpy as np
from rasterio.transform import from_origin

from sfcc_label import SensorMetadata
from sfcc_label.landcover_raster import (build_igbp_grid, sample_sensor_land_cover,
                                         screen_from_grid)


def test_modis_sampling_and_both_northern_grids(tmp_path):
    source = tmp_path / "synthetic_500m_igbp.tif"
    with rasterio.open(source, "w", driver="GTiff", width=120, height=120,
                       count=1, dtype="uint8", crs="EPSG:6931", nodata=255,
                       transform=from_origin(-30000, 30000, 500, 500)) as dst:
        dst.write(np.full((120, 120), 5, dtype="uint8"), 1)
    sensors = {"pole": SensorMetadata("pole", "local", 90, 0)}
    sampled = sample_sensor_land_cover(source, 2020, sensors)
    assert sampled[0].igbp_class == 5
    classes = {("pole", 2020): sampled[0]}
    for resolution in ("9km", "25km"):
        grid = tmp_path / f"{resolution}.tif"
        build_igbp_grid(source, grid, resolution)
        with rasterio.open(grid) as raster:
            assert raster.crs.to_epsg() == 6931
            assert raster.width == (2000 if resolution == "9km" else 720)
        screen, = screen_from_grid(grid, 2020, resolution, sensors, classes)
        assert screen.eligible
