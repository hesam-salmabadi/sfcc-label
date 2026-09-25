"""Small command-line entry points for stage-one validation and grid lookup."""

import argparse
from pathlib import Path

from .grid import grid_cell
from .io import load_metadata, read_observations


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
    args = parser.parse_args()
    if args.command == "cell":
        print(grid_cell(args.latitude, args.longitude, args.resolution).cell_id)
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
