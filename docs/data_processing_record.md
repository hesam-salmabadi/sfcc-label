# sfcc-label data and processing record

Status as of 2026-09-27. This document describes what the harmonised in situ
soil freeze/thaw dataset contains, where each file lives, and every processing
step taken to build its metadata, with the reasoning behind each decision. It is
the working record; `docs/manuscript_data_section.md` is the same material
written as a journal data section.

All numbers below were computed from the files on the data volume on
2026-09-27 (full scan of every standardized file, not a sample).

---

## 1. At a glance

| Item | Value |
| --- | --- |
| Sensors (one standardized hourly file each) | 17,090 |
| Sites | 2,482 |
| Distinct coordinates | 2,468 |
| Sources | 14 |
| Latitude range | 1.92–74.73° N |
| Period covered | 1991-01-01 to 2026-07-20 (UTC) |
| Hourly rows | 987,941,116 |
| Hours with soil temperature | 808,386,988 |
| Hours with soil moisture | 133,485,293 |
| Sensors with temperature / moisture / both | 16,924 / 3,004 / 2,934 |
| Median record length per sensor | 5.5 years (mean 6.6, max 34.8) |
| Standardized data size | 40 GB (+ 8.8 GB ISMN/AmeriFlux flag sidecars) |

Ancillary metadata attached to every sensor:

- SoilGrids 2.0 soil properties at the sensor's depth (`sensor_soil.csv`)
- EASE-Grid 2.0 cell id on ten grids (`sensor_grid_cells.csv`)
- ESA CCI land cover (six SMOS classes) for the sensor pixel and its cell on each
  grid, with a representativeness flag (`sensor_landcover_cci.csv`)

All four sensor tables join on `sensor_id`.

---

## 2. Where the data live

Data are private and are not in Git. Root: `/Volumes/Expansion/sfcc-label-data`
(the CLI default; override with the `SFCC_DATA_ROOT` environment variable).

```text
standardized/<source>/<sensor_id>.csv       hourly UTC observations, one file per sensor
flags/<source>/<sensor_id>.csv.gz           ISMN quality flags / AmeriFlux source coverage
metadata/<source>_sensors.csv               sensor metadata, one file per source (authoritative)
metadata/<source>_context.csv               source-specific provenance and depth evidence
metadata/<source>_import_status.csv         per-sensor import outcome
metadata/catalog.csv                        merged sensor metadata (all sources, same schema)
metadata/catalog_manifest.csv               which file contributed how many rows
metadata/sensor_id_map.csv                  old -> new sensor ids (2026-09-27 rename)
metadata/sensor_soil.csv                    SoilGrids values at each sensor depth
metadata/soilgrids_points.csv               raw SoilGrids values, all layers, per location
metadata/sensor_grid_cells.csv              cell id on all ten EASE-2 grids
metadata/sensor_landcover_cci.csv           CCI land cover + representativeness, per sensor and grid
landcover/landcover_cci2015_EASE2_<grid>.tif   dominant class + six class fractions per cell
sources/esa_cci_lc/                         ESA CCI LC v2.0.7 2015 source raster
cache/soilgrids/                            one CSV per sampled SoilGrids raster (resumable fetch)
archive/                                    backups taken before every destructive step
```

Code: `https://github.com/hesam-salmabadi/sfcc-label` (`src/sfcc_label/`,
`scripts/`, `tests/`).

---

## 3. Contents by source

