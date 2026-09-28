# Methods: probabilistic soil freeze/thaw state from in situ observations

*Draft methods text for model version `sfcc-joint-1.0` (`src/sfcc_label/classify.py`). A plain-language
walk-through is in [classification_pipeline.md](classification_pipeline.md).*

## Soil freezing characteristic curve in permittivity–temperature space

The phase state of soil water is characterised with a soil freezing characteristic curve (SFCC) in
permittivity–temperature space (Salmabadi et al., 2026). Bulk permittivity ε is reduced to a normalised
frozen fraction using a power-law dielectric mixing model with α = 0.5,

$$F = \frac{\sqrt{\varepsilon_u} - \sqrt{\varepsilon}}{\sqrt{\varepsilon_u} - \sqrt{\varepsilon_r}}, \tag{1}$$

where ε_u and ε_r are the unfrozen and fully frozen (residual) permittivities. Following Bai et al. (2018),

$$F(T) = \begin{cases} 1 - \exp[b\,(T - T_f)] & T < T_f \\ 0 & T \ge T_f. \end{cases} \tag{2}$$

Bai et al. (2018) derived Eq. (2) with the freezing point of free water as the onset (T_f = T₀) and b as the
only fitted parameter; following Salmabadi et al. (2026), T_f is treated as a free parameter here because
field probes register freezing at temperatures shifted by freezing-point depression and thermistor offsets.

The curve is parametrised by the temperatures at which F reaches q_on = 0.10 and q_fr = 0.75,

$$b = \frac{\ln(1-q_{on}) - \ln(1-q_{fr})}{T_{on} - T_{fr}}, \qquad T_f = T_{on} - \frac{\ln(1-q_{on})}{b}, \tag{3}$$

and T_on and T_fr are used directly as class boundaries: thawed above T_on, frozen below T_fr, transitional
in between. The onset level follows the one-tenth rule of Cohen et al. (2021); the frozen level follows the
0.75 criterion of Salmabadi et al. (2026). These fractions are choices of this product, not physical
constants. Across 1,326 real winters, Eq. (2) fitted the binned data better than a logistic curve through the
same thresholds (Pardo Lara et al., 2020) in 83 % of cases (median RMS misfit 0.070 vs 0.096 in F units).

## Data preparation

Hourly soil temperature and permittivity were used as harmonised (UTC). Values outside −60…60 °C and outside
1…90 (permittivity) were discarded. For ISMN records, only temperatures with a good (`G`) flag were used and
soil-moisture range and spike flags were applied. Where only volumetric water content θ was available,
permittivity was obtained by numerically inverting the Topp et al. (1980) polynomial; because θ may already
carry a sensor- or soil-specific calibration, this quantity is a pseudo-permittivity.

Records were split into freeze years (1 August–31 July). Curves were fitted to the freezing half of each
year, from 1 August to the day with the lowest daily-mean soil temperature, excluding snowmelt infiltration and
thaw hysteresis. Days were retained if they contained at least half of the readings possible for the
sensor's native logging interval, and a winter required at least 30 such days. Readings were binned by soil
temperature at 0.1 °C and summarised by the median √ε (bins with ≥ 3 readings; ≥ 2 for loggers slower than
hourly), which equalises the weight of temperature ranges irrespective of residence time.

## Joint estimation of the curve and the residual level

ε_u was the median of bins between +0.8 and +2.5 °C. T_on, the width w = T_on − T_fr and the frozen
fraction f = ε_r/ε_u were estimated jointly by bounded least squares on √ε in the bins between −4 and
+2.5 °C, with residuals scaled by the robust scatter of the unfrozen bins and two prior penalty terms:
f ~ N(0.44, 0.14²) and ln w ~ N(ln 1.45, 0.7²). The priors were derived from 1,324 real winters at 320 sites
that reached below −5 °C and showed a clear residual plateau (frozen/unfrozen permittivity ratio: median
0.44, 10th–90th percentile 0.24–0.60; median 10–75 % width 1.45 °C). The prior on f was preferred over a
regression on SoilGrids clay, organic carbon, bulk density and probe type, which reduced the
leave-one-site-out error only marginally (median absolute error 1.01 vs 1.16 permittivity units); that
regression is retained as an optional prior. Fits were rejected when the winter showed less than 15 % of the
expected drop, when a parameter reached a bound, or when the RMS misfit of bins colder than T_on + 0.3 °C
exceeded 30 % of the fitted drop.

