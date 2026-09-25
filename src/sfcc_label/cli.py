"""Small command-line entry points for stage-one validation and grid lookup."""

import argparse
import csv
import re
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from zipfile import BadZipFile

from .ameriflux import (import_ameriflux_site, pair_ameriflux,
                        read_measurement_heights, scan_ameriflux,
                        write_ameriflux_inventory)
from .grid import grid_cell
from .io import load_metadata, read_observations
from .ismn import (import_ismn_pair, pair_ismn, scan_ismn,
                   write_ismn_inventory)
from .landcover import (read_land_cover_screen, read_sensor_land_cover,
                        write_land_cover_screen, write_sensor_land_cover)
from .landcover_raster import (build_igbp_grid, sample_sensor_land_cover,
                               screen_from_grid)


def _import_ismn_task(task):
    pair, start, end, observations_dir, flags_dir, skip_existing = task
    observation_path = observations_dir / f"{pair.sensor_id}.csv"
    flag_path = flags_dir / f"{pair.sensor_id}.csv.gz"
    if observation_path.exists() or flag_path.exists():
        if observation_path.exists() and flag_path.exists() and skip_existing:
            return "skipped_existing", 0, ""
        return "error", 0, "existing or incomplete output"
    try:
        count = import_ismn_pair(pair, start, end, observations_dir, flags_dir)
        return ("imported" if count else "no_data"), count, ""
    except ValueError as exc:
        return "error", 0, str(exc)