| Source (`source`) | Code | Sensors | Sites | Latitude | Depth (cm) | Period (UTC) | T hours | SM hours | Variables |
| --- | --- | ---: | ---: | --- | --- | --- | ---: | ---: | --- |
| ISMN (`ismn`) | `ismn` | 11,774 | 1,728 | 1.9–70.3 | 0–203 | 2010-01-01 – 2026-07-20 | 573,680,059 | 118,472,771 | T; SM for 2,511 |
| AmeriFlux BASE (`ameriflux`) | `amf` | 4,684 | 484 | 9.2–74.7 | 0.01–300 (332 unknown) | 1991-01-01 – 2026-06-11 | 229,534,457 | 10,968,472 | T; SM for 329 |
| St-Marthe/St-Maurice (`st_marthe_maurice`) | `smm` | 180 | 18 | 45.4–46.5 | 2, 10 | 2020-10-06 – 2022-04-23 | 458,568 | 0 | T |
| NRCan Open File 66 iButtons (`nrcan_ibutton`) | `nrcan` | 107 | 107 | 68.3–69.4 | 13 | 2016-08-17 – 2017-08-22 | 219,019 | 0 | T |
| Local network and partners (`local`) | `local` | 69 | 69 | 47.3–58.2 | 5 | 2014-08-01 – 2024-06-30 | 1,525,340 | 1,387,157 | T, SM, bulk EDC |
| Cambridge Bay iButtons (`cambridge_bay`) | `cbay` | 64 | 16 | 69.2 | 0–28 | 2018-07-27 – 2020-09-16 | 191,008 | 0 | T |
| Chapleau (`chapleau`) | `chap` | 60 | 4 | 47.6–47.9 | 6–30 (T); 0–10, 0–18 (SM) | 2017-05-18 – 2023-01-01 | 450,517 | 1,758,664 | T or SM (+ CS616 period) |
| Montmorency transect (`montmorency`) | `mont` | 36 | 19 | 47.3–47.4 | 0, 5 | 2019-10-29 – 2023-06-18 | 211,992 | 0 | T |
| BERMS OBS/OJP (`berms`) | `berms` | 28 | 2 | 53.9–54.0 | 2–100 (T); intervals to 150 (SM) | 2015-01-01 – 2022-01-01 | 667,680 | 617,769 | T or SM |
| James Bay transect (`james_bay`) | `jbay` | 28 | 14 | 53.2–53.4 | 0, 5 | 2014-09-04 – 2022-08-29 | 576,223 | 0 | T |
| Kuujjuarapik transect (`kuujjuarapik`) | `kuuj` | 26 | 13 | 55.0 | 0, 5 | 2014-08-20 – 2022-09-01 | 515,420 | 0 | T |
| TVC HydraProbe stations (`tvc_hydraprobe`) | `tvch` | 24 | 6 | 68.7 | 5, 10 | 2018-09-02 – 2019-03-24 | 115,055 | 111,262 | T, SM, permittivity |
| TVC PANGAEA profile (`tvc_boike`) | `tvcb` | 7 | 1 | 68.7 | 2–20; 0–15 (SM) | 2016-08-27 – 2019-08-02 | 102,796 | 169,501 | T, SM |
| Dryden (`dryden`) | `dryden` | 3 | 1 | 49.9 | 6, 18, 30 | 2019-07-24 – 2023-01-01 | 88,452 | 0 | T |

`local` holds sensors from our own sites and network plus partner data that is
not publicly released. ISMN data may not be redistributed (ISMN terms), so no
ISMN-derived records are committed to the repository.

Depth distribution of all sensors (`depth_cm`): ≤5 cm 2,842; 5–15 cm 4,758;
15–30 cm 3,546; 30–60 cm 3,284; 60–100 cm 903; >100 cm 1,425; unknown 332.

Latitude distribution: <30° N 649; 30–45° N 10,952; 45–60° N 4,196; ≥60° N 1,293.

---

## 4. File formats

### 4.1 Observations — `standardized/<source>/<sensor_id>.csv`

```csv
timestamp_utc,soil_temperature_c,soil_moisture_m3_m3,raw_value
2011-03-03T22:00:00Z,18.8548,NaN,NaN
```

One row per UTC hour between a sensor's first and last available hour, gaps
filled with all-`NaN` rows. Temperature in °C, volumetric moisture in m³ m⁻³.
`raw_value` is the native sensor signal where one exists (units in
`raw_variable`/`raw_unit`). Missing is always the literal `NaN`, never zero.

### 4.2 Sensor metadata — `metadata/<source>_sensors.csv` and `catalog.csv`

