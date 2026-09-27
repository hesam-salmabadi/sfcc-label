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
| `sensor_id` | Stable, unique, file-safe identifier `<src>_<site>_<depth>_<tag>`, such as `berms_bs01_002p5cm_m` (see *Sensor naming*) |
| `source` | `ameriflux`, `berms`, `cambridge_bay`, `chapleau`, `dryden`, `ismn`, `james_bay`, `kuujjuarapik`, `local`, `montmorency`, `nrcan_ibutton`, `st_marthe_maurice`, `tvc_boike`, or `tvc_hydraprobe` |
| `latitude`, `longitude` | WGS84 decimal degrees |
| `site_id`, `network`, `station` | Site identity and original network/station names when known |
| `depth_cm` | Measurement depth below surface, if known; otherwise `NaN` |
| `depth_from_cm`, `depth_to_cm` | Original measurement interval; equal for a point sensor |
| `raw_variable`, `raw_unit` | Native sensor signal name and unit; use `NaN` when unavailable |
| `source_id`, `source_url` | Original station identifier and provenance link |
| `timezone_original` | Original time zone, if known; standardized times are always UTC |
| `soil_moisture_method` | Original conversion or calibration description, if known |
| `soil_temperature_sensor_type`, `soil_moisture_sensor_type` | Documented instrument family/model for each measurement; `NaN` when the source does not identify it |
| `sensor_type_source`, `sensor_type_note` | Evidence and qualification for the instrument-type fields |

Annual MODIS 500 m land cover is stored separately in `metadata/sensor_landcover.csv` as `sensor_id,year,igbp_class,product,collection`; one sensor can have a different class in different years. It uses the `LC_Type1` IGBP legend from MCD12Q1 Collection 6.1. The table is empty until source rasters and sensor coordinates are supplied. Site land cover and soil properties are not columns of the sensor metadata: ESA CCI land cover is in `metadata/sensor_landcover_cci.csv`, SoilGrids values in `metadata/sensor_soil.csv`, and grid cells in `metadata/sensor_grid_cells.csv`, all keyed by `sensor_id`.

The merged metadata catalog is `metadata/catalog.csv`. It has the same schema as
each source-specific `*_sensors.csv` file, so it can be loaded by the normal
metadata reader and used for maps, filtering, land-cover screening, and EASE-grid
aggregation. The source files remain authoritative and are not replaced by the
catalog. `metadata/catalog_manifest.csv` records the contributing file and row
count. Rebuild both files with `scripts/build_catalog.py` after an importer adds
or removes sensors.

### Sensor naming

Every `sensor_id` is also the file stem: `standardized/<source>/<sensor_id>.csv`
and, where present, `flags/<source>/<sensor_id>.csv.gz`. The folder name always
equals the `source` value. Ids are built by `sfcc_label.naming.sensor_id` and have
exactly four `_`-separated parts, each lowercase `a-z`, `0-9`, or `-`:

| Part | Rule | Examples |
| --- | --- | --- |
| src | short source code | `amf` ameriflux, `berms`, `cbay` cambridge_bay, `chap` chapleau, `dryden`, `ismn`, `jbay` james_bay, `kuuj` kuujjuarapik, `local`, `mont` montmorency, `nrcan` nrcan_ibutton, `smm` st_marthe_maurice, `tvcb` tvc_boike, `tvch` tvc_hydraprobe |
| site | site code; ISMN uses `network-station` | `bs01`, `ca-af1`, `arm-anthony` |
| depth | zero-padded cm; `p` for decimals; interval `top-bottom`; `nodepth` if unknown | `005cm`, `002p5cm`, `000-015cm`, `nodepth` |
| tag | separates sensors at one site and depth; `s1` if only one | `h1v1r1`, `pi1`, `pit2`, `p1a`, `t`, `m`, `mr`, `2018`, `hummock` |

`local` holds sensors from our own sites and network plus partner data that is
not publicly released. The 2026-09-27 rename from the earlier per-importer ids is
recorded in `metadata/sensor_id_map.csv` (old id, new id, old and new paths);
`scripts/rename_sensor_ids.py` produced it and pre-rename metadata is in
`archive/rename_20260927/metadata`.

`standardized/<source>/<sensor_id>.csv` contains exactly these columns:

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

## AmeriFlux BASE-BADM import

