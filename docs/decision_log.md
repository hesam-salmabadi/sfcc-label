# Decision log

Every method choice of the dataset and of the freeze/thaw classifier, with what else was considered, the
evidence, and who decided. "User" = project lead; "proposed" = suggested by the assistant and accepted by the
user. Numbers refer to the topsoil class unless stated. Dates are when the choice was settled; "sandbox" means
the prototyping phase before the classifier moved into the package on 2026-09-27.

Add new entries at the end of the relevant section; when a decision is reversed, keep the old entry and mark it
**superseded** with a pointer to the new one.

## A. Harmonised dataset

| # | Decision | Alternatives considered | Evidence / reason | Decided | Date |
|---|---|---|---|---|---|
| A1 | All timestamps in UTC, hourly means, no interpolation | keep source clocks; interpolate gaps | one time base across sources; no invented values | user | before 2026-09-27 |
| A2 | No new anomaly QA/QC; keep ISMN and AmeriFlux provider flags in sidecars | own spike/range filters | leave cleaning choices to users; provider flags documented | user | before 2026-09-27 |
| A3 | Every physical sensor its own stream; pair temperature and moisture only at a documented same depth | pair nearest depths | avoids mixing depths (AmeriFlux: one TS + one SWC at the same depth; ISMN: same instrument/position, then unique depth match) | user | before 2026-09-27 |
| A4 | Replace derived "local" copies with original publisher data | keep local copies | value-by-value checks; superseded files archived | user | before 2026-09-27 |
| A5 | Sensor ids `<src>_<site>_<depth>_<tag>`; place-named iButton sources (`james_bay`, `montmorency`, `kuujjuarapik`) | per-importer ids; "uqam" folder name | consistent, case-insensitive-unique ids; the lab name carries no meaning for the data | user | 2026-09-27 |
| A6 | SoilGrids 2.0 (250 m) for every sensor, one layer per sensor by depth (no blending) | local soil descriptions where available; blended layers | uniform coverage; local descriptions exist for few sites | user | 2026-09-27 |
| A7 | Unknown AmeriFlux depths get the layer most common for their vertical index | leave soil empty | 332 sensors; rule and share recorded in `depth_note` | proposed | 2026-09-27 |
| A8 | EASE-Grid 2.0, all ten N and M grids (6.25–36 km) | only N25km | users pick the grid of their satellite product | user | 2026-09-27 |
| A9 | ESA CCI Land Cover 2015 (300 m) merged to the six SMOS classes | MODIS MCD12Q1 (annual) | same classes as the SMOS F/T algorithm; finer; real wetland class; MODIS calls much boreal forest savanna; site land cover changes little | user | 2026-09-27 |
| A10 | SMOS-style representativeness screen per sensor: own class = cell's dominant class, dominant ≥ 70 %, water ≤ 5 %, other ≤ 5 % | earlier MODIS gate; SMOS's cell-level 70 % test | matches SMOS validation; per-sensor so each sensor gets its own flag | user | 2026-09-27 |
| A11 | Moss/lichen layer **rejected** | CGLS-LC100 moss/lichen cover | top-of-canopy product; only 68 of 17,090 sensor pixels had any cover (≈ 0 % in lichen woodland); SOC and Histosols probability used as organic-layer proxies | user | 2026-09-27 |
| A12 | James Bay local files: TEROS12 only; iButton gap-fill and averaging removed | keep level-0 files | level-0 files mixed iButton values into TEROS12 records; originals in `archive/local_bj_ibutton_fill_20260928/` | user | 2026-09-28 |
| A14 | Keep the detailed ESA CCI class (`cci_class`, names in `landcover_cci.CCI_NAMES`) beside the six SMOS classes | six classes only | one "forest" class hides needleleaf/broadleaf/mixed; tundra cover (lichens and mosses, sparse) was lumped with grassland | user | 2026-09-29 |
| A15 | RESOLVE Ecoregions 2017 biome and ecoregion per sensor (`metadata/sensor_biome.csv`); points outside every polygon snap to the nearest within 5 km (17 sensors, ≤ 2.8 km) | Köppen–Geiger climate; no biome | ESA CCI has no climate information, so it cannot separate boreal from temperate forest or tundra from prairie; biome names are directly interpretable | user | 2026-09-29 |
| A13 | ISMN records are not redistributed; derived tables stay private | publish derived tables | ISMN licence | user | — |

