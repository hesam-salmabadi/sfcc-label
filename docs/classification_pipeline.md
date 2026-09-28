# Freeze/thaw classification — step by step

Model version **`sfcc-joint-1.0`**, implemented in `src/sfcc_label/classify.py` and run with
`sfcc-label classify`. This page explains the method in plain terms. The formal description is in
[classification_methods.md](classification_methods.md).

Running example: **BJ06, winter 2021–22** (James Bay, TEROS12 at 5 cm, raw permittivity).

## What goes in and what comes out

**In:** for every sensor, the standardized hourly file (soil temperature plus a wetness signal) and its
catalog row (source, network, `raw_variable`).

| wetness signal | how it is used |
|---|---|
| raw bulk permittivity (`bulk_edc`, `bulk_permittivity`) | used directly |
| volumetric water content only (ISMN, AmeriFlux, …) | converted to (pseudo-)permittivity with the inverted Topp et al. (1980) equation |
| none (temperature-only loggers) | nothing to fit; the sensor borrows thresholds (step 9) |

**Out** (in the chosen output folder):

| file | content |
|---|---|
| `thresholds.csv` | one row per sensor-winter: probe type, status, T_on, T_fr and their uncertainty, unfrozen and frozen permittivity, fit misfit, slow-freeze flag and where T_fr came from |
| `predictions/<sensor>.csv.gz` | every hour (gzip-compressed): P(frozen), P(transition), P(thawed), most likely label, **leg** (freezing / thawing), mean frozen fraction, and where the thresholds came from |
| `yearly_events.csv` | per freeze year: transition onset, freeze start and freeze end |
| `manifest.json` | model version, depth class, git commit, all settings, counts, errors, fallback averages |

## Which sensors
Only sensors in the **topsoil class, 2.5 cm < depth < 7.5 cm, plus probes that integrate 0–5 cm** (3,971 sensors: 3,680
point sensors, mostly 5 cm and 5.08 cm, and 291 ISMN 0–5 cm probes),
are processed; this is the class the method was developed and evaluated for. The surface skin (0–2 cm) and
deeper sensors are on the to-do list ([classification_todo.md](classification_todo.md)). Fallback averages
are always computed within one depth class, so classes never borrow from each other.

## Step 1 — Clean
Temperatures outside −60…60 °C and permittivities outside 1…90 are removed. For ISMN, only temperature
flagged `G` is kept, and soil-moisture range/spike flags (`C0x`, `D06`) are removed; frozen-soil advisory
flags are kept because frozen hours are what we need.

## Step 2 — Freeze years and the freezing half
A freeze year runs **1 Aug → 31 Jul**. For fitting, only the **freezing half** is used: 1 Aug to the
coldest day. Spring (meltwater, thaw) never enters the fit.

A day counts only if it has at least half of the readings the logger can make (hourly logger: 12 of 24;
3-hourly: 4 of 8). A winter needs at least 30 such days.

## Step 3 — Bin by temperature
Every reading's temperature is rounded to the nearest 0.1 °C. Readings with the same rounded temperature are
grouped (whatever the date) and the **median √permittivity** of each group becomes one point.
Groups need ≥ 3 readings (≥ 2 for loggers slower than hourly).

Example: readings at 0.28, 0.31, 0.26, 0.33 °C with ε 11.2, 11.0, 11.4, 10.1 → one point at 0.3 °C, ε ≈ 11.1.

## Step 4 — Unfrozen level
Median of the points between **+0.8 and +2.5 °C**. BJ06: **ε ≈ 11.8**.

## Step 5 — Fit the freezing curve
The frozen fraction F (0 = unfrozen, 1 = fully frozen) is measured between the unfrozen level and the frozen
level on the √ε scale. The curve has the Bai shape (sharp start, slow approach to fully frozen), which fitted
real curves better than a logistic shape in 83 % of 1,326 real winters.

**One fit finds three things at once:**
- **T_on** — temperature where the soil is 10 % frozen (onset; Cohen et al. 2021)
- **T_fr** — temperature where the soil is 75 % frozen (Salmabadi et al. 2026)
- the **frozen level** (fully frozen permittivity)

Two soft anchors keep the fit sensible when the winter's data cannot show everything:
- frozen level ≈ **0.44 × unfrozen permittivity** (± 0.14; from 1,326 real winters at 492 sensors),
- curve width T_on − T_fr ≈ **1.45 °C** (real median).

Where the cold data show the curve clearly, the data win; where they do not (mild winters), the anchors keep
the answer reasonable and the uncertainty grows.

A winter is **not fitted** when:
- it barely froze (less than 15 % of the expected drop) → `barely_frozen`,
- the fit ran into a limit → `parameter_at_bound`,
- the curve misses the cold-side points by more than 30 % of the drop → `poor_fit`,
- fewer than half of the bootstrap rounds (step 6) succeed → `unstable_bootstrap`.

**Slow freezes.** When a winter's fitted width (T_on − T_fr) is wider than 90 % of the well-observed winters
in the run (winters whose soil went at least 1 °C past T_fr; the cut-off was 3.2 °C in the first test run), the
curve has lost its shape: T_on is kept, but T_fr = T_on − a **donor width**. Donors are well-observed,
non-slow winters, taken from the first level with at least 3 of them: the same sensor's other winters → the
same network and probe type → the same probe type → the same land cover and soil texture → all. The donors' spread becomes T_fr's uncertainty and
`t_fr_source` records the level.