20 columns: `sensor_id, source, latitude, longitude, site_id, network, station,
depth_cm, depth_from_cm, depth_to_cm, raw_variable, raw_unit, source_id,
source_url, timezone_original, soil_moisture_method,
soil_temperature_sensor_type, soil_moisture_sensor_type, sensor_type_source,
sensor_type_note`. For an interval sensor `depth_cm` is the midpoint and
`depth_from_cm`/`depth_to_cm` hold the support interval.

### 4.3 Sensor identifiers

`<src>_<site>_<depth>_<tag>`, e.g. `berms_bs01_002p5cm_m`,
`amf_ca-af1_nodepth_h1v2r1`, `ismn_arm-anthony_000-005cm_2a14e2a750`.
Exactly four `_`-separated parts, lowercase `a-z0-9-` only; the id is also the
file stem. Depth is zero-padded cm with `p` for a decimal point, `a-b` for an
interval, `nodepth` if unknown. The tag separates co-located sensors: the
source's own label (AmeriFlux `h`/`v`/`r` indices, pit, probe, campaign year,
`t`/`m`/`mr`) or `s1` for a single sensor; ISMN keeps a stable 10-character
hash of instrument identity. Built by `sfcc_label.naming.sensor_id`.

### 4.4 `sensor_soil.csv` (one row per sensor)

`sensor_id, source, latitude, longitude, depth_cm, depth_basis, depth_note,
soilgrids_top_cm, soilgrids_bottom_cm, clay_pct, sand_pct, silt_pct, soc_g_kg,
bdod_g_cm3, cfvo_pct, <property>_uncertainty (×6), texture_class_usda,
wrb_class, cryosols_probability_pct, histosols_probability_pct,
max_pixel_offset_m, soilgrids_version, accessed`.

### 4.5 `sensor_grid_cells.csv` (one row per sensor)

`sensor_id, source, site_id, latitude, longitude` + ten columns
`EASE2_N_6p25km … EASE2_M_36km`, each holding a cell id
`EASE2_<family>_<res>_r<row>_c<col>` (zero-based, four-digit padded).

### 4.6 `sensor_landcover_cci.csv` (one row per sensor and grid; 170,900 rows)

`sensor_id, source, site_id, latitude, longitude, cci_class, sensor_class, grid,
cell_id, row, col, cell_class, forest_fraction, low_vegetation_fraction,
wetland_fraction, agriculture_fraction, water_fraction, other_fraction,
sensor_class_fraction, sensor_matches_cell, eligible, reason, land_cover_source`.

### 4.7 `landcover/landcover_cci2015_EASE2_<grid>.tif`

Seven uint16 bands on the grid's native CRS and extent: band 1 dominant class
(0 no data, 1 forest, 2 low vegetation, 3 wetland, 4 agriculture, 5 water,
6 other); bands 2–7 area fraction of classes 1–6, scale 0.0001.

---

## 5. What was done, step by step

### Step 1 — Import and harmonise each source (before 2026-09-27)

Each source has its own importer (`src/sfcc_label/<source>.py`, CLI
`sfcc-label import-…`). Common rules:

- Convert every timestamp to UTC and aggregate to hourly means; no
  interpolation. Source clock definitions are used when available (AmeriFlux
  BIF `UTC_OFFSET`, `America/Toronto` for NRCan). Chapleau uses inferred fixed
  UTC−5; where a source clock is
  assumed rather than proven, the assumption is written to `timezone_original`
  and the context file.
- Convert moisture to m³ m⁻³ (percent ÷ 100) and map source missing markers
  (`-9999`, `9999`, `NA`) to `NaN`.
- No new anomaly QA/QC. ISMN and AmeriFlux provider information is kept in
  flag sidecars.
- Keep every physical sensor as its own stream. Temperature and moisture are
  paired in one file only when they are documented at the same depth
  (AmeriFlux: exactly one TS and one SWC at the same Measurement-Height depth;
  ISMN: same instrument/position, then unique depth match).
- Replace derived "local" copies with the original publisher data where both
  existed (NRCan, Cambridge Bay, Dryden, Chapleau, St-Marthe/St-Maurice, BERMS,
  TVC, iButton transects, 67 ISMN duplicates). Every replacement was checked
  value by value and the superseded files are kept in `archive/`.