## B. Freeze/thaw classifier — scope and inputs

| # | Decision | Alternatives considered | Evidence / reason | Decided | Date |
|---|---|---|---|---|---|
| B1 | Output: hourly P(thawed), P(transition), P(frozen) plus yearly dates | binary frozen/thawed; daily only | transition state is physically real (Salmabadi 2026); probabilities carry uncertainty | user | sandbox |
| B2 | No "never frozen" label; years without freezing simply have no frozen hours | explicit never-frozen class | user: the label is meaningless | user | sandbox |
| B3 | Work in permittivity–temperature space (SFCC, Salmabadi 2026) | temperature threshold (0 °C); VWC | permittivity responds directly to ice; a 0 °C rule gave freeze-start errors of 3 days median vs 0.5 days (synthetic benchmark) | user | sandbox |
| B4 | VWC-only sensors: invert Topp et al. (1980) to pseudo-permittivity | skip VWC sensors; use VWC directly | keeps most ISMN/AmeriFlux sensors; the frozen fraction is a ratio, so a calibration offset largely cancels | proposed | sandbox |
| B5 | Freeze year 1 Aug–31 Jul, freezing leg = 1 Aug to the coldest day | calendar year; whole winter | snowmelt infiltration and thaw hysteresis never enter the fit | user | sandbox |
| B6 | Topsoil class 2.5 cm < depth < 7.5 cm; skin (0–2 cm) and deeper classes postponed | 2–7 cm; all depths together | user definition; priors and fallbacks derived for this class only | user | 2026-09-27/28 |
| B7 | ISMN probes integrating 0–5 cm are topsoil; point sensors at exactly 2.5 cm stay out | exclude all 2.5 cm | the 0–5 cm probes (291) sense the topsoil layer | user | 2026-09-28 |
| B9 | Probes integrating any other layer (0–10 cm: 26, e.g. Chapleau moisture probes without paired temperature; 0–8 cm: 2; 0–7.5 cm: 1) are not topsoil | classify layers by their midpoint | layers reaching below 5 cm do not represent the topsoil; topsoil now 3,942 sensors | user | 2026-09-28 |
| B8 | Day valid for fitting with ≥ 50 % of the logger's possible readings (≥ 75 % for daily labels); ≥ 30 valid days per winter | count hours | works for hourly and 3-hourly loggers alike | proposed | sandbox |

## C. Curve and thresholds

