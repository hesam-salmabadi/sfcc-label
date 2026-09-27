"""Build annual EASE-Grid land-cover rasters from prepared MODIS IGBP rasters.

Input must be a georeferenced, one-band MCD12Q1.061 LC_Type1 mosaic/VRT or
GeoTIFF for one year. This module does not download NASA source granules.
"""

from pathlib import Path

from pyproj import Transformer

from .grid import ease_grid, grid_cell
from .landcover import SensorLandCover, screen_land_cover, _class_code
from .models import SensorMetadata


def _rasterio():
    try:
        import rasterio
    except ImportError as exc:
        raise ImportError("Install sfcc-label[geo] to process MODIS rasters") from exc
    return rasterio


def build_igbp_grid(source_raster: str | Path, output_raster: str | Path,
                    resolution: str = "9km") -> None:
    """Reproject a 500 m MODIS IGBP raster to an NSIDC EASE-Grid 2.0 grid.

    Categorical mode resampling gives the dominant input class near each grid
    cell. Source should be a complete mosaic for the Northern Hemisphere.
    """
    rasterio = _rasterio()
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    grid = ease_grid(resolution)
    output_raster = Path(output_raster)
    if output_raster.exists():
        raise FileExistsError(output_raster)
    with rasterio.open(source_raster) as source:
        if source.count != 1 or source.crs is None:
            raise ValueError("source must be a georeferenced, one-band IGBP class raster")
        with rasterio.open(output_raster, "w", driver="GTiff", width=grid.columns,
                           height=grid.rows, count=1, dtype="uint8", crs=grid.crs,
                           transform=grid.transform(),
                           nodata=255, compress="deflate", tiled=True) as target:
            reproject(source=rasterio.band(source, 1),
                      destination=rasterio.band(target, 1),
                      src_transform=source.transform, src_crs=source.crs,
                      src_nodata=source.nodata if source.nodata is not None else 255,
                      dst_transform=target.transform, dst_crs=target.crs,
                      dst_nodata=255, resampling=Resampling.mode,
                      init_dest_nodata=True)


def sample_sensor_land_cover(source_raster: str | Path, year: int,
                             sensors: dict[str, SensorMetadata]) -> list[SensorLandCover]:
    """Sample each sensor's native 500 m IGBP pixel from one annual raster."""
    rasterio = _rasterio()
    result = []
    with rasterio.open(source_raster) as source:
        if source.count != 1 or source.crs is None:
            raise ValueError("source must be a georeferenced, one-band IGBP class raster")
        transformer = Transformer.from_crs("EPSG:4326", source.crs, always_xy=True)
        for sensor in sensors.values():
            x, y = transformer.transform(sensor.longitude, sensor.latitude)
            sample = next(source.sample([(x, y)], masked=True))[0]
            value = None if getattr(sample, "mask", False) else int(sample)
            result.append(SensorLandCover(sensor.sensor_id, year, _class_code(value)))
    return result


def screen_from_grid(grid_raster: str | Path, year: int, resolution: str,
                     sensors: dict[str, SensorMetadata],
                     sensor_classes: dict[tuple[str, int], SensorLandCover]):
    """Compare annual 500 m sensor classes to the dominant EASE cell class."""
    rasterio = _rasterio()
    grid_def = ease_grid(resolution)
    expected = grid_def.transform()
    result = []
    with rasterio.open(grid_raster) as grid:
        if grid.count != 1 or grid.crs is None or grid.crs.to_string() != grid_def.crs or \
                grid.width != grid_def.columns or grid.height != grid_def.rows or \
                not grid.transform.almost_equals(expected):
            raise ValueError("raster does not match the requested NSIDC EASE grid")
        for sensor in sensors.values():
            cell = grid_cell(sensor.latitude, sensor.longitude, resolution)
            grid_class = int(grid.read(1, window=((cell.row, cell.row + 1),
                                                   (cell.col, cell.col + 1)))[0, 0])
            source = sensor_classes.get((sensor.sensor_id, year))
            result.append(screen_land_cover(sensor, year, resolution,
                                            source.igbp_class if source else None,
                                            grid_class))
    return result