Source-specific details (depth evidence, clock decisions, coordinate
discrepancies) are in the README section of each importer and in each
`<source>_context.csv`.

### Step 2 — Consistent sensor names (2026-09-27)

Problem: each importer had its own naming style (`ameriflux_CA-AF1_TS_1_1_1`,
`ismn_ARM_Anthony_d75da1cab8_0-000000-5-000000cm_…`, `uqam_BJ01_0cm`, …) and
folder names did not match the `source` column.

Done:

1. Defined the `<src>_<site>_<depth>_<tag>` rule (section 4.3).
2. `scripts/rename_sensor_ids.py` built the old→new map for all 17,090 sensors
   and 1,301 unimported ISMN pairing candidates, and checked: four-part pattern,
   uniqueness ignoring case (the exFAT volume is case-insensitive), one
   metadata file per sensor, one file per id.
3. Backed up all metadata to `archive/rename_20260927/metadata/`.
4. Renamed 17,090 standardized files and 16,458 flag files (with their macOS
   `._` sidecars) and renamed folders to the `source` value.
5. Rewrote `sensor_id` in every metadata, context, pairing and status file;
   rebuilt `catalog.csv`. The map is saved as `metadata/sensor_id_map.csv`.
6. Moved id construction into `sfcc_label/naming.py`, used by all importers, so a
   re-import produces the same names.

The three iButton transects had arrived in a folder named after UQAM; that name
has no meaning for the data, so they became the place-named sources
`james_bay`, `montmorency`, `kuujjuarapik`.

### Step 3 — SoilGrids soil properties (2026-09-27)

Source: SoilGrids 2.0 (ISRIC; Poggio et al., 2021), 250 m.

1. Read directly from ISRIC's cloud-optimized rasters
   (`files.isric.org/soilgrids/latest/data`) with rasterio over HTTP, reading
   only pixels under sensors. Projection: Interrupted Goode Homolosine.
2. For each of the 2,468 locations: `clay, sand, silt, soc, bdod, cfvo`
   (mean and uncertainty) at all six layers (0–5, 5–15, 15–30, 30–60, 60–100,
   100–200 cm), plus the most probable WRB reference soil group and the
   Cryosols and Histosols probabilities — 75 rasters in total. Each raster is
   cached as one CSV so the fetch is resumable.
3. Converted mapped units: clay/sand/silt g kg⁻¹ → % (÷10), soc dg kg⁻¹ →
   g kg⁻¹ (÷10), bdod cg cm⁻³ → g cm⁻³ (÷100), cfvo cm³ dm⁻³ → % (÷10);
   uncertainty ratio ÷10.
4. A no-data pixel falls back to the nearest valid pixel within ±2 pixels
   (≤ ~700 m); the shift is recorded (324 sensors, max 559 m).
5. Depth matching, one layer per sensor (no blending):
   round `depth_cm` to the nearest whole cm, then take the layer whose range
   contains it, bottom edge inclusive (0–5 holds 0–5 cm, 5–15 holds 6–15 cm, …);
   5.4 cm → 0–5, 5.6 cm → 5–15. Deeper than 200 cm → 100–200.
6. Unknown depth (332 AmeriFlux sensors): the AmeriFlux vertical index
   (`v1`, `v2`, … in `h?v?r?`) is used systematically — each level gets the
   layer most often observed for that level among AmeriFlux sensors with known
   depth (v1 → 0–5 cm, 74 % of 895; v2 → 5–15 cm, 54 % of 651; v3/v4 → 15–30 cm;
   v5 → 30–60 cm; v6 → 60–100 cm; v7+ → 100–200 cm). Sensors without a level get
   0–5 cm. These rows have `depth_basis` = `assumed_from_level` (208) or
   `assumed_top` (124) and the share in `depth_note`.
7. USDA texture class computed from sand/silt/clay normalised to 100 %.

Checked before the full run: projection and units against the ISRIC REST API
(5 values, exact match).

