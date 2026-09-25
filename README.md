# sfcc-label

A Python package skeleton for turning in situ soil observations into probabilistic frozen / transition / thawed labels, then querying those results on a standard EASE-Grid 2.0 grid.

The project has three stages:

1. **Prepare data:** harmonize ISMN, AmeriFlux, and locally collected records into one metadata table and one hourly CSV per sensor.
2. **Classify:** use a future, versioned processor to produce per-hour class probabilities and yearly freeze onset / freeze end dates. The scientific algorithm has not yet been specified, so this stage deliberately raises `NotImplementedError`.
3. **Serve gridded results:** map stations to EASE-Grid 2.0 cells, aggregate available station probabilities by cell and hour, and query the resulting records. This stage accepts processed records supplied by a future processor.

See [WORKFLOW.md](WORKFLOW.md) for the end-to-end project plan and the decisions still needed.

## Installation

```bash
python -m pip install -e '.[test]'
python -m pytest
```

## Data contract

`metadata/sensors.csv` has one row per **sensor**, not merely per site. Required fields:

| Column | Meaning |
| --- | --- |
| `sensor_id` | Stable, unique, file-safe identifier, such as `ismn_network_station_5cm` |
| `source` | `ismn`, `ameriflux`, or `local` |
| `latitude`, `longitude` | WGS84 decimal degrees |
| `depth_cm` | Measurement depth below surface, if known; otherwise `NaN` |
| `raw_variable`, `raw_unit` | Native sensor signal name and unit; use `NaN` when unavailable |
| `source_id`, `source_url` | Original station identifier and provenance link |
| `timezone_original` | Original time zone, if known; standardized times are always UTC |
| `soil_moisture_method` | Original conversion or calibration description, if known |
| `land_cover`, `land_cover_source`, `modeled_soil_variable`, `modeled_soil_value`, `modeled_soil_unit`, `modeled_soil_source` | Optional enrichment with source and meaning kept alongside the value |

`data/standardized/<sensor_id>.csv` contains exactly these columns:

```csv
timestamp_utc,soil_temperature_c,soil_moisture_m3_m3,raw_value
2024-01-01T00:00:00Z,-1.2,NaN,8321
2024-01-01T01:00:00Z,-1.1,NaN,8324
```

Each timestamp marks an hourly UTC slot. Use literal `NaN` for unavailable measurements; do not interpret missing soil moisture as zero. A missing hour can be represented by an all-`NaN` row. Retain source files separately for traceability. The raw value has no global unit; `raw_variable` and `raw_unit` in metadata define it for each sensor. A sensor can have no soil moisture series at all.

`data/processed/<sensor_id>.csv`, when the processor is implemented, will contain `timestamp_utc,p_frozen,p_transition,p_thawed,label,model_version`. The three probabilities must be finite, within `[0, 1]`, and sum to one (within tolerance). `label` is the highest probability class; ties use the class order frozen, transition, thawed. An unknown hour should have three `NaN` probabilities and an empty label, rather than a fabricated prediction. Annual events will be stored separately with `sensor_id,year,freeze_start_utc,freeze_end_utc,model_version` and definitions supplied with the algorithm. A year is a UTC calendar year until the event definition is specified.

## Current API

```python
from sfcc_label import load_metadata, read_observations, grid_cell, aggregate_probabilities

stations = load_metadata("metadata/sensors.csv")
hours = read_observations("data/standardized/example_sensor.csv")
cell = grid_cell(stations["example_sensor"].latitude,
                 stations["example_sensor"].longitude, resolution="9km")
```

`aggregate_probabilities(predictions, stations, resolution="9km")` computes an **unweighted arithmetic mean** of available station probabilities for each cell and hour, and includes `station_count`. This is a provisional aggregation policy, not an area estimate or a spatial interpolation. Same-cell station readings are correlated, so the mean must not be interpreted as calibrated gridded uncertainty. The query helper `get_processed_data(...)` filters these in-memory rows by UTC interval and optional cell IDs. No online data service or native ISMN/AmeriFlux downloader is implemented yet.

```bash
sfcc-label validate metadata/sensors.csv data/standardized
sfcc-label cell 45.5 -73.6 --resolution 9km
```

## Design notes and next decisions

- Native source adapters should preserve source license, station version, timezone conversion, quality flags, depth, calibration, and citations. The normalized schema is an output contract; source-specific mapping rules still need real example files.
- Probability model inputs may include temperature, moisture, raw frequency/count, permittivity, and time response. The first two standardized measurement columns are stable; additional raw channels need an extension schema before they are ingested.
- Decide whether freeze dates are defined by UTC calendar year, hydrological year, or cold season, and how multiple freeze/thaw cycles are handled.
- Decide minimum sensor coverage, missing-data handling, confidence calibration, and validation split across stations/sites/years before publishing scientific labels.
- The default global grid is NSIDC EASE-Grid 2.0 9 km (EPSG:6933, 3856 columns × 1624 rows). A global 25 km option is also available. Cell IDs include the grid name and zero-based row and column so resolutions cannot be mixed.

Grid dimensions and origins follow the [NSIDC EASE-Grid guide](https://nsidc.org/data/user-resources/help-center/guide-ease-grids). ISMN and AmeriFlux are named as planned sources, with no data mirrored in this repository.

## Repository layout

```text
metadata/sensors.csv          sensor registry and optional enrichment
data/raw/                     original source files (ignored)
data/standardized/            one hourly CSV per sensor (ignored)
data/processed/               model output (ignored)
src/sfcc_label/               data contract, grid, aggregation, CLI
tests/                        contract and grid checks
```
