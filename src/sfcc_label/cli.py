"""Small command-line entry points for stage-one validation and grid lookup."""

import argparse
import csv
import os
import re
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from zipfile import BadZipFile

from .ameriflux import (import_ameriflux_site, pair_ameriflux,
                        read_measurement_heights, scan_ameriflux,
                        write_ameriflux_inventory)
from .grid import GRID_NAMES, RESOLUTIONS, grid_cell, write_sensor_grid_cells
from .io import load_metadata, read_observations
from .ismn import (import_ismn_pair, pair_ismn, scan_ismn,
                   write_ismn_inventory)
from .local import import_local
from .nrcan_ibutton import import_nrcan_ibutton
from .cambridge_bay import import_cambridge_bay
from .dryden import import_dryden
from .chapleau import import_chapleau
from .st_marthe_maurice import import_st_marthe_maurice
from .soilgrids import fetch_soilgrids, match_sensors
from .landcover_cci import aggregate_cci, sensor_landcover
from .ibutton_transects import import_ibutton_transect
from .berms import import_berms
from .tvc_boike import import_tvc_boike
from .tvc_hydraprobe import import_tvc_hydraprobe
from .time_qc import (benchmark_standardized_solar, load_level0_profiles,
                      read_local_sites, screen_site_years, write_time_report)