Result: 17,054 sensors with complete texture; 36 ISMN sensors at four Berlin
sites have no SoilGrids data (urban pixels, no valid pixel nearby).
Median (5th–95th percentile): clay 21.1 % (6.7–39.7), sand 41.7 % (8.9–75.0),
silt 35.7 % (13.5–58.9), SOC 19.4 g kg⁻¹ (2.5–140.5), bulk density
1.38 g cm⁻³ (0.89–1.68), coarse fragments 9.3 % (0.4–28.2). Most common
textures: loam 5,387, sandy loam 3,817, clay loam 2,933. Cryosols probability
≥50 %: 204 sensors; Histosols ≥50 %: 105; SOC ≥120 g kg⁻¹: 1,212.

### Step 4 — EASE-Grid 2.0 cells (2026-09-27)

`sfcc_label/grid.py` defines ten NSIDC EASE-Grid 2.0 grids (Brodzik et al.,
2012): Northern Hemisphere `N` (EPSG:6931) and global `M` (EPSG:6933) at
6.25, 9, 12.5, 25 and 36 km, with the published dimensions (e.g. N25km
720×720, M36km 964×406). Grid names use `p` for the decimal point (`N6p25km`).
`sfcc-label grid-cells` writes each sensor's cell on every grid. Every sensor has
a cell on every grid.

Cells holding at least one sensor: N6p25km 1,639; N9km 1,542; N12p5km 1,451;
N25km 1,216; N36km 1,064; M6p25km 1,658; M9km 1,550; M12p5km 1,454;
M25km 1,205; M36km 1,064.

### Step 5 — Land cover (2026-09-27)

Product choice: ESA CCI Land Cover v2.0.7 (300 m), year 2015, instead of MODIS
MCD12Q1. Reasons: it is the product used by the operational SMOS L3 soil
freeze–thaw algorithm (Rautiainen et al., 2025), so our representativeness
test matches SMOS; it is finer (300 vs 500 m); it has a proper wetland class;
and MODIS IGBP labels much boreal forest as savanna. One representative year
is used because land cover at the sensor sites changes little; 2015 is the last
v2.0.7 year and needs no account.

1. Merged the CCI LCCS classes into the six SMOS classes following the CCI user
   guide IPCC conversion: forest 50–100, 160, 170; low vegetation 110–153;
   wetland 180; agriculture 10–40; water 210; other 190, 200–202, 220.
2. For every grid, every 300 m pixel centre is projected to the grid (the
   projections are separable, so each row and column is projected once; exact
   to 0 m against pyproj), assigned to its cell, and weighted by cos(latitude),
   giving true area fractions. Dominant class = largest fraction. Pixels south
   of 40° S are skipped (only far corner cells of the N grids lie there).
3. `sensor_landcover_cci.csv` stores, per sensor and grid, the sensor's own 300 m
   class, its cell, the cell's dominant class and all six fractions.

Sensor pixel classes: forest 6,046; low vegetation 5,463; agriculture 5,100;
other 275; wetland 152; water 54.

### Step 6 — Representativeness screen (2026-09-27)

Following the SMOS validation criteria, a sensor counts for its cell on a grid
only if all four hold: (1) its class equals the cell's dominant class, (2) that
class covers ≥70 % of the cell, (3) open water ≤5 %, (4) "other" ≤5 %. Missing
values fail. SMOS applies the 70 % test to all sensors in a cell together; here
it is applied per sensor. `eligible` and `reason` (first failed test) are in
`sensor_landcover_cci.csv`; thresholds live only in `sfcc_label/landcover.py`,
which the aggregation functions use. The earlier MODIS-based gate was removed.

| Grid | Sensors passing | Cells with ≥1 eligible sensor | class mismatch | class <70 % | water >5 % | other >5 % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| N6p25km | 8,783 (51 %) | 855 | 21 % | 20 % | 4 % | 4 % |
| N9km | 7,807 (46 %) | 754 | 23 % | 20 % | 5 % | 6 % |
| N12p5km | 7,457 (44 %) | 641 | 23 % | 21 % | 4 % | 9 % |
| N25km | 6,022 (35 %) | 438 | 29 % | 26 % | 4 % | 6 % |
| N36km | 5,722 (33 %) | 348 | 32 % | 26 % | 3 % | 5 % |
| M6p25km | 8,143 (48 %) | 863 | 22 % | 20 % | 7 % | 4 % |
| M9km | 7,595 (44 %) | 727 | 23 % | 21 % | 5 % | 7 % |
| M12p5km | 7,020 (41 %) | 640 | 27 % | 21 % | 4 % | 7 % |
| M25km | 6,291 (37 %) | 456 | 31 % | 22 % | 4 % | 6 % |
| M36km | 5,366 (31 %) | 355 | 35 % | 22 % | 6 % | 6 % |

