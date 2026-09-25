# sfcc-label

A Python package skeleton for turning in situ soil observations into probabilistic frozen / transition / thawed labels, then querying those results on a standard EASE-Grid 2.0 grid.

The project has three stages:

1. **Prepare data:** harmonize ISMN, AmeriFlux, and locally collected records into one metadata table and one hourly CSV per sensor.
2. **Classify:** use a future, versioned processor to produce per-hour class probabilities and yearly freeze onset / freeze end dates. The scientific algorithm has not yet been specified, so this stage deliberately raises `NotImplementedError`.
3. **Serve gridded results:** map stations to Northern Hemisphere EASE-Grid 2.0 cells, summarize sampled states by cell and hour, and query the resulting records. A full-coverage product would require a separate spatial model.

See [WORKFLOW.md](WORKFLOW.md) for the end-to-end project plan and the decisions still needed.

## Installation

```bash
python -m pip install -e '.[test]'
python -m pytest
```

Install the optional raster tools with `python -m pip install -e '.[test,geo]'` when preparing MODIS land cover.

## Data contract

`metadata/sensors.csv` has one row per **depth-specific observation stream** (a temperature sensor optionally paired with moisture), not merely per site. Required fields:

| Column | Meaning |
| --- | --- |
| `sensor_id` | Stable, unique, file-safe identifier, such as `ismn_network_station_5cm` |
| `source` | `ismn`, `ameriflux`, or `local` |
| `latitude`, `longitude` | WGS84 decimal degrees |
| `site_id`, `network`, `station` | Site identity and original network/station names when known |
| `depth_cm` | Measurement depth below surface, if known; otherwise `NaN` |
| `depth_from_cm`, `depth_to_cm` | Original measurement interval; equal for a point sensor |
| `raw_variable`, `raw_unit` | Native sensor signal name and unit; use `NaN` when unavailable |
| `source_id`, `source_url` | Original station identifier and provenance link |
| `timezone_original` | Original time zone, if known; standardized times are always UTC |
| `soil_moisture_method` | Original conversion or calibration description, if known |
| `land_cover`, `land_cover_source`, `modeled_soil_variable`, `modeled_soil_value`, `modeled_soil_unit`, `modeled_soil_source` | Optional general enrichment with source and meaning kept alongside the value |

Annual MODIS 500 m land cover is stored separately in `metadata/sensor_landcover.csv` as `sensor_id,year,igbp_class,product,collection`; one sensor can have a different class in different years. It uses the `LC_Type1` IGBP legend from MCD12Q1 Collection 6.1. The table is empty until source rasters and sensor coordinates are supplied. The general `land_cover` field in `sensors.csv` is not used for the representativeness gate.

`data/standardized/<sensor_id>.csv` contains exactly these columns:

```csv
timestamp_utc,soil_temperature_c,soil_moisture_m3_m3,raw_value
2024-01-01T00:00:00Z,-1.2,NaN,8321
2024-01-01T01:00:00Z,-1.1,NaN,8324
```

Each timestamp marks an hourly UTC slot. Use literal `NaN` for unavailable measurements; do not interpret missing soil moisture as zero. A missing hour can be represented by an all-`NaN` row. Retain source files separately for traceability. The raw value has no global unit; `raw_variable` and `raw_unit` in metadata define it for each sensor. A sensor can have no soil moisture series at all.

The CSV retains finite source values even when they fall outside a physical range. QA/QC can later use the source flags to accept, mask, or investigate them. This avoids silently discarding flagged anomalies during harmonization.

## ISMN header+values import