BJ06: frozen level ε ≈ 5.0; **T_on = +0.60 °C, T_fr = +0.16 °C** (positive values reflect the TEROS12
thermistor offset, as in Salmabadi et al. 2026).

## Step 6 — Uncertainty (bootstrap)
If the winter has 150 days, 150 days are drawn at random with replacement (some twice, some not at all),
steps 3–5 are redone, and the two anchors are re-drawn from their ranges. Repeating this 200 times gives
200 (T_on, T_fr) pairs; their median is the estimate and their spread the uncertainty.
BJ06: T_on ± 0.04, T_fr ± 0.13 °C.

## Step 7 — Pooling
Each winter's thresholds are pulled slightly toward the average of that sensor's fitted winters, but each
winter keeps its own uncertainty. Sensor averages are combined into a network average.

## Step 8 — Extra uncertainty
To make the error bars honest (checked on a realistic synthetic benchmark), extra uncertainty is added:
+0.1 °C on T_on; on T_fr +0.2 °C if the winter went ≥ 1 °C colder than T_fr, +0.5 °C if it only just passed
it, +1.0 °C if it never reached it (extrapolated).

## Step 9 — Which thresholds each hour uses

| order | source | extra uncertainty |
|---|---|---|
| 1 | this freeze year's own fit | — |
| 2 | the same sensor's other fitted winters (earlier or later) | — |
| 3 | sensors in the same network with the same temperature-probe type | — |
| 4 | sensors with the same probe type in any network | — |
| 5 | sensors in the same network with another probe type | ± 0.16 °C |
| 6 | sensors with the same land cover (ESA CCI) and soil texture class (SoilGrids), ≥ 3 sensors | ± 0.16 °C |
| 7 | all fitted sensors | ± 0.16 °C |

Probe types are grouped into families (all METER probes together, both HydraProbe versions together,
iButton, PT100, …) from the catalog, the ISMN file names or the local network table. Thresholds include each
probe's thermistor offset, which is why the order prefers the same probe type. The ± 0.16 °C is the measured
spread between TEROS12 and iButton readings at eight co-located James Bay sites (zero-curtain plateaus: mean
difference +0.02 °C, so no correction is applied). A leave-one-site-out test on 1,251 winters showed that
network × probe type predicts thresholds best. For topsoil sensors, land cover × soil texture class was the
best of the land-cover/soil groupings (typical T_on miss 0.22 °C vs 0.29 °C with no grouping), so it serves
temperature-only networks that have no fitted sensors of their own (e.g. St-Marthe, Cambridge Bay).

## Step 10 — Hourly probabilities
For every hour, 400 draws: pick a (T_on, T_fr) pair, add ± 0.1 °C thermometer noise to the measured
temperature, then call it thawed (warmer than T_on), frozen (colder than T_fr) or transition. The shares are
the probabilities. The same draws give the mean frozen fraction (the P_frozen of Salmabadi et al. 2026).

BJ06, 28 Feb 2022 23:00, soil at +0.31 °C: P(frozen) 0.14, **P(transition) 0.85**, P(thawed) 0.01.

## Step 11 — Freezing or thawing leg
Each hour gets a `leg`: **freezing** from 1 Aug to the freeze year's coldest day (daily mean soil
temperature), **thawing** from the next day to 31 Jul. The same thresholds are used in both legs; the column
lets users separate autumn freezing from spring thawing (e.g. meltwater periods near 0 °C).

## Step 12 — Yearly dates
Each day gets the label most of its hours have (days need ≥ 75 % of the logger's readings).
Within 1 Aug – 1 Mar:
- **freeze start** = first day of the first run of ≥ 5 frozen days (day of first freezing, Rautiainen et al. 2025),
- **transition onset** = the same rule for "not thawed";
- **freeze end** = first day of the thawing leg (after the coldest day) that begins ≥ 5 thawed days, for years
  with a transition onset. The SMOS paper defines no spring date (wet snow masks the soil from the satellite),
  so this mirrors the autumn rule.

## Running it

```bash
python -m pip install -e '.[classify]'
sfcc-label classify --output-dir /path/to/private-data/processed/sfcc-joint-1.0 \
  --source local --network "James Bay" --workers 8
```

Defaults read `metadata/catalog.csv`, `standardized/` and `flags/` under `SFCC_DATA_ROOT`. The output folder
must be new or empty. `--bootstrap` and `--seed` set the number of bootstrap rounds and the random seed.

## Known limitations
- In ~16 % of topsoil winters a gradual (logistic) curve fits slightly better; there the gradual curve puts
  T_on 0.1–0.7 °C warmer than ours. In the clearest real cases the difference comes from uneven data just
  above 0 °C (rain or drift steps) rather than a genuinely gradual onset, so no correction is applied.
- Spring uses the freezing thresholds; the `leg` column marks those hours as thawing.
- Cross-probe transfer adds ± 0.16 °C, measured only at James Bay (TEROS12 vs iButton).
- Very dry soils (e.g. Candle Lake sand, unfrozen ε 3–5) have small permittivity drops; their thresholds lean
  more on the anchors.
- The optional soil-based frozen-level prior (`SoilPrior`, SoilGrids + probe type) is included but not used by
  default.