### Step 7 — Metadata cleanup (2026-09-27)

The sensor-metadata columns `land_cover`, `land_cover_source` and
`modeled_soil_*` (six columns) were removed: they were empty except Cambridge
Bay's field land cover, which remains in `cambridge_bay_context.csv`. Backup in
`archive/drop_columns_20260927/`.

### Step 7b — Biome and ecoregion (2026-09-29)

Source: RESOLVE Ecoregions 2017 (Dinerstein et al., 2017; CC BY 4.0), shapefile
`sources/resolve_ecoregions/Ecoregions2017.shp` (846 ecoregions, 14 biomes). ESA CCI describes vegetation
structure, not climate, so it cannot tell boreal from temperate forest or tundra from prairie grassland.

1. `sfcc-label biome-sensors` (`sfcc_label/biome.py`, needs `.[biome]`) assigns each sensor location the
   ecoregion polygon that contains it.
2. Locations outside every polygon (coasts, lake shores) take the nearest ecoregion within 5 km; the distance is
   in `snap_distance_m` (17 sensors, at most 2.8 km). No sensor is left without a biome.
3. Output `metadata/sensor_biome.csv`: `sensor_id, source, site_id, latitude, longitude, biome_num, biome,
   ecoregion, realm, snap_distance_m`.

The detailed ESA CCI class (`cci_class` in `sensor_landcover_cci.csv`) is kept beside the six SMOS classes;
`sfcc_label.landcover_cci.CCI_NAMES` gives the class names.

Sensors per biome: temperate broadleaf and mixed forests 4,048; temperate grasslands, savannas and shrublands
3,914; temperate conifer forests 3,248; deserts and xeric shrublands 2,578; boreal forests/taiga 925; tundra
847; montane grasslands 555; Mediterranean 485; other biomes 490.

### Step 8 — Evaluated and rejected: moss/lichen

No gridded moss/lichen thickness product exists at these scales. The
Copernicus CGLS-LC100 v3.0.1 moss/lichen cover fraction (2015, 100 m) was built
on all grids and then rejected: it is top-of-canopy cover, so ground-layer moss
and lichen under trees or shrubs is invisible; only 68 of 17,090 sensor pixels
had any cover (≈0 % in Schefferville lichen woodland and Kuujjuarapik). Outputs
were deleted. SoilGrids SOC and Histosols probability are the proxies for thick
organic layers.

---

## 6. Verification (2026-09-27)

An independent script (written by Codex, not reusing project code) recomputed
everything from raw sources and public definitions:

| Check | Result | Comparisons | Mismatches |
| --- | --- | ---: | ---: |
| EASE-2 cells on all ten grids (pyproj + NSIDC definitions; anchors M36km (0,0) = r203 c482, N9km pole = r1000 c1000) | PASS | 170,902 | 0 |
| CCI product (v2.0.7, 2015) and six-class mapping at sensor pixels | PASS | 343,301 | 0 |
| Cell fractions and dominant class, brute-force from raw 300 m pixels | PASS | 1,197,856 | 0 |
| Representativeness screen, all rows | PASS | 683,600 | 0 |
| SoilGrids layer per sensor depth, incl. assumed AmeriFlux depths | PASS | 51,270 | 0 |
| Soil values match the right property and layer; units; texture class | PASS | 926,606 | 0 |
| Same sensors, coordinates and cell ids across all files | PASS | 1,367,203 | 0 |
| Live ISRIC REST API, 6 random sensors × 6 properties (0–5, 5–15, 15–30 cm) | PASS | 36 | 0 |

Unit tests: 44 pass (`env -u PROJ_DATA .venv/bin/python -m pytest`).

---