def _import_ameriflux_task(task):
    archive, sensors, observations_dir, flags_dir, start, end, skip_existing = task
    paths = [(observations_dir / f"{sensor.sensor_id}.csv",
              flags_dir / f"{sensor.sensor_id}.csv.gz") for sensor in sensors]
    if any(obs.exists() or flag.exists() for obs, flag in paths):
        if skip_existing and all(obs.exists() and flag.exists() for obs, flag in paths):
            return "skipped_existing", 0, ""
        return "error", 0, "existing or incomplete site output"
    try:
        hours, invalid_cells = import_ameriflux_site(archive, sensors, observations_dir,
                                                     flags_dir, start=start, end=end)
        detail = f"invalid_numeric_cells={invalid_cells}" if invalid_cells else ""
        return ("imported" if hours else "no_data"), hours * len(sensors), detail
    except (ValueError, OSError, BadZipFile, csv.Error, IndexError, UnicodeError) as exc:
        return "error", 0, str(exc)


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
    importer.add_argument("--status-file", type=Path,
                          help="append per-sensor results for a resumable batch")
    importer.add_argument("--skip-existing", action="store_true",
                          help="skip sensors with both output files already present")
    importer.add_argument("--workers", type=int, default=1,
                          help="parallel sensor imports (default: 1)")
    amf_index = subparsers.add_parser("index-ameriflux", help="inventory northern AmeriFlux BASE TS/SWC")
    amf_index.add_argument("root", type=Path)
    amf_index.add_argument("--height-file", required=True, type=Path)
    amf_index.add_argument("--output-dir", type=Path, default=Path("metadata/private"))
    amf_import = subparsers.add_parser("import-ameriflux", help="harmonize AmeriFlux BASE to UTC hourly CSVs")
    amf_import.add_argument("root", type=Path)
    amf_import.add_argument("--height-file", required=True, type=Path)
    amf_import.add_argument("--site", help="optional exact AmeriFlux site code")
    amf_import.add_argument("--max-sites", type=int)
    amf_import.add_argument("--start", help="inclusive UTC date, YYYY-MM-DD")
    amf_import.add_argument("--end", help="exclusive UTC date, YYYY-MM-DD")
    amf_import.add_argument("--observations-dir", type=Path,
                            default=Path("data/standardized/ameriflux"))
    amf_import.add_argument("--flags-dir", type=Path, default=Path("data/flags/ameriflux"))
    amf_import.add_argument("--status-file", type=Path)
    amf_import.add_argument("--skip-existing", action="store_true")
    amf_import.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if args.command == "cell":
        print(grid_cell(args.latitude, args.longitude, args.resolution).cell_id)
    elif args.command == "index-ismn":
        files, issues = scan_ismn(args.root)
        pairs = pair_ismn(files)
        write_ismn_inventory(args.root, args.output_dir, pairs, issues)
        print(f"Indexed {sum(pair.temperature is not None for pair in pairs)} northern "
              f"temperature sensors; {len(issues)} scan issues")
    elif args.command == "index-ameriflux":
        archives, issues = scan_ameriflux(args.root)
        heights = read_measurement_heights(args.height_file)
        write_ameriflux_inventory(args.output_dir, archives, heights, issues)
        northern = [item for item in archives if item.latitude >= 0 and item.temperature_columns]
        print(f"Indexed {len(northern)} northern AmeriFlux sites and "
              f"{sum(len(item.temperature_columns) for item in northern)} temperature streams; "
              f"{len(issues)} scan issues")
    elif args.command == "import-ameriflux":
        if args.workers <= 0 or args.max_sites is not None and args.max_sites <= 0:
            raise ValueError("workers and max-sites must be positive")
        for value in (args.start, args.end):
            if value is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("start and end must be UTC dates, YYYY-MM-DD")
        start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc) if args.start else None
        end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc) if args.end else None
        if start is not None and end is not None and start >= end:
            raise ValueError("start must precede end")
        archives, issues = scan_ameriflux(args.root)
        if issues:
            raise ValueError(f"{len(issues)} AmeriFlux archives could not be indexed")
        heights = read_measurement_heights(args.height_file)
        archives = [item for item in archives if item.latitude >= 0 and item.temperature_columns
                    and (args.site is None or item.site_code == args.site)]
        if args.max_sites is not None:
            archives = archives[:args.max_sites]
        tasks = ((archive, pair_ameriflux(archive, heights), args.observations_dir,
                  args.flags_dir, start, end, args.skip_existing) for archive in archives)
        imported = skipped = failed = no_data = rows = 0
        if args.status_file:
            args.status_file.parent.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            log = stack.enter_context(args.status_file.open("a", newline="", encoding="utf-8")
                                      if args.status_file else open("/dev/null", "w"))
            writer = csv.writer(log)
            if args.status_file and log.tell() == 0:
                writer.writerow(("site_code", "status", "sensor_hourly_rows", "detail"))
            if args.workers == 1:
                results = map(_import_ameriflux_task, tasks)
            else:
                pool = stack.enter_context(ProcessPoolExecutor(max_workers=args.workers))
                results = pool.map(_import_ameriflux_task, tasks)
            for number, (archive, (status, count, detail)) in enumerate(zip(archives, results), 1):
                imported += status == "imported"
                skipped += status == "skipped_existing"
                failed += status == "error"
                no_data += status == "no_data"
                rows += count
                if args.status_file:
                    writer.writerow((archive.site_code, status, count, detail))
                    log.flush()
                if number % 20 == 0 or number == len(archives):
                    print(f"Processed {number}/{len(archives)} AmeriFlux sites: "
                          f"{imported} imported, {skipped} skipped, "
                          f"{no_data} no data, {failed} errors", flush=True)
        print(f"Imported {imported} sites and {rows} sensor-hour rows; "
              f"{skipped} skipped, {no_data} no data, {failed} errors")
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
        if args.workers <= 0:
            raise ValueError("workers must be positive")
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
        skipped = 0
        failed = 0
        if args.status_file:
            args.status_file.parent.mkdir(parents=True, exist_ok=True)
        tasks = ((pair, start, end, args.observations_dir, args.flags_dir,
                  args.skip_existing) for pair in pairs)
        with ExitStack() as stack:
            log = stack.enter_context(args.status_file.open("a", newline="", encoding="utf-8")
                                      if args.status_file else open("/dev/null", "w"))
            writer = csv.writer(log)
            if args.status_file and log.tell() == 0:
                writer.writerow(("sensor_id", "status", "hourly_rows", "detail"))
            if args.workers == 1:
                results = map(_import_ismn_task, tasks)
            else:
                pool = stack.enter_context(ProcessPoolExecutor(max_workers=args.workers))
                results = pool.map(_import_ismn_task, tasks)
            for number, (pair, (status, count, detail)) in enumerate(zip(pairs, results), 1):
                imported += status == "imported"
                skipped += status == "skipped_existing"
                failed += status == "error"
                rows += count
                if args.status_file:
                    writer.writerow((pair.sensor_id, status, count, detail))
                    log.flush()
                if number % 100 == 0 or number == len(pairs):
                    print(f"Processed {number}/{len(pairs)} sensors: "
                          f"{imported} imported, {skipped} skipped, {failed} errors",
                          flush=True)
        print(f"Imported {imported} sensors and {rows} hourly rows; "
              f"{skipped} skipped, {failed} errors")
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