The independent AmeriFlux importer reads the downloaded BASE-BADM ZIP archives and their bundled site-metadata (BIF) workbooks. ISMN's [FLUXNET-AMERIFLUX contributor network](https://ismn.earth/en/networks/?id=FLUXNET-AMERIFLUX) is only a small subset of the direct AmeriFlux holdings, so the two sources remain separate with source-specific IDs. The importer uses AmeriFlux's [Measurement Height](https://ameriflux.lbl.gov/data/measurement-height/) table for actual sensor depths. AmeriFlux positional suffixes are relative indices, not depth measurements; the importer pairs TS and SWC only when exactly one of each has the same documented below-ground depth at a site. All other temperature streams remain temperature-only, with moisture `NaN`, and their depth evidence stays in the pairing report. Some BASE variables are aggregates or PI-provided series; retaining them does **not** make them independent sensors for later grid aggregation.

```bash
sfcc-label index-ameriflux /path/to/ameriflux_downloads \
  --height-file /path/to/private-data/metadata/BASE_MeasurementHeight_YYYYMMDD.csv \
  --output-dir /path/to/private-data/metadata
sfcc-label import-ameriflux /path/to/ameriflux_downloads \
  --height-file /path/to/private-data/metadata/BASE_MeasurementHeight_YYYYMMDD.csv \
  --observations-dir /path/to/private-data/standardized/ameriflux \
  --flags-dir /path/to/private-data/flags/ameriflux \
  --status-file /path/to/private-data/metadata/ameriflux_import_status.csv \
  --skip-existing --workers 4
```

BASE timestamps are [local standard time without daylight-saving shifts](https://ameriflux.lbl.gov/data/aboutdata/data-variables/); the importer applies each site's fixed BIF `UTC_OFFSET`. Half-hourly and hourly source intervals are converted to hourly UTC means using their valid-minute coverage. When both HH and HR files overlap, a valid HH observation takes precedence for that variable and hour. Soil temperature remains in °C; BASE [volumetric SWC is percent](https://ameriflux.lbl.gov/data/aboutdata/data-variables/) and is divided by 100 to become m³/m³. The source's `-9999` missing marker becomes `NaN`. A malformed numeric cell also becomes missing, with its count recorded in the per-site status log for review. No new anomaly QA/QC is applied. Per-sensor compressed sidecars record valid source minutes and original variable names; these are coverage/provenance records, not ISMN-style quality flags. The raw-output column is `NaN` because BASE TS/SWC are calibrated variables, not sensor frequency or permittivity. Use separate output directories for a date-limited pilot; `--skip-existing` does not verify that an existing file covers the same requested interval.

The inspected local download has 592 archives, 571 northern sites, and 484 northern sites with temperature columns. The BIF for 8 of those temperature sites has more than one reported coordinate; the inventory marks those locations as ambiguous, and they need review before land-cover screening or location-sensitive aggregation. AmeriFlux direct data and the official Measurement Height CSV stay on the private data volume, not in Git.

## Local level-0 import

`import-local` reads the supplied local network tables, splits their `site_id`
streams, and writes `local_<site_id>.csv` files using the four-column standard
observation schema. It also creates `local_sensors.csv` with coordinates,
depth, and `raw_variable=bulk_edc`, plus `local_import_status.csv` with
per-site row counts and coverage. CP01–CP04 have a 0–10 cm support interval
and 5 cm midpoint, as confirmed by the data owner. Unknown depths stay
unknown; the raw `bulk_edc` unit is not asserted without documentation.
NI/NT sites in the level-0 tables belong to the NRCan publisher collection and
are skipped here; `import-nrcan-ibutton` owns them. The `Alaska ISMN` and
`RISMA ISMN` level-0 networks are also skipped because their sites are present
in the direct ISMN import. Cambridge Bay is skipped because its dedicated
importer preserves distinct site-depth streams.

```bash
sfcc-label import-local /path/to/level_0 \
  --metadata /path/to/metadata_soil_added.csv \
  --observations-dir /path/to/private-data/standardized/local \
  --sensors-file /path/to/private-data/metadata/local_sensors.csv \
  --status-file /path/to/private-data/metadata/local_import_status.csv
```

Source timestamps are **treated as declared UTC**, with no timezone test or
conversion. Subhourly readings are averaged independently for temperature,
moisture, and `bulk_edc` within each UTC hour. Identical repeated timestamps
are counted once; conflicting nonmissing values at one timestamp stop the
import for review by default. Pass `--skip-conflicting-sites` to import the
unambiguous sites and list skipped sites in the status CSV. Output hours are
sorted, with `NaN` for missing values and
entirely missing hours. Source `9999` and `-9999` sentinels become `NaN`;
other finite values are retained without anomaly QA/QC. Existing outputs
are not overwritten. The level-0 tables remain untouched.

## Original NRCan iButton publisher import

`import-nrcan-ibutton` reads the original logger files and `Site_data.xlsx` from
[NRCan Open File 66](https://doi.org/10.4095/329207), independently of the
derived local level-0 tables. It writes one temperature-only hourly UTC CSV per
logger to a **separate** `standardized/nrcan_ibutton` directory. The source
records are nominally 255 minutes apart; an hour with no actual source sample
has `NaN`, and no interpolation or nearest-neighbor filling is performed.
Moisture and raw-output fields are `NaN`. Original logger records are retained
in the publisher package.

```bash
sfcc-label import-nrcan-ibutton /path/to/gid_329207 \
  --observations-dir /path/to/private-data/standardized/nrcan_ibutton \
  --sensors-file /path/to/private-data/metadata/nrcan_ibutton_sensors.csv \
  --context-file /path/to/private-data/metadata/nrcan_ibutton_site_context.csv \
  --status-file /path/to/private-data/metadata/nrcan_ibutton_import_status.csv
```

The publisher describes installation **13 cm below ground surface, measured
from the moss/lichen surface when present**. Consequently, `depth_cm` remains
13 cm below the local surface for every sensor. `Site_data.xlsx` supplies
`Top_Organic_Layer_Thickness(cm)` for the logger sites, but that field includes
moss/lichen **and** other organic material. Explicit moss/lichen thickness is
present in the soil-condition notes for only 17 of the 107 logger sites, so it
cannot support a consistent soil-surface-depth correction for the collection.
The separate site-context file retains total organic thickness and
`estimated_interface_offset_cm = 13 - organic_layer_cm`.
A negative offset estimates a logger within the organic layer; a positive
offset estimates depth into mineral soil. This is an approximate position
relative to the organic–mineral interface, **not** a replacement depth below
surface. The importer corrects two publisher filename/site-label mismatches:
`T18_DD_36BF0221.csv` belongs to T16 and `T36_7A_36CA7521.csv` belongs to
T35. It preserves the original filename and internal device registration in
the context and status tables. Local timestamps are converted from
`America/Toronto` to UTC, with ambiguous autumn DST times resolved against the
logger's 255-minute cadence. Existing output paths are never overwritten.

The older `local_NI*`/`local_NT*` level-0 derivatives and this publisher import
represent the same observations. The 103 former standardized files were moved
out of `standardized/local` into the recoverable private archive
`archive/local_nrcan_level0_20260926/observations`; the two additional NI/NT
level-0 sites previously lacked standardized files because of conflicting
duplicate records. The original level-0 tables remain untouched. The active
local metadata and import-status CSVs now exclude NI/NT; their pre-replacement
versions are preserved in the same archive.

The 49 `Alaska ISMN` and 18 `RISMA ISMN` local derivatives also matched direct
ISMN sites at the same coordinates. Every matched site had imported shallow
ISMN temperature data whose overall time span included its local span. Their
67 standardized CSVs were moved from `standardized/local` to the recoverable
private archive `archive/local_ismn_level0_20260926/observations`. That archive
retains the pre-removal local metadata/status and `match_manifest.csv` linking
each local site to its ISMN site. The original level-0 tables remain untouched.
The archived local files may carry `bulk_edc` values absent from the direct
ISMN standardized files; they remain available for provenance or later study,
but are no longer active aggregation inputs.

## Cambridge Bay depth-specific iButton import

`import-cambridge-bay` reads the curated per-logger files in the two Cambridge
Bay campaign folders, using `CB_ib_2018-2019/Metadata.xlsx` for the 16 site
locations and 2018 deployment depths. The sibling `Metadata.csv` has stale
IP11/IP12 button/depth entries and is not used. The importer keeps 2018-19 and
2019-20 deployments as separate sensor IDs, even at the same site and depth.
It writes 64 temperature-only hourly UTC files (47 older, 17 newer) to a
separate `standardized/cambridge_bay` folder. Source readings are three-hourly;
unsampled hours remain `NaN`, as do moisture and raw-output columns. The source
clock is **assumed UTC from prior processing, not independently verified**.

```bash
sfcc-label import-cambridge-bay /path/to/CambridgeBay \
  --observations-dir /path/to/private-data/standardized/cambridge_bay \
  --sensors-file /path/to/private-data/metadata/cambridge_bay_sensors.csv \
  --context-file /path/to/private-data/metadata/cambridge_bay_context.csv \
  --status-file /path/to/private-data/metadata/cambridge_bay_import_status.csv
```

The older campaign's recorded depths span 2-28 cm. Three deployments listed
in the workbook have no recovered temperature file: CB01 at 28 cm, CB07 at
29 cm, and CB15 at 30 cm. The newer file tags indicate nominal 0 and 5 cm;
the 2020 retrieval sheet labels seven of the eight nominal 0-cm loggers at
2 cm on retrieval. Both values are recorded separately in the context file;
the 0-cm tag should not be treated as a precisely constant soil depth. Two
EC-tower logger files are listed as `excluded_no_coordinates` in the status
file because the supplied deployment metadata does not locate that tower.

The nine former `local_CB*` files were byte-identical to their 2019-20 5-cm
publisher-source replacements. They were moved from `standardized/local` to
the recoverable private archive
`archive/local_cambridge_bay_level0_20260926/observations`, with the old
local metadata/status and a replacement manifest. The original source and
level-0 tables remain untouched.

## Dryden source audit and depth-specific importer

The original `Dryden_SoilTemp.xlsx` in the owner's OneDrive `data/raw/SoilTemp`
folder contains three hourly temperature streams (`Dryden_6`, `Dryden_18`,
`Dryden_30`) at one site. Its metadata declares UTC, °C, coordinates
49.868744, −92.604012, and sensor heights −6, −18, and −30 cm. Each stream
has 29,484 dated readings from 2019-07-24 17:00 through 2023-01-01 05:00 UTC.
Twelve additional rows per stream have `NA` timestamps and cannot be placed
on the time axis; the importer counts them in its status/context files.
`local_DD01` is a byte-identical copy of the `Dryden_6` hourly output.

The data owner confirmed that **6, 18, and 30 cm are the temperature-probe
depths**; the CFS `Soil_moisture_data_documentation.docx` in
`/Volumes/Expansion/UQAM/Chelene` lists separate Dryden moisture-probe
installation depths of 10, 14, and 18 cm, with four probes per depth. The
folder does not contain the Dryden moisture time series. The
[2023 Hanes et al. paper](https://doi.org/10.1071/WF22112)
reports those observations but says to contact the corresponding author
for access to its datasets; no open hourly Dryden moisture download has been
located. The imported temperature files therefore have `NaN` moisture and raw
outputs. Install `sfcc-label[source-excel]` for this workbook importer.

```bash
sfcc-label import-dryden /path/to/Dryden_SoilTemp.xlsx \
  --source-6-depth 6 --source-18-depth 18 --source-30-depth 30 \
  --depth-evidence 'owner confirmation 2026-09-26; workbook metadata' \
  --observations-dir /path/to/private-data/standardized/dryden \
  --sensors-file /path/to/private-data/metadata/dryden_sensors.csv \
  --context-file /path/to/private-data/metadata/dryden_context.csv \
  --status-file /path/to/private-data/metadata/dryden_import_status.csv
```

The production import wrote three streams to `standardized/dryden`, each with
30,157 hourly slots (29,484 measured hours), and passed schema validation.
After a byte-identical replacement check, `local_DD01` was moved to the
recoverable private archive `archive/local_dryden_level0_20260926/observations`.
The old active local metadata/status and match manifest are in that archive;
the original workbook and level-0 table were not changed. The local importer
excludes Dryden on future reruns.

## Chapleau temperature and moisture importer

`import-chapleau` uses the original OneDrive `data/raw/SoilTemp/Chapleau_SoilTemp.xlsx`
for 12 temperature streams (four plots × 6, 15, and 30 cm) and the four Chelene
plot workbooks for 48 distinct CS616 moisture probes (four per subplot at
subplots 1, 3, and 5). Each physical measurement has its own file in
`standardized/chapleau`: 12 temperature-only and 48 moisture-only streams.
There is **no forced same-depth pairing** between temperature depths and
moisture support intervals. The context CSV links each moisture probe to the
temperature sensor at its subplot as a nearby reference, not as an equivalent
measurement depth.

The CS616's 30 cm rods were inserted diagonally from the surface to an
installation depth of 10 or 18 cm. The metadata records support intervals
**0–10 and 0–18 cm**, with nominal midpoints **5 and 9 cm**, respectively;
those midpoints do not turn the integrated moisture measurement into a point
observation. Calibrated source VWC in percent is divided by 100 for m³/m³.
The `raw_value` is the uncorrected CS616 period in microseconds. The source's
temperature-corrected period and soil-profile calibration coefficients stay
in the original workbooks rather than being mislabeled as raw output.

The source temperature workbook declares UTC. Its timestamps include
`HH:59:59` and a few seconds after the hour; they are rounded to the nearest
UTC hour. The Chelene workbooks use Ontario local clock time, inferred from
matching their temperature columns to the UTC source. They are converted with
`America/Toronto`. Five ambiguous autumn clock-change rows per plot could not
be resolved uniquely and are not assigned an hour. One or five nonexistent
spring local-time rows per plot are likewise skipped. Counts are recorded in
`chapleau_context.csv` and `chapleau_import_status.csv`; no interpolation or
new anomaly QA/QC is applied.

The Aspen/AS3 workbooks report 47.738633, −83.40105, while the Chelene site
document and existing CP03 metadata report about 47.71472, −83.39722.
The import uses the latter documented site coordinates and records the
discrepancy in context for owner review. The other plot coordinates come from
the original temperature workbook.

```bash
sfcc-label import-chapleau /path/to/Chelene \
  --temperature-workbook /path/to/Chapleau_SoilTemp.xlsx \
  --aspen-latitude 47.71472 --aspen-longitude -83.39722 \
  --aspen-coordinate-evidence 'Chelene site document and existing CP03 metadata' \
  --observations-dir /path/to/private-data/standardized/chapleau \
  --sensors-file /path/to/private-data/metadata/chapleau_sensors.csv \
  --context-file /path/to/private-data/metadata/chapleau_context.csv \
  --status-file /path/to/private-data/metadata/chapleau_import_status.csv
```

The production import wrote 60 validated streams, including 1,758,361
measured moisture hours across the 48 probes. The four old `local_CP01`–
`local_CP04` files were byte-identical to their new 6 cm temperature-source
replacements and were moved to the recoverable private archive
`archive/local_chapleau_level0_20260926/observations`, along with a match
manifest and copies of the pre-removal local metadata/status. Original
workbooks and level-0 files were not modified. `import-local` excludes
Chapleau on future reruns.

## St-Marthe/St-Maurice publisher pits

`import-st-marthe-maurice` reads the publisher `dataverse_files` CSVs and
`Plotlocations.csv`, producing one temperature-only UTC series for each of
five pits at 2 and 10 cm in each of 18 plots. The 2020–21 and 2021–22 files
are combined for each instrument; unmeasured intervening hours are `NaN`.
The publisher freezing probabilities are deliberately not imported as sensor
measurements. The production import yielded 180 pit-depth streams (90 at each
depth) in `standardized/st_marthe_maurice`, with plot coordinates in
`metadata/st_marthe_maurice_sensors.csv` and source provenance in its context
CSV. The publisher README explicitly labels the measurement time UTC.

The former `local_MT01`–`MT10` and `local_MU01`–`MU08` were **medians of the
five 2 cm pits**, not individual probes. Every observed local median was
reconstructed from the imported publisher pit series before those 18 copies
were archived. The independent pit readings now remain available instead of
only the plot median.

```bash
sfcc-label import-st-marthe-maurice /path/to/dataverse_files \
  --observations-dir /path/to/private-data/standardized/st_marthe_maurice \
  --sensors-file /path/to/private-data/metadata/st_marthe_maurice_sensors.csv \
  --context-file /path/to/private-data/metadata/st_marthe_maurice_context.csv
```

## James Bay, Montmorency, and Kuujjuarapik iButton transects

`import-ibutton-transect` reads the `Submission_2023/BJ`, `FM`, or `KJ` publisher
workbook metadata and companion CSV. Each iButton is a temperature-only
stream at either 0 cm (ground surface beneath the lichen) or 5 cm below the
ground surface. The production imports contain 28 James Bay, 36 Montmorency,
and 26 Kuujjuarapik depth-specific streams, one source each: `james_bay`,
`montmorency`, and `kuujjuarapik` (raw files arrived in a folder named UQAM; that
name is not used for these sources). This includes publisher streams not represented in the old local
collection. Original sub-hour timestamps are assigned to the containing UTC
hour; multiple readings in one hour are averaged and the collision count is
recorded in the context CSV. Empty hours remain `NaN`.

The 2023 workbook marks these timestamps UTC, but the 2022 submission
metadata calls them “Local.” Both claims are recorded in the context/metadata;
the importer follows the 2023 workbook and does not claim the disagreement is
resolved. The 35 depth-unknown local BJ/FM/KJ temperature-only copies were
matched observation-by-observation to the imported 5 cm source streams and
archived. The known-depth, temperature-plus-moisture 5 cm TEROS records
(`BJ01`–`BJ09` and `FM203`, `FM212`, `FM219`, `FM304`, `FM307`, `FM311`,
`FM403`, `FM404`, `FM406`, `FM407`) remain in `local`.

```bash
sfcc-label import-ibutton-transect /path/to/DataSubmission/DataSubmission \
  --network BJ \
  --observations-dir /path/to/private-data/standardized/james_bay \
  --sensors-file /path/to/private-data/metadata/james_bay_sensors.csv \
  --context-file /path/to/private-data/metadata/james_bay_context.csv
```

Repeat with `--network FM` (`montmorency`) or `KJ` (`kuujjuarapik`).
All 53 superseded local temperature-only copies are recoverable in
`archive/local_publisher_series_20260926/observations` with a match manifest
and the previous local metadata/status. The publisher sources and level-0
tables were not changed; `import-local` excludes these superseded streams on
future reruns while retaining the TEROS records.

## BERMS Old Black Spruce and Old Jack Pine profiles

The two formerly depth-unknown BERMS local series (`BS01` and `JP01`) are
unambiguously **5 cm temperature**: the source processing notebook maps both
to `SoilTemp_005cm`. A full value-level comparison found zero mismatches
across 17,546 BS01 and 61,369 JP01 observed hours. The previous local
metadata was backed up with this depth evidence in
`archive/berms_depth_correction_20260926`. The [BERMS site page](https://water.usask.ca/berms/index.php)
confirms the Old Black Spruce/Old Jack Pine station locations, and a
[BERMS field study](https://water.usask.ca/hillslope/documents/pdfs/2022/nehemy_2022_2.pdf)
independently documents 2, 5, 10, 20, 50, and 100 cm temperature profiles.

`import-berms` uses the original CSV profiles in `/Volumes/Expansion/UQAM/BERMS/Data`
and the Old Black Spruce 2017–2020 RData to create 28 separate streams:
12 temperature point-depth series (six depths per site) and 16 moisture
series. Source VWC support intervals are not paired to nearby temperature
depths. The CSV clock is interpreted as UTC, as in the legacy import; the
summer shallow-soil diurnal phase is consistent with that interpretation but
does not prove it. RData POSIX timestamps are converted from absolute epoch
seconds to UTC; its README describes an `America/Regina` display clock. Both
time-basis decisions are recorded in `berms_context.csv` and should remain
reviewable rather than silently assumed exact.

```bash
pip install 'sfcc-label[source-r]'
sfcc-label import-berms /path/to/BERMS/Data \
  --observations-dir /path/to/private-data/standardized/berms \
  --sensors-file /path/to/private-data/metadata/berms_sensors.csv \
  --context-file /path/to/private-data/metadata/berms_context.csv
```

The production import passed schema validation. Its 5 cm output reproduces
every observed hour of the two old local files; those copies are recoverable
in `archive/local_berms_level0_20260926/observations` with a match manifest
and the prior local metadata/status. Original BERMS files and level-0 tables
were not changed. `import-local` excludes BERMS on future reruns.

## Trail Valley Creek PANGAEA soil profile

`import-tvc-boike` reads the four published annual `Boike-etal_2020_TVCsoilYYYY.tab`
files (2016–2019). Their timestamps are explicitly UTC and already hourly.
It writes four paired soil-temperature/volumetric-moisture streams at 2, 5,
10, and 20 cm below the moss–air surface, plus three separate 0–15 cm
vertical moisture-only streams. The vertical probes have a nominal midpoint
of 7.5 cm in metadata; their 0–15 cm measurement support is retained in the
depth bounds and context table. No raw electrical output is published, so
`raw_value` is `NaN`. Missing source values remain `NaN`.

```bash
sfcc-label import-tvc-boike /path/to/Boike-etal_2020_TVCsoilT/datasets \
  --observations-dir /path/to/private-data/standardized/tvc_boike \
  --sensors-file /path/to/private-data/metadata/tvc_boike_sensors.csv \
  --context-file /path/to/private-data/metadata/tvc_boike_context.csv
```

The separate `TVC_Boike_2013_2020.csv` is not imported by this command: its
2016–2019 profile overlaps the PANGAEA release and its local clock needs a
separate audit before the earlier 20 cm records can be added. The legacy
HydraProbe-derived `local/TV*` series are handled by the dedicated importer
below.

## Trail Valley Creek HydraProbe stations

`import-tvc-hydraprobe` reads the six station workbooks from the TVC Soil
Stations repository. Each workbook contains four HydraProbes: H1 and H3 are
at 5 cm, while H2 and H4 are at 10 cm. It averages the 30-minute source rows
within each UTC hour and writes temperature, volumetric water fraction, and
effective bulk permittivity to separate standardized streams. Effective
permittivity uses the temperature-corrected components and the published
HydraProbe conversion:

`(epsilon_real + sqrt(epsilon_real^2 + epsilon_imag^2)) / 2`.

The formula, source columns, coordinates, depths, and UTC basis are recorded
in `tvc_hydraprobe_context.csv` and `tvc_hydraprobe_sensors.csv`. The former
11 one-stream TVC files were archived in
`archive/local_tvc_hydraprobe_20260926`; they are no longer active in
`standardized/local`.

```bash
sfcc-label import-tvc-hydraprobe /path/to/TVC-Soil-Stations-master/data/hydraprobe \
  --observations-dir /path/to/private-data/standardized/tvc_hydraprobe \
  --sensors-file /path/to/private-data/metadata/tvc_hydraprobe_sensors.csv \
  --context-file /path/to/private-data/metadata/tvc_hydraprobe_context.csv
```

## Experimental UTC timestamp screen for local observations

`screen-time-utc` reads the existing, already-processed local `level_0/*.csv` files and
the supplied site metadata without changing the source timestamps or writing any
observations. Its output is a new, one-row-per-site-per-UTC-year CSV of **review
flags**, not a timezone correction or proof of UTC. Source `datetime` values are
interpreted as the site's declared UTC timestamps. The command refuses to
overwrite an existing report.

```bash
sfcc-label screen-time-utc /path/to/level_0 \
  --metadata /path/to/metadata_soil_added.csv \
  --biome-file /path/to/meta.csv \
  --output data/processed/local_time_qc.csv
```

The screen groups depths into non-overlapping bands: 0–<2, 2–<7, 7–<13,
13–<18, 18–<23 cm, then 5 cm bands. It keeps unknown depths unknown. The
user-confirmed CP01–CP04 probes are represented as 0–10 cm intervals with a
5 cm midpoint, despite their source metadata's `10` cm entry. Because this
support crosses the shallow limit, they are **not** treated as point-like
5 cm probes for the solar test. Both depth and provenance appear in the report.

For 0–<7 cm point-like measurements only, the solar screen estimates each
warm-season day's temperature-cycle phase in local solar time from longitude
and the equation of time. It considers June–October days with at least 18
covered UTC hours, mean soil temperature above 2 °C, and a fitted daily
amplitude of at least 0.5 °C. An annual shallow-site flag requires at least
20 usable days and a phase discrepancy of at least 5 hours on at least 70%
of them. These broad thresholds intentionally target conspicuous errors;
they are screening heuristics, not calibrated physical limits.

The neighbor screen compares normalized daily soil-temperature curves with
nearby sites in the same depth band and, when available, the same broad biome.
It searches within 100 km by default and requires at least two comparable
neighbors with 20 shared usable days each. An offset must be at least 3 hours,
show substantial correlation improvement over zero lag, and agree across
neighbors. Deep sensors can receive a neighbor result when they have a
detectable daily cycle, but the solar test is always inapplicable to them.
Sparse coverage, unknown depth, weak cycles, or insufficient neighbors yield
`inconclusive` / `not_applicable` rather than a positive timing verdict.

The combined `timestamp_status` is `suspect_offset` only when the shallow
solar and neighbor tests agree within 2 hours; a single-test warning or
conflict is `review`. `no_obvious_offset` means this screen found no large
offset, **not** that UTC was proved. `inconclusive` means neither test had
enough evidence. A proposed shift is a diagnostic only. The source file,
derived hourly records, and any future standardized timestamps must remain
unchanged until a human checks provenance. This screen does not yet include
radiation-based alignment, a better diagnostic where measured shortwave or
photosynthetically active radiation exists.

To audit the shallow solar heuristic against already-standardized UTC data,
run `benchmark-solar-utc` separately for ISMN and AmeriFlux. It reads only
streams whose documented depth support lies entirely within 0–7 cm, applies
the same daily/annual thresholds, and writes one row per sensor-year. It does
**not** run the neighbor test or re-import observations; the isolated solar
result makes a widespread false-positive pattern visible rather than hiding
it behind the two-test consensus rule. Treat these collections as UTC-labeled
controls, not proof that every individual source clock was correct.

```bash
sfcc-label benchmark-solar-utc /path/to/ismn_sensors.csv /path/to/standardized/ismn \
  --output data/processed/ismn_solar_benchmark.csv
sfcc-label benchmark-solar-utc /path/to/ameriflux_sensors.csv /path/to/standardized/ameriflux \
  --output data/processed/ameriflux_solar_benchmark.csv
```

On the locally available standardized collections (audit dated 2026-09-26),
the unchanged solar rule flagged 139/17,527 testable ISMN sensor-years (0.79%)
and 33/7,925 testable AmeriFlux sensor-years (0.42%). Another 5,748 ISMN and
3,445 AmeriFlux sensor-years were inconclusive. In the local level-0 data,
126/184 testable shallow site-years (68.5%) triggered the same solar rule.
For the matching 2–<7 cm band alone, the reference rates were 113/17,420
(0.65%) for ISMN and 11/7,209 (0.15%) for AmeriFlux.
These are *sensor-years*, except for the local *site-years*, and are not
independent observations. The screen does not use the separate source QA flags
or prove that any individual clock is right or wrong. Nonzero warnings in
UTC-labeled controls mean this remains an **experimental review aid**, not an
automatic timezone correction or a validated classifier. The neighbor rule
has not been benchmarked on these standardized collections.

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

## SoilGrids soil properties

`soilgrids-fetch` samples SoilGrids 2.0 (ISRIC, 250 m) at every distinct catalog
location, reading only the needed pixels from ISRIC's cloud-optimized rasters
(`files.isric.org/soilgrids/latest/data`). It fetches `clay`, `sand`, `silt`, `soc`,
`bdod`, and `cfvo` (mean and uncertainty for all six layers 0-5, 5-15, 15-30,
30-60, 60-100, 100-200 cm), the most probable WRB reference soil group, and the
Cryosols and Histosols probabilities. Values are converted from SoilGrids mapped
units to %, g/kg, and g/cm3; uncertainty is the SoilGrids (Q95-Q05)/Q50 ratio.
A nodata pixel falls back to the nearest valid pixel within ±2 pixels (at most
about 700 m on the diagonal), and the shift
is recorded. Each raster is cached under `cache/soilgrids/`, so an interrupted
fetch resumes. Spot values were checked against the ISRIC REST API.

`soilgrids-match` writes `metadata/sensor_soil.csv`, one row per sensor, from the
single SoilGrids layer that matches the sensor depth:

1. Take `depth_cm` (for an interval sensor this is its midpoint).
2. Round to the nearest whole cm.
3. Use the layer whose range includes it, bottom edge inclusive: 0-5 holds 0 to
   5 cm, 5-15 holds 6 to 15 cm, and so on. 5.4 cm uses 0-5; 5.6 cm uses 5-15.
4. Deeper than 200 cm uses 100-200 (`depth_basis=measured_below_soilgrids`).

AmeriFlux sensors without a documented depth are assigned systematically:
a sensor with a vertical level (`h1v2r1` is level `v2`) takes the layer most
often observed for that level among AmeriFlux sensors whose depth is known
(`depth_basis=assumed_from_level`, with the share in `depth_note`); a sensor
without a level takes 0-5 cm (`assumed_top`). Filter on `depth_basis` to exclude
assumed depths.

```bash
sfcc-label soilgrids-fetch --workers 12      # writes metadata/soilgrids_points.csv
sfcc-label soilgrids-match                   # writes metadata/sensor_soil.csv
```

The general `modeled_soil_*` fields in the sensor metadata are not used for
SoilGrids; `sensor_soil.csv` holds the values with their source and version.

## EASE-2 grid cells and ESA CCI land cover

`sfcc_label.grid` knows ten NSIDC EASE-Grid 2.0 grids: Northern Hemisphere
(`N`, EPSG:6931) and global (`M`, EPSG:6933) at 6.25, 9, 12.5, 25, and 36 km,
named `N6p25km`, `N9km`, `N12p5km`, `N25km`, `N36km`, `M6p25km`, ... (`p`
replaces the decimal point). A bare resolution such as `9km` means the `N` grid.
Cell ids look like `EASE2_N_25km_r0302_c0162` (zero-based row and column).

`sfcc-label grid-cells` writes `metadata/sensor_grid_cells.csv`: one row per
sensor with its cell id on all ten grids (columns `EASE2_N_6p25km` ...
`EASE2_M_36km`). Rerun it after sensors are added.

`sfcc-label landcover-cci-grids` builds one GeoTIFF per grid,
`landcover/landcover_cci2015_EASE2_<grid>.tif`, from ESA CCI Land Cover v2.0.7
(300 m, 2015), the product used by the SMOS L3 soil freeze-thaw algorithm
(Rautiainen et al., 2025). One representative year is used; land cover at the
sensor sites changes little. CCI classes are merged into the six SMOS classes
following the CCI user guide IPCC conversion:

| Code | Class | CCI LCCS codes |
| --- | --- | --- |
| 1 | forest | 50-100, 160, 170 |
| 2 | low_vegetation | 110-153 |
| 3 | wetland | 180 |
| 4 | agriculture | 10-40 |
| 5 | water | 210 |
| 6 | other | 190, 200-202, 220 |

Band 1 is the dominant class (0 = no data); bands 2-7 are the area fraction of
each class (uint16, scale 0.0001). Every 300 m pixel is assigned to the cell that
contains its centre and weighted by its area (cos latitude), so fractions are
true area shares.

`sfcc-label landcover-cci-sensors` writes `metadata/sensor_landcover_cci.csv`
with one row per sensor and grid: the sensor's own 300 m class, its cell, the
cell's dominant class and six fractions, the fraction of the sensor's class in
the cell, and whether the sensor matches the cell's dominant class. These are the
inputs for SMOS-style representativeness checks (dominant class share, open
water and "other" at most 5 %).

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