| # | Decision | Alternatives considered | Evidence / reason | Decided | Date |
|---|---|---|---|---|---|
| C1 | Frozen fraction F = (√ε_u − √ε)/(√ε_u − √ε_r) (α = 0.5 mixing) | linear in ε | standard dielectric mixing; used by Cohen 2021 | proposed | sandbox |
| C2 | Bai et al. (2018) curve with free onset T_f | logistic (Pardo Lara 2020); Bai with T_f = 0 °C | Bai shape fitted better in 83 % of 1,326 winters (84 % topsoil); free T_f absorbs freezing-point depression and probe offsets | proposed, user agreed | sandbox |
| C3 | Thresholds at F = 0.10 (T_on, Cohen 2021) and 0.75 (T_fr, Salmabadi 2026) | 0.05/0.75; 0.10/0.90 | user's TC paper uses 0.75; Cohen's one-tenth rule; product-defined, not physical | user | sandbox |
| C4 | 0.1 °C temperature bins, median √ε per bin, ≥ 3 readings (≥ 2 for slower loggers) | fit raw readings | equal weight per temperature, not per hour spent there | user | sandbox |
| C5 | Unfrozen level ε_u = median of bins between +0.8 and +2.5 °C | fixed date window; warmer window | clear of onsets up to ~+0.7 °C (probe offsets); close to the pre-freeze moisture | proposed | sandbox |
| C6 | Fit range −4 to +2.5 °C | fit to −10 °C | user: −4 °C is enough for the transition; colder bins add little | user | sandbox |
| C7 | Frozen level ε_r fitted jointly with T_on and width, prior ε_r/ε_u ~ N(0.44, 0.14) | fixed ε_r 3–5 (tried, wrong for clay); take lowest bin; SoilGrids regression | fixed value failed in clay; regression cut LOSO error only 1.16 → 1.01 units, kept optional (`SoilPrior`) | user ("go with A and B") | sandbox |
| C8 | Width prior ln(T_on − T_fr) ~ N(ln 1.45, 0.7) | no prior | stabilises mild winters; 1.45 °C = median width of winters with a seen frozen level (1.51 in the current fit) | proposed | sandbox |
| C9 | Frozen level "seen" rule: soil ≤ −5 °C, flat run of coldest bins (within 10 % of the √ε drop, ≥ 0.5 °C long), drop > 3 units, ε_r ≥ 2 | −4 °C; Lara's 3.8-unit range | −4 °C gives the same median (0.45); 3 vs 3.8 changes the median 0.45 → 0.43; ε_r ≥ 2 follows the ~2.3 instrument minimum (Pardo Lara 2020) | user kept 3 | 2026-09-28 |
| C10 | Fitted ε_r may not exceed the lowest bin by more than 5 % | unbounded | the soil cannot be less frozen than at its coldest | proposed | sandbox |
| C11 | Five acceptance checks: enough bins; froze ≥ 15 % of the expected drop; no parameter at a limit; cold-side misfit ≤ 30 % of the drop; ≥ 50 % of bootstrap rounds succeed | trust every fit; slope "flat" test; trust rule (and a −5 °C variant) | slope and trust rules performed worse on the synthetic benchmark | proposed | sandbox |

## D. Slow freezes

| # | Decision | Alternatives considered | Evidence / reason | Decided | Date |
|---|---|---|---|---|---|
| D1 | Width > 90th percentile of reference widths → keep T_on, T_fr = T_on − donor width | keep wide curves; fixed cut-off | wide curves put T_fr far below the data | proposed, user agreed | 2026-09-27 |
| D2 | Reference = fitted winters with a seen frozen level (cut 3.07 °C, 339 of 4,846 winters) | winters ≥ 1 °C past their own fitted T_fr (cut 2.87 °C) | only there is the whole curve measured; median width 1.51 matches the prior | user | 2026-09-28 |
| D3 | No exemptions (dry or clay soils) | exempt ε_u ≤ 6 or clay > 35 % | user: any super-slow freeze is suspicious. Dry soils are slow more often (16 % vs 2 % wet); SoilGrids clay shows no link | user | 2026-09-28 |
| D4 | Donor order: sensor → network × probe → probe → land cover × soil → all; ≥ 3 donors | global only | same order as the fallback chain | proposed | 2026-09-27 |

## E. Uncertainty

| # | Decision | Alternatives considered | Evidence / reason | Decided | Date |
|---|---|---|---|---|---|
| E1 | Day-block bootstrap, 200 rounds, whole selection and fit redone each round | residual bootstrap; resample hours | hours within a day are not independent; redoing everything avoids mode mixing (found in Codex review) | proposed | sandbox |
| E2 | Prior centres re-drawn every bootstrap round | fixed priors | error bars were too narrow where the prior dominates | proposed | sandbox |
| E3 | Extra sd 0.10 °C on T_on; on T_fr 0.2 / 0.5 / 1.0 °C for winters ≥ 1 °C past / < 1 °C past / never past T_fr | none | calibrated so 95 % intervals reach nominal coverage (96 % T_on, 90 % T_fr on the synthetic benchmark) | proposed | sandbox |
| E4 | Minimum sd 0.1 °C | none | thermometer resolution; user agreed | user | sandbox |
| E5 | Monte Carlo 400 draws with 0.1 °C thermometer noise; ±0.5 °C accuracy not added | add probe accuracy | probe offsets are already inside the fitted thresholds | proposed, user agreed | sandbox |
| E6 | Pairs with T_fr ≥ T_on redrawn | clip | clipping produced negative probabilities (Codex review) | proposed | sandbox |
| E7 | DerSimonian–Laird pooling of winters per sensor, each winter keeps its own sd | independent winters; full shrinkage | frozen-level errors are shared by a sensor's winters | proposed | sandbox |