Winters whose fitted width T_on − T_fr exceeded the 90th percentile of well-observed widths in the run
(winters whose minimum soil temperature was at least 1 °C below T_fr) were treated as slow freezes whose
curve shape does not constrain T_fr. For these, T_on was retained and T_fr was set to T_on minus the median
width of donor winters (well-observed and not slow), taken from the first level with at least three donors:
the same sensor, the same network and temperature-probe type, the same probe type, or all winters; the
donors' standard deviation was propagated into T_fr. Slow freezes were more frequent in dry soils (volumetric
water content ≤ 0.15: 26–30 % of winters favoured a gradual curve vs 14–18 % otherwise) and in clay-rich
soils (> 35 % clay: 31 %).

## Uncertainty and pooling

Parameter uncertainty was estimated with a day-block bootstrap (200 replicates): whole days were resampled
with replacement, binning and fitting were repeated, and the prior centres were re-drawn from their own
distributions in every replicate so that prior uncertainty propagates where the data are uninformative. A
winter was accepted when at least half of the replicates converged; thresholds are the replicate medians and
their uncertainty the replicate standard deviations. Winters without an accepted fit borrowed thresholds from, in order, the same sensor's other winters, sensors
of the same network and temperature-probe family, the same probe family in any network, the same network
with other probes, sensors sharing the ESA CCI land-cover group and SoilGrids USDA texture class (at least three
sensors), and all sensors of the same depth class. Because fitted thresholds include each probe's thermistor offset, the last
two levels add 0.16 °C, the standard deviation of TEROS12 − iButton differences on zero-curtain plateaus at
eight co-located James Bay sites (mean +0.02 °C, hence no offset correction). In a leave-one-site-out test on
1,251 winters, network × probe type gave the lowest prediction error for T_on, T_fr and width (e.g. T_on
0.22 °C vs 0.34 °C for a global median), whereas ESA CCI land cover or SoilGrids clay class alone added little; for topsoil sensors, land cover × USDA
texture class was the best land-cover/soil grouping (T_on 0.22 °C vs 0.29 °C without grouping). Only sensors
with 2.5 cm < depth < 7.5 cm (topsoil class) were processed.

Winter estimates were shrunk toward the sensor mean with
a DerSimonian–Laird random-effects model (DerSimonian and Laird, 1986) while retaining each winter's own
standard deviation, because errors in the residual level are shared by all winters of a sensor. Sensor means
were combined into network means in the same way.

Additional error terms were calibrated on a realistic synthetic benchmark (below) so that 95 % intervals
reach nominal coverage: 0.10 °C on T_on, and on T_fr 0.2, 0.5 or 1.0 °C when the winter's minimum temperature
was at least 1 °C below, less than 1 °C below, or above the estimated T_fr. A minimum standard deviation of
0.1 °C (thermometer resolution) was applied.

## Hourly state probabilities and annual dates

For each hour, 400 Monte Carlo draws combined an ordered (T_on, T_fr) pair — from the winter's rescaled
bootstrap distribution, or from normal distributions of the sensor or network average when the winter was not
fitted — with thermometer noise, T_sim ~ N(T_obs, 0.1²). Class probabilities are the fractions of draws that
are thawed (T_sim > T_on), frozen (T_sim < T_fr) or transitional; the mean of F(T_sim) gives the expected
frozen fraction, equivalent to the freezing probability of Salmabadi et al. (2026).