## 7. Known issues and caveats

1. **96 AmeriFlux sensor files contain only `NaN`**: the BASE files list the
   columns but every value is missing. Candidates for removal.
2. **332 AmeriFlux sensors have no documented depth** in the core metadata;
   only the soil table assigns an assumed layer (flagged).
3. **36 ISMN sensors (four Berlin sites) have no SoilGrids values.**
4. **Clock assumptions** that are documented but not proven: Cambridge Bay
   (assumed UTC), the three iButton transects (2023 workbook says UTC, 2022
   metadata says local), BERMS CSV (interpreted UTC), `local` level-0 tables
   (declared UTC). Use `sfcc-label screen-time-utc` for a diagnostic.
5. **Eight AmeriFlux sites** have more than one reported coordinate in the BIF.
6. **Instrument model is unknown for most sensors** (16,865 without a
   temperature sensor type).
7. **SoilGrids is weakest in the Arctic and on organic soils**; use the
   uncertainty columns. It is a 250 m model, not a site measurement.
8. **CCI land cover is one year (2015).**
9. **ISMN starts 2010-01-01** because of the import window chosen.
10. Dated reports in `data/processed/` (2026-09-26) and `WORKFLOW.md` predate the
    rename and the CCI switch.

---

## 8. Rebuild the metadata from the standardized data

```bash
export SFCC_DATA_ROOT=/Volumes/Expansion/sfcc-label-data   # default
PY="env -u PROJ_DATA .venv/bin/sfcc-label"                  # anaconda PROJ_DATA breaks rasterio

.venv/bin/python scripts/build_catalog.py $SFCC_DATA_ROOT/metadata \
  --output $SFCC_DATA_ROOT/metadata/catalog.csv \
  --manifest $SFCC_DATA_ROOT/metadata/catalog_manifest.csv --apply
$PY grid-cells                      # sensor_grid_cells.csv (seconds)
$PY soilgrids-fetch --workers 12    # soilgrids_points.csv (~1 h, resumable)
$PY soilgrids-match                 # sensor_soil.csv
$PY landcover-cci-grids             # ten land-cover GeoTIFFs (~30 min, needs the CCI 2015 GeoTIFF)
$PY landcover-cci-sensors           # sensor_landcover_cci.csv
```

The CCI source is
`https://dap.ceda.ac.uk/neodc/esacci/land_cover/data/land_cover_maps/v2.0.7/ESACCI-LC-L4-LCCS-Map-300m-P1Y-2015-v2.0.7.tif`
(313 MB, no account).

---

## 9. References

- Brodzik, M. J., Billingsley, B., Haran, T., Raup, B., and Savoie, M. H.: EASE-Grid 2.0: Incremental but significant improvements for Earth-gridded data sets, ISPRS Int. J. Geo-Inf., 1, 32–45, 2012.
- Dorigo, W. et al.: The International Soil Moisture Network: serving Earth system science for over a decade, Hydrol. Earth Syst. Sci., 25, 5749–5804, 2021.
- ESA: Land Cover CCI Product User Guide, Version 2.0, 2017.
- Dinerstein, E. et al.: An ecoregion-based approach to protecting half the terrestrial realm, BioScience, 67, 534–545, 2017.
- Poggio, L. et al.: SoilGrids 2.0: producing soil information for the globe with quantified spatial uncertainty, SOIL, 7, 217–240, 2021.
- Rautiainen, K. et al.: An operational SMOS soil freeze–thaw product, Earth Syst. Sci. Data, 17, 5337–5353, https://doi.org/10.5194/essd-17-5337-2025, 2025.
- Buchhorn, M. et al.: Copernicus Global Land Service: Land Cover 100m: collection 3: epoch 2015: Globe (v3.0.1), Zenodo, https://doi.org/10.5281/zenodo.3939038, 2020 (evaluated, not used).
- NRCan Open File 66, https://doi.org/10.4095/329207.
- Hanes et al., Int. J. Wildland Fire, https://doi.org/10.1071/WF22112, 2023 (Dryden site; verify full reference).
- AmeriFlux BASE data and Measurement Height table, https://ameriflux.lbl.gov.