# Private data volume; override with SFCC_DATA_ROOT. Keeps importer output out of the repo.
DATA_ROOT = Path(os.environ.get("SFCC_DATA_ROOT", "/Volumes/Expansion/sfcc-label-data"))
CCI_SOURCE = DATA_ROOT / "sources/esa_cci_lc/ESACCI-LC-L4-LCCS-Map-300m-P1Y-2015-v2.0.7.tif"


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
    cell.add_argument("--resolution", choices=(*RESOLUTIONS, *GRID_NAMES), default="9km",
                      help="bare resolution = Northern Hemisphere grid; prefix M for global")
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
                          default=DATA_ROOT / "standardized/ismn")
    importer.add_argument("--flags-dir", type=Path, default=DATA_ROOT / "flags/ismn")
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
                            default=DATA_ROOT / "standardized/ameriflux")
    amf_import.add_argument("--flags-dir", type=Path, default=DATA_ROOT / "flags/ameriflux")
    amf_import.add_argument("--status-file", type=Path)
    amf_import.add_argument("--skip-existing", action="store_true")
    amf_import.add_argument("--workers", type=int, default=1)
    time_screen = subparsers.add_parser(
        "screen-time-utc", help="screen local level-0 timestamps without changing them")
    time_screen.add_argument("input_dir", type=Path,
                             help="directory of local level-0 network CSV files")
    time_screen.add_argument("--metadata", required=True, type=Path,
                             help="local metadata_soil_added.csv")
    time_screen.add_argument("--biome-file", type=Path,
                             help="optional local meta.csv for like-biome neighbors")
    time_screen.add_argument("--output", required=True, type=Path,
                             help="new per-site-year screening CSV; never overwritten")
    time_screen.add_argument("--radius-km", type=float, default=100)
    time_screen.add_argument("--minimum-days", type=int, default=20)
    benchmark = subparsers.add_parser(
        "benchmark-solar-utc", help="benchmark the shallow solar screen on standardized UTC streams")
    benchmark.add_argument("metadata", type=Path)
    benchmark.add_argument("observations_dir", type=Path)
    benchmark.add_argument("--output", required=True, type=Path)
    benchmark.add_argument("--minimum-days", type=int, default=20)
    benchmark.add_argument("--max-sensors", type=int)
    local_import = subparsers.add_parser(
        "import-local", help="split local level-0 network tables into hourly UTC site files")
    local_import.add_argument("input_dir", type=Path)
    local_import.add_argument("--metadata", required=True, type=Path)
    local_import.add_argument("--observations-dir", type=Path,
                              default=DATA_ROOT / "standardized/local")
    local_import.add_argument("--sensors-file", type=Path,
                              default=DATA_ROOT / "metadata/local_sensors.csv")
    local_import.add_argument("--status-file", type=Path,
                              default=DATA_ROOT / "metadata/local_import_status.csv")
    local_import.add_argument("--skip-conflicting-sites", action="store_true",
                              help="leave sites with conflicting same-timestamp values out of the output")
    ibutton_import = subparsers.add_parser(
        "import-nrcan-ibutton", help="import original NRCan Open File 66 iButton records")
    ibutton_import.add_argument("package_root", type=Path)
    ibutton_import.add_argument("--observations-dir", required=True, type=Path)
    ibutton_import.add_argument("--sensors-file", required=True, type=Path)
    ibutton_import.add_argument("--context-file", required=True, type=Path)
    ibutton_import.add_argument("--status-file", required=True, type=Path)
    cambridge_import = subparsers.add_parser(
        "import-cambridge-bay", help="import depth-specific Cambridge Bay iButton records")
    cambridge_import.add_argument("source_root", type=Path)
    cambridge_import.add_argument("--observations-dir", required=True, type=Path)
    cambridge_import.add_argument("--sensors-file", required=True, type=Path)
    cambridge_import.add_argument("--context-file", required=True, type=Path)
    cambridge_import.add_argument("--status-file", required=True, type=Path)
    dryden_import = subparsers.add_parser(
        "import-dryden", help="import original Dryden temperature workbook with resolved depths")
    dryden_import.add_argument("workbook", type=Path)
    dryden_import.add_argument("--source-6-depth", required=True, type=float)
    dryden_import.add_argument("--source-18-depth", required=True, type=float)
    dryden_import.add_argument("--source-30-depth", required=True, type=float)
    dryden_import.add_argument("--depth-evidence", required=True,
                               help="reference or owner confirmation for the assigned depths")
    dryden_import.add_argument("--observations-dir", required=True, type=Path)
    dryden_import.add_argument("--sensors-file", required=True, type=Path)
    dryden_import.add_argument("--context-file", required=True, type=Path)
    dryden_import.add_argument("--status-file", required=True, type=Path)
    chapleau_import = subparsers.add_parser(
        "import-chapleau", help="import original Chapleau temperature and Chelene moisture probes")
    chapleau_import.add_argument("chelene_dir", type=Path)
    chapleau_import.add_argument("--temperature-workbook", required=True, type=Path)
    chapleau_import.add_argument("--aspen-latitude", required=True, type=float)
    chapleau_import.add_argument("--aspen-longitude", required=True, type=float)
    chapleau_import.add_argument("--aspen-coordinate-evidence", required=True)
    chapleau_import.add_argument("--observations-dir", required=True, type=Path)
    chapleau_import.add_argument("--sensors-file", required=True, type=Path)
    chapleau_import.add_argument("--context-file", required=True, type=Path)
    chapleau_import.add_argument("--status-file", required=True, type=Path)
    st_import = subparsers.add_parser(
        "import-st-marthe-maurice", help="import original plot/pit temperatures at 2 and 10 cm")
    st_import.add_argument("source_dir", type=Path)
    st_import.add_argument("--observations-dir", required=True, type=Path)
    st_import.add_argument("--sensors-file", required=True, type=Path)
    st_import.add_argument("--context-file", required=True, type=Path)
    transect_import = subparsers.add_parser(
        "import-ibutton-transect",
        help="import 0/5 cm iButton transects: BJ (James Bay), FM (Montmorency), KJ (Kuujjuarapik)")
    transect_import.add_argument("submission_dir", type=Path)
    transect_import.add_argument("--network", required=True, choices=("BJ", "FM", "KJ"))
    transect_import.add_argument("--observations-dir", required=True, type=Path)
    transect_import.add_argument("--sensors-file", required=True, type=Path)
    transect_import.add_argument("--context-file", required=True, type=Path)
    berms_import = subparsers.add_parser(
        "import-berms", help="import BERMS OBS/OJP temperature and moisture profiles")
    berms_import.add_argument("source_dir", type=Path)
    berms_import.add_argument("--observations-dir", required=True, type=Path)
    berms_import.add_argument("--sensors-file", required=True, type=Path)
    berms_import.add_argument("--context-file", required=True, type=Path)
    tvc_import = subparsers.add_parser(
        "import-tvc-boike", help="import PANGAEA Trail Valley Creek hourly soil profiles")
    tvc_import.add_argument("source_dir", type=Path,
                            help="directory containing Boike-etal_2020_TVCsoilYYYY.tab")
    tvc_import.add_argument("--observations-dir", required=True, type=Path)
    tvc_import.add_argument("--sensors-file", required=True, type=Path)
    tvc_import.add_argument("--context-file", required=True, type=Path)
    soil_fetch = subparsers.add_parser(
        "soilgrids-fetch", help="sample SoilGrids 2.0 rasters at every catalog location")
    soil_fetch.add_argument("--catalog", type=Path, default=DATA_ROOT / "metadata/catalog.csv")
    soil_fetch.add_argument("--output", type=Path, default=DATA_ROOT / "metadata/soilgrids_points.csv")
    soil_fetch.add_argument("--cache-dir", type=Path, default=DATA_ROOT / "cache/soilgrids")
    soil_fetch.add_argument("--workers", type=int, default=12)
    soil_fetch.add_argument("--limit", type=int, help="sample only this many spread-out locations (pilot)")
    soil_match = subparsers.add_parser(
        "soilgrids-match", help="match SoilGrids layers to sensor depth, one row per sensor")
    soil_match.add_argument("--catalog", type=Path, default=DATA_ROOT / "metadata/catalog.csv")
    soil_match.add_argument("--points", type=Path, default=DATA_ROOT / "metadata/soilgrids_points.csv")
    soil_match.add_argument("--output", type=Path, default=DATA_ROOT / "metadata/sensor_soil.csv")
    cells = subparsers.add_parser(
        "grid-cells", help="cell id of every sensor on all ten EASE-2 grids")
    cells.add_argument("--catalog", type=Path, default=DATA_ROOT / "metadata/catalog.csv")
    cells.add_argument("--output", type=Path, default=DATA_ROOT / "metadata/sensor_grid_cells.csv")
    cci_grids = subparsers.add_parser(
        "landcover-cci-grids", help="ESA CCI land cover on all N and M EASE-2 grids (6 SMOS classes)")
    cci_grids.add_argument("--source", type=Path, default=CCI_SOURCE)
    cci_grids.add_argument("--output-dir", type=Path, default=DATA_ROOT / "landcover")
    cci_grids.add_argument("--year", type=int, default=2015)
    cci_sensors = subparsers.add_parser(
        "landcover-cci-sensors", help="per-sensor CCI class and its cell classes on every grid")
    cci_sensors.add_argument("--catalog", type=Path, default=DATA_ROOT / "metadata/catalog.csv")
    cci_sensors.add_argument("--source", type=Path, default=CCI_SOURCE)
    cci_sensors.add_argument("--grid-dir", type=Path, default=DATA_ROOT / "landcover")
    cci_sensors.add_argument("--output", type=Path, default=DATA_ROOT / "metadata/sensor_landcover_cci.csv")
    cci_sensors.add_argument("--year", type=int, default=2015)
    tvc_hp_import = subparsers.add_parser(
        "import-tvc-hydraprobe", help="import TVC HydraProbe multi-depth workbooks")
    tvc_hp_import.add_argument("source_dir", type=Path)
    tvc_hp_import.add_argument("--observations-dir", required=True, type=Path)
    tvc_hp_import.add_argument("--sensors-file", required=True, type=Path)
    tvc_hp_import.add_argument("--context-file", required=True, type=Path)
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
    elif args.command == "screen-time-utc":
        if args.radius_km <= 0 or args.minimum_days <= 0:
            raise ValueError("radius-km and minimum-days must be positive")
        if args.output.exists():
            raise FileExistsError(args.output)
        sites = read_local_sites(args.metadata, args.biome_file)
        profiles, counts = load_level0_profiles(args.input_dir, sites)
        rows = screen_site_years(sites, profiles, counts, args.radius_km, args.minimum_days)
        write_time_report(args.output, rows)
        from collections import Counter
        summary = Counter(row["timestamp_status"] for row in rows)
        print(f"Screened {len(rows)} site-years: {dict(sorted(summary.items()))}. "
              f"Report: {args.output}")
    elif args.command == "benchmark-solar-utc":
        if args.minimum_days <= 0 or args.max_sensors is not None and args.max_sensors <= 0:
            raise ValueError("minimum-days and max-sensors must be positive")
        summary = benchmark_standardized_solar(
            args.metadata, args.observations_dir, args.output,
            args.minimum_days, args.max_sensors)
        print(f"Solar benchmark: {dict(sorted(summary.items()))}. Report: {args.output}")
    elif args.command == "import-local":
        rows = import_local(args.input_dir, args.metadata, args.observations_dir,
                            args.sensors_file, args.status_file, args.skip_conflicting_sites)
        imported = [row for row in rows if row["status"] == "imported"]
        print(f"Imported {len(imported)} local sites and "
              f"{sum(row['output_hours'] for row in imported)} hourly rows; "
              f"{len(rows) - len(imported)} conflicting sites skipped. "
              f"Observations: {args.observations_dir}; metadata: {args.sensors_file}")
    elif args.command == "import-nrcan-ibutton":
        rows = import_nrcan_ibutton(args.package_root, args.observations_dir,
                                    args.sensors_file, args.context_file,
                                    args.status_file)
        print(f"Imported {len(rows)} original NRCan iButton streams and "
              f"{sum(row['output_hours'] for row in rows)} hourly slots. "
              f"Observations: {args.observations_dir}; metadata: {args.sensors_file}")
    elif args.command == "import-cambridge-bay":
        rows = import_cambridge_bay(args.source_root, args.observations_dir,
                                    args.sensors_file, args.context_file,
                                    args.status_file)
        imported = [row for row in rows if row["status"] == "imported"]
        print(f"Imported {len(imported)} Cambridge Bay site-depth streams; "
              f"{len(rows) - len(imported)} excluded without coordinates. "
              f"Observations: {args.observations_dir}; metadata: {args.sensors_file}")
    elif args.command == "import-dryden":
        rows = import_dryden(
            args.workbook, args.observations_dir, args.sensors_file, args.context_file,
            args.status_file, {6: args.source_6_depth, 18: args.source_18_depth,
                               30: args.source_30_depth}, args.depth_evidence)
        print(f"Imported {len(rows)} Dryden temperature streams and "
              f"{sum(row['output_hours'] for row in rows)} hourly slots. "
              f"Observations: {args.observations_dir}; metadata: {args.sensors_file}")
    elif args.command == "import-chapleau":
        rows = import_chapleau(
            args.chelene_dir, args.temperature_workbook, args.observations_dir,
            args.sensors_file, args.context_file, args.status_file,
            args.aspen_latitude, args.aspen_longitude, args.aspen_coordinate_evidence)
        print(f"Imported {len(rows)} Chapleau streams: 12 temperatures and 48 moisture probes. "
              f"Observations: {args.observations_dir}; metadata: {args.sensors_file}")
    elif args.command == "import-st-marthe-maurice":
        rows = import_st_marthe_maurice(args.source_dir, args.observations_dir,
                                        args.sensors_file, args.context_file)
        print(f"Imported {len(rows)} St-Marthe/Maurice pit-depth temperatures")
    elif args.command == "import-ibutton-transect":
        rows = import_ibutton_transect(args.submission_dir, args.network,
                                       args.observations_dir, args.sensors_file,
                                       args.context_file)
        print(f"Imported {len(rows)} {args.network} iButton depth-specific temperatures")
    elif args.command == "import-berms":
        rows = import_berms(args.source_dir, args.observations_dir,
                            args.sensors_file, args.context_file)
        print(f"Imported {len(rows)} BERMS depth-specific temperature/moisture streams")
    elif args.command == "import-tvc-boike":
        rows = import_tvc_boike(args.source_dir, args.observations_dir,
                                args.sensors_file, args.context_file)
        print(f"Imported {len(rows)} Trail Valley Creek PANGAEA streams")
    elif args.command == "import-tvc-hydraprobe":
        rows = import_tvc_hydraprobe(args.source_dir, args.observations_dir,
                                      args.sensors_file, args.context_file)
        print(f"Imported {len(rows)} Trail Valley Creek HydraProbe streams")
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
    elif args.command == "grid-cells":
        occupied = write_sensor_grid_cells(args.catalog, args.output)
        print(f"Wrote {args.output}")
        for column, count in occupied.items():
            print(f"{column}: {count} cells hold at least one sensor")
    elif args.command == "landcover-cci-grids":
        for path in aggregate_cci(args.source, args.output_dir, args.year,
                                  progress=lambda message: print(message, flush=True)):
            print(path)
    elif args.command == "landcover-cci-sensors":
        rows = sensor_landcover(args.catalog, args.source, args.grid_dir, args.output, args.year)
        print(f"Wrote {rows} sensor-grid rows to {args.output}")
    elif args.command == "soilgrids-fetch":
        points = fetch_soilgrids(args.catalog, args.output, args.cache_dir, args.workers, args.limit,
                                 progress=lambda message: print(message, flush=True))
        print(f"Sampled {points} locations; wrote {args.output}")
    elif args.command == "soilgrids-match":
        summary = match_sensors(args.catalog, args.points, args.output)
        print(f"Wrote {args.output}: {summary}")
    else:
        sensors = load_metadata(args.metadata)
        for sensor_id in sensors:
            path = args.observations_dir / f"{sensor_id}.csv"
            hours = read_observations(path)
            print(f"{sensor_id}: {len(hours)} hourly rows")
        extras = sorted(path.name for path in args.observations_dir.glob("*.csv")
                        if not path.name.startswith("._") and path.stem not in sensors)
        if extras:
            raise ValueError(f"observation files without metadata: {', '.join(extras)}")
        print(f"Validated {len(sensors)} sensors")


if __name__ == "__main__":
    main()