The importer reads the ISMN `Data_separate_files_header_...` export. ISMN already [harmonizes UTC timestamps and volumetric soil-moisture units](https://ismn.earth/data/harmonization/). The current step joins `ts` and `sm` at identical UTC hours and copies values without a new QA/QC decision. ISMN and provider flags go into `data/flags/ismn/<sensor_id>.csv.gz`, aligned with the four-column observation CSV; the raw sensor-output column is `NaN` because this ISMN export does not contain frequency/count/permittivity measurements.

```bash
sfcc-label index-ismn /path/to/ISMN-export
sfcc-label import-ismn /path/to/ISMN-export \
  --start 2010-01-01 --end 2026-07-21 \
  --observations-dir /path/to/private-data/standardized/ismn \
  --flags-dir /path/to/private-data/flags/ismn \
  --status-file /path/to/private-data/metadata/ismn_import_status.csv \
  --skip-existing --workers 4
```

`index-ismn` reads filenames and headers, then creates local-only `metadata/private/ismn_sites.csv`, `ismn_sensors.csv`, `ismn_pairing.csv`, and `ismn_scan_issues.csv`. Every metadata sensor has a below-ground soil-temperature stream; moisture-only streams remain visible in the pairing report but are not imported as standalone classifier inputs. Coordinates come from ISMN file headers. Distinct instrument replacements and redundant probes keep distinct sensor IDs. A logical record can pair two physical instruments. Pairing uses the same instrument/position first, then a unique position match, then a unique pair at the same exact depth bounds. Ambiguous unmatched temperature streams remain temperature-only. The pairing report contains the original relative file paths and method for review. The supplied ISMN export also includes a `FLUXNET-AMERIFLUX` network; a later direct AmeriFlux import will need duplicate-site checks.

`import-ismn` writes one CSV per selected sensor to the chosen observations directory and keeps the original flags in compressed sidecars. `--start` is inclusive and `--end` exclusive. It fills missing hours with `NaN` between the first and last available hour in the requested window. Existing outputs are not overwritten. `--skip-existing` makes interrupted batches resumable; the optional status CSV records each sensor's outcome. `--workers` parallelizes independent sensor imports. Use a separate private data volume for the full export rather than the repository disk. A sensor with no observations in the requested window is logged as `no_data` and has no output CSV.

The inspected export indexed **1,728 northern sites and 11,774 temperature-bearing sensors**. Three negative-depth files were explicitly excluded and recorded. Local data tables and observations are Git-ignored. [ISMN terms](https://ismn.earth/terms-and-conditions) prohibit onward distribution of downloaded data, so the public repository contains importer code and schema, not ISMN-derived records. Cite both ISMN and contributing networks in scientific outputs.

`data/processed/<sensor_id>.csv`, when the processor is implemented, will contain `timestamp_utc,p_frozen,p_transition,p_thawed,label,model_version`. The three probabilities must be finite, within `[0, 1]`, and sum to one (within tolerance). `label` is the highest probability class; ties use the class order frozen, transition, thawed. An unknown hour should have three `NaN` probabilities and an empty label, rather than a fabricated prediction. Annual events will be stored separately with `sensor_id,year,freeze_start_utc,freeze_end_utc,model_version` and definitions supplied with the algorithm. A year is a UTC calendar year until the event definition is specified.

## Current API

```python
from sfcc_label import load_metadata, read_observations, grid_cell, aggregate_probabilities

stations = load_metadata("metadata/sensors.csv")
hours = read_observations("data/standardized/example_sensor.csv")
cell = grid_cell(stations["example_sensor"].latitude,
                 stations["example_sensor"].longitude, resolution="9km")
```

`aggregate_probabilities(predictions, stations, screens, resolution="9km")` reports per-cell/hour sensor label counts, label shares, the **unweighted mean of sensor probability vectors**, and `sensor_count`. The `screens` argument is required: only sensors whose annual 500 m MODIS IGBP class exactly matches their EASE cell's dominant IGBP class enter the summary. Missing classes or screening records exclude the sensor; observations are retained. These summaries describe sampled locations, not cell-wide state probabilities or area fractions. There is no single grid-cell label. The query helper `get_processed_data(...)` filters these in-memory rows by UTC interval and optional cell IDs. No online data service or native ISMN/AmeriFlux downloader is implemented yet.

`aggregate_yearly_events(events, stations, screens, resolution="9km")` applies the same land-cover gate, then summarizes supplied per-sensor freeze-start and freeze-end dates separately with the median, earliest, latest, and number of contributing sensors. Filter to comparable sensor depths before calling it. The package does not yet infer those dates from hourly data.

## MODIS land-cover preparation

Prepare a georeferenced, **one-band** raster or VRT mosaic of MCD12Q1.061 `LC_Type1` (IGBP classes, nominally 500 m) for each requested year. The command samples each sensor's native pixel and creates dominant-class grids at both supported EASE-Grid resolutions using categorical mode resampling:

```bash
sfcc-label prepare-landcover 2020 data/raw/MCD12Q1_2020_LC_Type1.vrt
```

Outputs are `metadata/sensor_landcover.csv`, `metadata/landcover_screen.csv`, and `data/landcover/ease2_n_{9km,25km}_2020.tif`. The screening table records the sensor class, cell class, match decision, and exclusion reason by year and resolution. Run once per year; the command refuses to overwrite an existing year. It expects a complete, correctly identified source mosaic and does not download MODIS granules or apply the product QA layer yet. A missing or invalid IGBP class is excluded from aggregation, never treated as a match. Source tiles and generated rasters are not committed.

The cited [SMOS study](https://essd.copernicus.org/articles/17/5337/2025/) used ESA CCI land cover at 300 m and a more involved representativeness test. This project follows the requested MODIS 500 m exact-class rule. The [MODIS Collection 6.1 guide](https://lpdaac.usgs.gov/documents/1409/MCD12_User_Guide_V61.pdf) documents the annual IGBP layer and its codes.

```bash
sfcc-label validate metadata/sensors.csv data/standardized
sfcc-label cell 45.5 -73.6 --resolution 9km
```

## Design notes and next decisions

- Native source adapters should preserve source license, station version, timezone conversion, quality flags, depth, calibration, and citations. The normalized schema is an output contract; source-specific mapping rules still need real example files.
- Probability model inputs may include temperature, moisture, raw frequency/count, permittivity, and time response. The first two standardized measurement columns are stable; additional raw channels need an extension schema before they are ingested.
- Decide whether freeze dates are defined by UTC calendar year, hydrological year, or cold season, and how multiple freeze/thaw cycles are handled.
- Decide minimum sensor coverage, missing-data handling, confidence calibration, and validation split across stations/sites/years before publishing scientific labels.
- The default grid is NSIDC EASE-Grid 2.0 Northern Hemisphere 9 km (EPSG:6931, 2,000 columns × 2,000 rows). A northern 25 km option is also available. Cell IDs include the grid name and zero-based row and column so resolutions cannot be mixed.

Grid dimensions and origins follow the [NSIDC EASE-Grid guide](https://nsidc.org/data/user-resources/help-center/guide-ease-grids). ISMN and AmeriFlux are named as planned sources, with no data mirrored in this repository.

## Repository layout

```text
metadata/sensors.csv          sensor registry and optional enrichment
metadata/private/             local ISMN site/sensor/pairing tables (ignored)
metadata/sensor_landcover.csv annual 500 m MODIS class per sensor
metadata/landcover_screen.csv annual sensor-to-cell match audit
data/raw/                     original source files (ignored)
data/standardized/            one hourly CSV per sensor (ignored)
data/flags/                   source quality-flag sidecars (ignored)
data/processed/               model output (ignored)
data/landcover/               yearly 9 km and 25 km EASE rasters (ignored)
src/sfcc_label/               data contract, grid, aggregation, CLI
tests/                        contract and grid checks
```