## F. Sensors or years without a fit

| # | Decision | Alternatives considered | Evidence / reason | Decided | Date |
|---|---|---|---|---|---|
| F1 | Fallback chain: own winter → sensor's other winters → network × probe → probe → network, other probe → land cover × soil texture (≥ 3 sensors) → all; within one depth class | global mean; "biome" | LOSO on 1,251 winters: network × probe best (T_on 0.22 vs 0.34 °C global) | proposed, user agreed | 2026-09-27 |
| F2 | **Superseded by F6.** Land cover × USDA texture as the "biome" level | ESA CCI alone; clay class alone; Köppen | best land-cover/soil grouping for topsoil (T_on 0.22 vs 0.29 °C); either alone added little | user | 2026-09-27 |
| F3 | +0.16 °C for levels that may mix probe types; no offset correction | correct TEROS12–iButton offset | James Bay zero-curtain test at 8 co-located sites: +0.02 ± 0.16 °C; only pair available | proposed, user agreed | 2026-09-27 |
| F5 | A sensor's own average competes with the first available group level; the smaller combined T_on/T_fr uncertainty wins | own average always first | Kenaston EC14: two winters 1.1 °C apart gave own average T_on ± 0.97 vs network + probe ± 0.17 | user | 2026-09-28 |
| F6 | Environment fallback level = RESOLVE biome × USDA texture (≥ 3 sensors) | land cover × texture (F2); biome × land cover × texture; biome × CCI detailed | LOSO on 4,507 topsoil winters at 978 sites: biome × texture T_on 0.26 / T_fr 0.43 °C vs land cover × texture 0.27 / 0.44; biome × land cover × texture similar (0.255 / 0.433) but matches fewer sensors (94 vs 97 %); network × probe still best (0.24 / 0.42) | user | 2026-09-29 |
| F4 | Probe families (METER together, both HydraProbes together, iButton, PT100, …) | exact models | too few sensors per exact model | proposed | 2026-09-27 |

## G. Hourly output and dates

| # | Decision | Alternatives considered | Evidence / reason | Decided | Date |
|---|---|---|---|---|---|
| G1 | Same thresholds in spring; hourly `leg` column marks freezing/thawing | separate thaw thresholds; drop spring | no reliable way to fit thaw curves (meltwater); users can filter | user | 2026-09-27 |
| G2 | Daily label = majority of hourly labels (days with ≥ 75 % of readings) | mean probability | simple, matches SMOS daily product | proposed | sandbox |
| G3 | Freeze start / transition onset: first day ≤ 1 Mar starting ≥ 5 frozen / not-thawed days (Rautiainen 2025) | first frozen hour | same rule as SMOS F/T | user | sandbox |
| G4 | Freeze end: first thawing-leg day starting ≥ 5 thawed days, only for years with an onset | none (SMOS defines no spring date) | mirrors the autumn rule; wet snow limits SMOS, not in situ | user | 2026-09-28 |
| G5 | Gradual (logistic-like) onset: documented limitation, no correction | switch shape per winter | ~16 % of winters favour logistic; clearest real cases were uneven data above 0 °C, not gradual onsets | user | 2026-09-28 |
| G6 | Retrospective product (thresholds use the whole freezing leg) | near-real-time | better thresholds; not an operational product | proposed | sandbox |
| G7 | Predictions as `.csv.gz`; manifest records git commit, settings and version | plain CSV | size; reproducibility | user | 2026-09-27 |

## Open

See [classification_todo.md](classification_todo.md): skin and deeper depth classes, the 56 point sensors at
2.5 cm, cross-probe uncertainty beyond James Bay, the optional soil-based frozen-level prior.