Each hour was assigned to the freezing leg (1 August to the freeze year's day of minimum daily-mean soil
temperature) or the thawing leg (after that day); thresholds are the same in both legs, and the leg is reported
so that spring (thaw, snowmelt infiltration) can be analysed or excluded separately.

Daily states were assigned by majority of hourly most-likely labels, for days with at least 75 % of possible
readings. Following Rautiainen et al. (2025), the freeze start is the first day (on or before 1 March) that
begins at least five consecutive frozen days; transition onset uses the same rule for the non-thawed state. The freeze end is the first day of
the thawing leg that begins at least five consecutive thawed days (years with a transition onset only);
Rautiainen et al. (2025) define no spring date because wet snow masks soil thaw at L-band, so this rule mirrors
the autumn definition.
Thresholds use the whole freezing half, so the product is retrospective rather than near-real-time.

## Evaluation

**Synthetic benchmark.** Fake sensors (5 winter minima from −8 to −0.4 °C × slow/fast freezing ×
replicates, three winters each) took their true thresholds, unfrozen permittivity and frozen fraction from
randomly chosen real winters; half were generated with Eq. (2) and half with a logistic curve. Hourly data
included thermometer noise (0.1 °C), permittivity noise, diurnal and synoptic variability and autumn moisture
drift. For Bai-shaped truth, the median absolute error was 0.05 °C for T_on and 0.13 °C for T_fr, 91 % of hours
between −2 and +2 °C were labelled correctly, and 95 % intervals covered the truth in 96 % (T_on) and 90 %
(T_fr) of winters; freeze-start dates had a median error of 0.5 days (90th percentile 6 days), compared with
3 and 21.5 days for a 0 °C rule. For logistic-shaped truth, T_on was biased by about −0.25 °C.

**Real networks.** Applied to three local networks (31 sensors, 51 sensor-winters), 37 winters were fitted.
Network means were T_on +0.73 / T_fr −0.05 °C (James Bay, TEROS12), +0.32 / −0.29 °C (Montmorency Forest,
TEROS12) and 0.00 / −1.19 °C (Candle Lake, HydraProbe). Eastern boreal sites remained predominantly
transitional through winter, while Candle Lake froze from December to April, consistent with
Salmabadi et al. (2026).

## Limitations

Cross-probe uncertainty was measured at a single network; the freezing-season thresholds are also applied in
spring (flagged by the leg); gradually freezing
(logistic-like) soils are represented less well; and very dry soils with small permittivity drops rely more
strongly on the priors.

## References

- Bai, R., Lai, Y., Zhang, M., Yu, F. (2018). Theory and application of a novel soil freezing characteristic curve. *Applied Thermal Engineering*, 129, 1106–1114.
- Cohen, J., Rautiainen, K., Lemmetyinen, J., Smolander, T., Vehviläinen, J., Pulliainen, J. (2021). Sentinel-1 based soil freeze/thaw estimation in boreal forest environments. *Remote Sensing of Environment*, 254, 112267.
- DerSimonian, R., Laird, N. (1986). Meta-analysis in clinical trials. *Controlled Clinical Trials*, 7, 177–188.
- Pardo Lara, R., Berg, A. A., Warland, J., Tetlock, E. (2020). In situ estimates of freezing/melting point depression in agricultural soils using permittivity and temperature measurements. *Water Resources Research*, 56, e2019WR026020.
- Rautiainen, K., et al. (2025). An operational SMOS soil freeze–thaw product. *Earth System Science Data*, 17, 5337–5353.
- Salmabadi, H., et al. (2026). In situ monitoring of seasonally frozen ground using soil freezing characteristic curve in permittivity–temperature space. *The Cryosphere*, 20, 1635–1654.
- Topp, G. C., Davis, J. L., Annan, A. P. (1980). Electromagnetic determination of soil water content. *Water Resources Research*, 16, 574–582.
