"""Small command-line entry points for stage-one validation and grid lookup."""

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path

from .grid import grid_cell
from .io import load_metadata, read_observations
from .ismn import (import_ismn_pair, pair_ismn, scan_ismn,
                   write_ismn_inventory)
from .landcover import (read_land_cover_screen, read_sensor_land_cover,
                        write_land_cover_screen, write_sensor_land_cover)
from .landcover_raster import (build_igbp_grid, sample_sensor_land_cover,
                               screen_from_grid)


def main() -> None:
    parser = argparse.ArgumentParser(prog="sfcc-label")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate metadata and per-sensor hourly CSV files")
    validate.add_argument("metadata", type=Path)
    validate.add_argument("observations_dir", type=Path)
    cell = subparsers.add_parser("cell", help="look up a latitude/longitude in EASE-Grid 2.0")
    cell.add_argument("latitude", type=float)
    cell.add_argument("longitude", type=float)
    cell.add_argument("--resolution", choices=("9km", "25km"), default="9km")
    landcover = subparsers.add_parser("prepare-landcover", help="prepare one year of MODIS IGBP screening")
    landcover.add_argument("year", type=int)
    landcover.add_argument("source_raster", type=Path,
                           help="one-band MCD12Q1.061 LC_Type1 GeoTIFF/VRT mosaic")
    landcover.add_argument("--metadata", type=Path, default=Path("metadata/sensors.csv"))
    landcover.add_argument("--grid-dir", type=Path, default=Path("data/landcover"))
    landcover.add_argument("--sensor-table", type=Path,
                           default=Path("metadata/sensor_landcover.csv"))
    landcover.add_argument("--screen-table", type=Path,
                           default=Path("metadata/landcover_screen.csv"))
    index = subparsers.add_parser("index-ismn", help="inventory northern ISMN sites and depth pairs")
    index.add_argument("root", type=Path)
    index.add_argument("--output-dir", type=Path, default=Path("metadata/private"))
    importer = subparsers.add_parser("import-ismn", help="normalize a bounded ISMN time window")
    importer.add_argument("root", type=Path)
    importer.add_argument("--start", required=True, help="inclusive UTC date, YYYY-MM-DD")
    importer.add_argument("--end", required=True, help="exclusive UTC date, YYYY-MM-DD")
    importer.add_argument("--network", help="optional exact network name")
    importer.add_argument("--station", help="optional exact station name")
    importer.add_argument("--paired-only", action="store_true",
                          help="only import sensors with both temperature and moisture")
    importer.add_argument("--max-sensors", type=int, help="limit output for a pilot run")
    importer.add_argument("--observations-dir", type=Path,
                          default=Path("data/standardized"))
    importer.add_argument("--flags-dir", type=Path, default=Path("data/flags/ismn"))
    args = parser.parse_args()
    if args.command == "cell":
        print(grid_cell(args.latitude, args.longitude, args.resolution).cell_id)
    elif args.command == "index-ismn":
        files, issues = scan_ismn(args.root)
        pairs = pair_ismn(files)
        write_ismn_inventory(args.root, args.output_dir, pairs, issues)
        print(f"Indexed {sum(pair.temperature is not None for pair in pairs)} northern "
              f"temperature sensors; {len(issues)} scan issues")
    elif args.command == "import-ismn":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.start) or \
                not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.end):
            raise ValueError("start and end must be UTC dates, YYYY-MM-DD")
        start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
        if start.time() != datetime.min.time() or end.time() != datetime.min.time():
            raise ValueError("start and end must be UTC dates, YYYY-MM-DD")
        if args.max_sensors is not None and args.max_sensors <= 0:
            raise ValueError("max-sensors must be positive")
        files, issues = scan_ismn(args.root)
        errors = [issue for issue in issues if not issue[1].startswith("excluded:")]
        if errors:
            raise ValueError(f"{len(errors)} ISMN files could not be parsed; run index-ismn first")
        pairs = [pair for pair in pair_ismn(files)
                 if pair.temperature is not None
                 and (args.network is None or pair.depth_key[0] == args.network)
                 and (args.station is None or pair.depth_key[1] == args.station)
                 and (not args.paired_only or pair.moisture is not None)]
        if args.max_sensors is not None:
            pairs = pairs[:args.max_sensors]
        rows = 0
        imported = 0
        for pair in pairs:
            count = import_ismn_pair(pair, start, end,
                                     args.observations_dir, args.flags_dir)
            rows += count
            imported += count > 0
        print(f"Imported {imported} sensors and {rows} hourly rows")
    elif args.command == "prepare-landcover":
        sensors = load_metadata(args.metadata)
        old_sensor = read_sensor_land_cover(args.sensor_table) if args.sensor_table.exists() else {}
        old_screen = read_land_cover_screen(args.screen_table) if args.screen_table.exists() else {}
        if any(key[1] == args.year for key in old_sensor):
            raise ValueError(f"sensor land cover already exists for {args.year}")
        if any(key[1] == args.year for key in old_screen):
            raise ValueError(f"land-cover screen already exists for {args.year}")
        paths = {resolution: args.grid_dir / f"ease2_n_{resolution}_{args.year}.tif"
                 for resolution in ("9km", "25km")}
        if any(path.exists() for path in paths.values()):
            raise FileExistsError("land-cover grid already exists for this year")
        args.grid_dir.mkdir(parents=True, exist_ok=True)
        sampled = sample_sensor_land_cover(args.source_raster, args.year, sensors)
        annual = {(record.sensor_id, record.year): record for record in sampled}
        screens = []
        for resolution, path in paths.items():
            build_igbp_grid(args.source_raster, path, resolution)
            screens.extend(screen_from_grid(path, args.year, resolution, sensors, annual))
        write_sensor_land_cover(args.sensor_table,
                                sorted((*old_sensor.values(), *sampled),
                                       key=lambda record: (record.year, record.sensor_id)))
        write_land_cover_screen(args.screen_table,
                                sorted((*old_screen.values(), *screens),
                                       key=lambda record: (record.year, record.resolution,
                                                           record.sensor_id)))
        print(f"Prepared {args.year}: {len(sampled)} sensor classes and two EASE grids")
    else:
        sensors = load_metadata(args.metadata)
        for sensor_id in sensors:
            path = args.observations_dir / f"{sensor_id}.csv"
            hours = read_observations(path)
            print(f"{sensor_id}: {len(hours)} hourly rows")
        extras = sorted(path.name for path in args.observations_dir.glob("*.csv")
                        if path.stem not in sensors)
        if extras:
            raise ValueError(f"observation files without metadata: {', '.join(extras)}")
        print(f"Validated {len(sensors)} sensors")


if __name__ == "__main__":
    main()
