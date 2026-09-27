# Data (manuscript draft)

*Draft data section in the style of an ESSD / The Cryosphere article. Numbers
are from the dataset as of 2026-09-27; see `docs/data_processing_record.md` for
the full processing record. Items marked [check] need author confirmation.*

---

## 2 Data

### 2.1 In situ soil temperature and moisture observations

We compiled hourly in situ soil temperature and, where available, volumetric
soil moisture from 14 sources into a single harmonised dataset of 17,090 sensor
records at 2,482 sites (2,468 distinct locations) between 1.9° N and 74.7° N
(Fig. 1 [to be drawn], Table 1). The two largest contributors are the
International Soil Moisture Network (ISMN; Dorigo et al., 2021), with
11,774 sensors at 1,728 sites, and the AmeriFlux network BASE data
(https://ameriflux.lbl.gov), with 4,684 sensors at 484 sites. They are
complemented by 632 sensors from regional campaigns and our own and partner
networks in Canada: iButton transects at James Bay, Montmorency Forest and
Kuujjuarapik; the Natural Resources Canada iButton survey near Inuvik and
Tuktoyaktuk (NRCan Open File 66); Cambridge Bay; the St-Marthe and
St-Maurice plots; the Boreal Ecosystem Research and Monitoring Sites (BERMS)
Old Black Spruce and Old Jack Pine profiles; Chapleau; Dryden; two Trail Valley
Creek (TVC) records (the PANGAEA profile of Boike et al. [check reference] and
six HydraProbe stations); and 69 sensors from our own and partner sites that are
not publicly released.

The records span 1991–2026, with a median length of 5.5 years per sensor, and
contain 808.4 million hourly soil temperature values and 133.5 million hourly
soil moisture values. Of the 17,090 sensors, 16,924 measure soil temperature,
3,004 measure soil moisture, and 2,934 measure both at the same documented
depth. Sensor depths range from the ground surface to 3 m: 2,842 sensors are at
or above 5 cm, 4,758 between 5 and 15 cm, 3,546 between 15 and 30 cm, 3,284
between 30 and 60 cm, 903 between 60 and 100 cm and 1,425 below 1 m; the depth
of 332 AmeriFlux sensors is not documented. Most sensors are in the mid-latitudes
(10,952 between 30 and 45° N), with 4,196 between 45 and 60° N and 1,293 north
of 60° N.

**Table 1.** Sources of the harmonised in situ dataset. T: soil temperature;
SM: volumetric soil moisture. Hours are hourly values present in the
standardized records.

| Source | Sensors | Sites | Latitude (° N) | Depth (cm) | Period | T hours (10⁶) | SM hours (10⁶) |
| --- | ---: | ---: | --- | --- | --- | ---: | ---: |
| ISMN | 11,774 | 1,728 | 1.9–70.3 | 0–203 | 2010–2026 | 573.7 | 118.5 |
| AmeriFlux BASE | 4,684 | 484 | 9.2–74.7 | 0–300 | 1991–2026 | 229.5 | 11.0 |
| St-Marthe / St-Maurice | 180 | 18 | 45.4–46.5 | 2, 10 | 2020–2022 | 0.46 | – |
| NRCan Open File 66 | 107 | 107 | 68.3–69.4 | 13 | 2016–2017 | 0.22 | – |
| Own and partner sites | 69 | 69 | 47.3–58.2 | 5 | 2014–2024 | 1.53 | 1.39 |
| Cambridge Bay | 64 | 16 | 69.2 | 0–28 | 2018–2020 | 0.19 | – |
| Chapleau | 60 | 4 | 47.6–47.9 | 6–30; 0–18 | 2017–2023 | 0.50 | 1.76 |
| Montmorency Forest | 36 | 19 | 47.3–47.4 | 0, 5 | 2019–2023 | 0.21 | – |
| BERMS | 28 | 2 | 53.9–54.0 | 2–150 | 2015–2022 | 0.67 | 0.62 |
| James Bay | 28 | 14 | 53.2–53.4 | 0, 5 | 2014–2022 | 0.58 | – |
| Kuujjuarapik | 26 | 13 | 55.0 | 0, 5 | 2014–2022 | 0.52 | – |
| TVC HydraProbe | 24 | 6 | 68.7 | 5, 10 | 2018–2019 | 0.12 | 0.11 |
| TVC PANGAEA profile | 7 | 1 | 68.7 | 0–20 | 2016–2019 | 0.10 | 0.17 |
| Dryden | 3 | 1 | 49.9 | 6, 18, 30 | 2019–2023 | 0.09 | – |
| **Total** | **17,090** | **2,482** | **1.9–74.7** | **0–300** | **1991–2026** | **808.4** | **133.5** |

### 2.2 Harmonisation

Each source was read from its original publisher files by a dedicated importer.
All timestamps were converted to UTC using the documented source clock (for
example the AmeriFlux site `UTC_OFFSET` for local standard time, and the
`America/Toronto` zone for the NRCan and Chapleau loggers) and averaged to
hourly values; sub-hourly readings were averaged within each UTC hour and no
values were interpolated. Hours without data were kept as missing values. Soil
moisture was converted to m³ m⁻³, and source missing-value markers were set to
missing. We did not apply additional quality control; the original ISMN quality
flags and the AmeriFlux source coverage are retained alongside each record.
Where a source clock could only be assumed rather than confirmed (Cambridge
Bay, the three iButton transects and the BERMS CSV files), the assumption is
recorded in the sensor metadata.

Every physical sensor forms a separate record. Soil temperature and soil
moisture were combined in one record only when both were documented at the same
depth: in the AmeriFlux data, when a site had exactly one temperature and one
moisture variable at the same depth in the AmeriFlux Measurement Height table;
in the ISMN data, by matching instrument and position, then by a unique match
at identical depth bounds. Moisture probes that integrate over a depth interval
(for example CS616 rods inserted diagonally to 10 or 18 cm at Chapleau) keep
that interval as their support rather than being assigned a point depth.
Where a derived copy and the original publisher data of the same measurement
were both available, the original was used after a value-by-value comparison.

Each sensor carries a unique identifier of the form
`<source>_<site>_<depth>_<tag>` (for example `berms_bs01_002p5cm_m`), which is
also the name of its data file. The metadata of every sensor record its
coordinates, depth or depth interval, network and station, original identifier,
provenance, original time zone and, where documented, the instrument type.

### 2.3 Soil properties

Soil properties at each sensor were taken from SoilGrids 2.0 (Poggio et al.,
2021), a 250 m global model of soil properties at six standard depth layers
(0–5, 5–15, 15–30, 30–60, 60–100 and 100–200 cm). At each of the 2,468 sensor
locations we sampled the mean and uncertainty of clay, sand and silt content,
soil organic carbon (SOC), bulk density of the fine earth and coarse-fragment
volume at all six layers, together with the most probable World Reference Base
(WRB) reference soil group and the probabilities of Cryosols and Histosols.
Values were converted from SoilGrids mapped units to %, g kg⁻¹ and g cm⁻³.
Where the sensor pixel had no data, the nearest valid pixel within two pixels was
used (324 sensors; maximum shift 559 m); the shift is recorded.

Each sensor was assigned the single SoilGrids layer containing its depth: the
depth was rounded to the nearest centimetre and matched to the layer whose range
includes it, with the lower boundary inclusive (a sensor at 5.4 cm falls in
0–5 cm and one at 5.6 cm in 5–15 cm). For interval sensors the midpoint of the
interval was used, and sensors deeper than 200 cm were assigned the 100–200 cm
layer. For the 332 AmeriFlux sensors without a documented depth we used the
AmeriFlux vertical position index: each index was assigned the layer most
frequently observed for that index among AmeriFlux sensors of known depth (for
example 0–5 cm for the uppermost position, observed for 74 % of 895 sensors, and
5–15 cm for the second, 54 % of 651), and sensors without an index were assigned
0–5 cm. These 332 assignments are flagged. USDA texture classes were derived
from the sand, silt and clay fractions.

Across all sensors, the median clay, sand and silt contents are 21 %, 42 % and
36 %, the median SOC is 19.4 g kg⁻¹ (5th–95th percentile 2.5–140.5 g kg⁻¹), and
the median bulk density is 1.38 g cm⁻³. Loam (5,387 sensors), sandy loam (3,817)
and clay loam (2,933) are the most frequent texture classes. The Cryosols
probability is at least 50 % for 204 sensors and the Histosols probability for
105; 1,212 sensors have an SOC of at least 120 g kg⁻¹, indicating organic
surface horizons. SoilGrids provides no values for 36 sensors at four urban
sites.

No gridded product of moss or lichen layer thickness exists at these scales.
We tested the moss and lichen cover fraction of the Copernicus Global Land
Service 100 m land cover (Buchhorn et al., 2020) as a substitute, but it
represents the top-of-canopy cover and is zero at almost all sensors, including
lichen woodland sites (only 68 of 17,090 sensor pixels had non-zero cover), so
it was not used. The SOC content and Histosols probability serve as indicators
of thick organic surface layers.

### 2.4 Grids and land cover

All sensors were located on the NSIDC Equal-Area Scalable Earth Grid 2.0
(EASE-Grid 2.0; Brodzik et al., 2012), in both the Northern Hemisphere
azimuthal (EASE2-N, EPSG:6931) and the global cylindrical (EASE2-M,
EPSG:6933) projections, at 6.25, 9, 12.5, 25 and 36 km (ten grids). At 25 km,
the 17,090 sensors fall in 1,216 EASE2-N and 1,205 EASE2-M cells.

Land cover was taken from ESA Climate Change Initiative (CCI) Land Cover v2.0.7
for 2015 at 300 m (ESA, 2017), the product used by the operational SMOS soil
freeze–thaw algorithm (Rautiainen et al., 2025). Following that algorithm, the
CCI classes were aggregated into six classes: forest, low vegetation, wetland,
agriculture, open water and other (permanent ice, bare areas and urban areas).
The aggregation follows the IPCC class conversion of the CCI Land Cover user
guide, with tree cover classes including flooded tree cover assigned to forest.
A single year was used because land cover at the sensor sites changes little
over the observation period. For each of the ten grids, every 300 m pixel was
assigned to the grid cell containing its centre and weighted by its area, and
the fractional cover of each class and the dominant class were computed per
cell. Each sensor was assigned the class of the 300 m pixel at its location:
forest (6,046 sensors), low vegetation (5,463), agriculture (5,100), other
(275), wetland (152) and open water (54).

To identify sensors that represent the land cover of their grid cell, we
adopted the criteria of the SMOS freeze–thaw validation (Rautiainen et al.,
2025): a sensor is considered representative when (i) its land cover class is
the dominant class of the cell, (ii) this class covers at least 70 % of the
cell, and the cell contains at most (iii) 5 % open water and (iv) 5 % of the
"other" class. Unlike SMOS, which applies criterion (ii) to the classes of all
sensors in a cell together, we apply it to each sensor individually. The share
of representative sensors decreases with cell size, from 51 % at 6.25 km to 33 %
at 36 km on the EASE2-N grids (Table 2); most exclusions arise because the
sensor's class is not the dominant class of the cell or covers less than 70 % of
it.

**Table 2.** Sensors passing the land-cover representativeness criteria per
grid, and the first criterion failed by the others (share of all 17,090
sensors).

| Grid | Representative | Cells with ≥ 1 representative sensor | Class not dominant | Class < 70 % | Water > 5 % | Other > 5 % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| EASE2-N 6.25 km | 51 % | 855 | 21 % | 20 % | 4 % | 4 % |
| EASE2-N 9 km | 46 % | 754 | 23 % | 20 % | 5 % | 6 % |
| EASE2-N 12.5 km | 44 % | 641 | 23 % | 21 % | 4 % | 9 % |
| EASE2-N 25 km | 35 % | 438 | 29 % | 26 % | 4 % | 6 % |
| EASE2-N 36 km | 33 % | 348 | 32 % | 26 % | 3 % | 5 % |
| EASE2-M 6.25 km | 48 % | 863 | 22 % | 20 % | 7 % | 4 % |
| EASE2-M 9 km | 44 % | 727 | 23 % | 21 % | 5 % | 7 % |
| EASE2-M 12.5 km | 41 % | 640 | 27 % | 21 % | 4 % | 7 % |
| EASE2-M 25 km | 37 % | 456 | 31 % | 22 % | 4 % | 6 % |
| EASE2-M 36 km | 31 % | 355 | 35 % | 22 % | 6 % | 6 % |

### 2.5 Verification

The derived metadata were verified with an independent implementation that did
not share code with the processing chain. It recomputed the grid cell of every
sensor on all ten grids from the NSIDC grid definitions, the land cover class of
every sensor from the original CCI raster, the class fractions of sampled grid
cells from the original 300 m pixels, the representativeness decision for every
sensor and grid, and the SoilGrids layer and property values of every sensor,
and checked that identifiers, coordinates and cell assignments agree across all
tables. None of the approximately 4.7 million comparisons showed a
discrepancy. In addition, SoilGrids values for randomly selected sensors at
depths of 0–5, 5–15 and 15–30 cm matched the ISRIC SoilGrids web service
exactly.

### 2.6 Limitations

SoilGrids is a 250 m statistical model and does not replace site measurements;
its uncertainty is largest in the Arctic and in organic soils, and the
uncertainty layers are provided with the data. Land cover represents a single
year (2015). The time basis of some small campaigns could only be assumed
(Section 2.2). The depth of 332 AmeriFlux sensors is inferred rather than
documented, and 96 AmeriFlux records contain no valid values [check: remove
before release]. The instrument model is documented for fewer than 2 % of
sensors.

### Data availability [draft]

The processing code is available at https://github.com/hesam-salmabadi/sfcc-label
[check: archive with a DOI]. ISMN data are available from https://ismn.earth
and may not be redistributed; AmeriFlux data are available from
https://ameriflux.lbl.gov. SoilGrids 2.0 is available from ISRIC
(https://soilgrids.org) and ESA CCI Land Cover from https://climate.esa.int.
[check: availability of the regional and partner datasets.]

---

## References

Brodzik, M. J., Billingsley, B., Haran, T., Raup, B., and Savoie, M. H.: EASE-Grid 2.0: Incremental but significant improvements for Earth-gridded data sets, ISPRS Int. J. Geo-Inf., 1, 32–45, 2012.

Buchhorn, M., Smets, B., Bertels, L., De Roo, B., Lesiv, M., Tsendbazar, N.-E., Herold, M., and Fritz, S.: Copernicus Global Land Service: Land Cover 100m: collection 3: epoch 2015: Globe (V3.0.1), Zenodo, https://doi.org/10.5281/zenodo.3939038, 2020.

Dorigo, W., Himmelbauer, I., Aberer, D., et al.: The International Soil Moisture Network: serving Earth system science for over a decade, Hydrol. Earth Syst. Sci., 25, 5749–5804, 2021.

ESA: Land Cover CCI Product User Guide Version 2.0, European Space Agency, 2017.

Natural Resources Canada: Open File 66, https://doi.org/10.4095/329207 [check full reference].

Poggio, L., de Sousa, L. M., Batjes, N. H., Heuvelink, G. B. M., Kempen, B., Ribeiro, E., and Rossiter, D.: SoilGrids 2.0: producing soil information for the globe with quantified spatial uncertainty, SOIL, 7, 217–240, 2021.

Rautiainen, K., Holmberg, M., Cohen, J., Mialon, A., Schwank, M., Lemmetyinen, J., de la Fuente, A., and Kerr, Y.: An operational SMOS soil freeze–thaw product, Earth Syst. Sci. Data, 17, 5337–5353, https://doi.org/10.5194/essd-17-5337-2025, 2025.

[check: add references for AmeriFlux, BERMS, St-Marthe/St-Maurice, the iButton transects, Cambridge Bay, Chapleau, Dryden (Hanes et al., 2023, https://doi.org/10.1071/WF22112), TVC (Boike et al.), and the TVC HydraProbe stations.]
