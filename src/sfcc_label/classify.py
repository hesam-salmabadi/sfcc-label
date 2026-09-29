"""Probabilistic soil freeze/thaw state from soil temperature and permittivity.

Method (see docs/classification_methods.md):

1. Each freeze year (1 Aug - 31 Jul) is fitted on its freezing half (1 Aug to the coldest day), using days
   with enough paired temperature/wetness readings for the sensor's own logging interval.
2. Hours are binned by soil temperature (0.1 degC, median sqrt-permittivity per bin). Volumetric water content
   is converted to (pseudo-)permittivity with the inverted Topp et al. (1980) equation.
3. The unfrozen level is the median of the +0.8..+2.5 degC bins. A Bai-type soil freezing curve is fitted
   jointly for the onset T_on (10 % frozen), the frozen threshold T_fr (75 % frozen) and the frozen level,
   anchored by a frozen-fraction prior (0.44 +- 0.14 of the unfrozen permittivity) and a width prior
   (1.45 degC). Fits whose cold-side misfit exceeds 30 % of the permittivity drop are rejected.
4. A day-block bootstrap (anchors re-drawn in every round) gives the threshold uncertainty; winters are
   pooled toward the sensor mean without shrinking their uncertainty; unfitted winters borrow the sensor or
   network average.
5. Hourly class probabilities come from Monte Carlo draws of (T_on, T_fr) and thermometer noise; annual
   dates use the majority daily label and a 5-day persistence rule.

Requires the optional ``classify`` dependencies (numpy, scipy, pandas).
"""

from __future__ import annotations

import copy
import zlib
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from .models import Observation, Prediction, SensorMetadata, YearlyFreezeEvent

MODEL_VERSION = "sfcc-joint-1.1"
# Depth classes (sensor depth_cm): the method is developed and evaluated for the topsoil class only.
# (lower, upper, lower inclusive, upper inclusive)
DEPTH_CLASSES = {"skin": (0.0, 2.0, True, False), "topsoil": (2.5, 7.5, False, False)}


# Probes that integrate a layer rather than measure at a point, assigned to a class by their layer.
LAYER_CLASSES = {(0.0, 5.0): "topsoil"}


def depth_class(depth_cm, depth_from_cm=None, depth_to_cm=None) -> str | None:
    """'skin' for 0 <= d < 2 cm, 'topsoil' for 2.5 < d < 7.5 cm, None otherwise (other or unknown depth).
    Probes that integrate a layer (depth_to > depth_from) are classed only by LAYER_CLASSES (0-5 cm -> topsoil)."""
    if depth_from_cm is not None and depth_to_cm is not None and np.isfinite(depth_from_cm) and np.isfinite(depth_to_cm):
        layer = (float(depth_from_cm), float(depth_to_cm))
        if layer in LAYER_CLASSES:
            return LAYER_CLASSES[layer]
        if layer[1] > layer[0]:
            return None
    if depth_cm is None or not np.isfinite(depth_cm):
        return None
    for name, (lower, upper, lower_in, upper_in) in DEPTH_CLASSES.items():
        if (depth_cm >= lower if lower_in else depth_cm > lower) and (depth_cm <= upper if upper_in else depth_cm < upper):
            return name
    return None
RAW_PERMITTIVITY = {"bulk_edc", "bulk_permittivity"}
CLASSES = ("thawed", "transition", "frozen")


@dataclass(frozen=True)
class Settings:
    """All tunable choices of the method, with the values used for MODEL_VERSION."""
    q_on: float = 0.10                       # onset: 10 % frozen (Cohen et al. 2021)
    q_fr: float = 0.75                       # frozen: 75 % frozen (Salmabadi et al. 2026)
    bin_width_c: float = 0.1
    min_bin_readings: int = 3                # 2 for loggers slower than hourly
    unfrozen_range_c: tuple = (0.8, 2.5)
    fit_range_c: tuple = (-4.0, 2.5)
    min_days: int = 30
    day_fit_share: float = 0.5               # share of a day's possible readings needed for fitting
    day_label_share: float = 0.75            # ... and for a daily label
    min_frozen_share: float = 0.15           # below this observed freezing, a winter is not fitted
    frozen_fraction: tuple = (0.44, 0.14, 0.10, 0.80)   # prior: mean, sd, lower, upper
    width_prior: tuple = (1.45, 0.7)         # prior: median width (degC), log-sd
    t_on_bounds_c: tuple = (-2.0, 1.5)
    max_cold_misfit: float = 0.3             # reject fits with cold-side RMS misfit > 30 % of the drop
    n_boot: int = 200
    min_boot_share: float = 0.5
    n_mc: int = 400
    thermometer_sd_c: float = 0.1
    se_floor_c: float = 0.1
    extra_sd_on_c: float = 0.10              # calibrated on the realistic synthetic benchmark
    extra_sd_fr_c: tuple = (0.2, 0.5, 1.0)   # winter went >=1 degC past T_fr / <1 degC past / never reached it
    persist_days: int = 5
    slow_width_quantile: float = 0.90        # winters wider than this quantile of reference widths are "slow"
    slow_width_default_c: float = 3.0        # used when fewer than 30 reference winters are available
    # reference winters = fitted winters whose frozen level is seen in the data (flat run of the coldest bins)
    seen_min_coldest_c: float = -5.0         # soil must reach this temperature
    seen_flat_tol: float = 0.10              # bins within this share of the observed sqrt(eps) drop ...
    seen_flat_span_c: float = 0.5            # ... over at least this temperature span
    seen_min_drop: float = 3.0               # eps_unfrozen - eps_frozen (permittivity units)
    seen_min_frozen_eps: float = 2.0         # below the instrument minimum (~2.3, Pardo Lara et al. 2020)
    min_donors: int = 3                      # donor winters needed at a fallback level
    cross_probe_sd_c: float = 0.16           # TEROS12 vs iButton spread at co-located James Bay sites
    seed: int = 0


# --- priors ----------------------------------------------------------------------------------
@dataclass
class FractionPrior:
    """Frozen permittivity = f x unfrozen permittivity, f ~ truncated normal."""
    mean: float = 0.44
    sd: float = 0.14
    lower: float = 0.10
    upper: float = 0.80

    def expected(self, eps_unf: float) -> float:
        return self.mean * eps_unf

    def penalty(self, eps_fr: float, eps_unf: float) -> float:
        return (eps_fr / eps_unf - self.mean) / self.sd

    def redrawn(self, rng: np.random.Generator) -> "FractionPrior":
        p = copy.copy(self)
        p.mean = float(np.clip(rng.normal(self.mean, self.sd), self.lower, self.upper))
        return p


# Optional soil/wetness regression for the frozen level (fitted on 1,324 trusted real winters at 320 sites;
# leave-one-site-out spread 0.32 in log units). Kept for later use; not the default prior.
SOIL_PRIOR_COEFFICIENTS = {
    "intercept": 1.09773, "log_eps_unf": 0.71468, "clay_per10": 0.03242, "log_soc": -0.23029,
    "bdod": -0.26178, "probe_meter": -0.14835, "probe_other": -0.38658, "signal_raw_eps": -0.34044,
    "sd_log": 0.31785,
}


@dataclass
class SoilPrior:
    """log(frozen permittivity) from wetness, SoilGrids clay / SOC / bulk density and probe type."""
    clay_pct: float
    soc_g_kg: float
    bdod_g_cm3: float
    probe: str = "hydraprobe"          # "hydraprobe" | "meter" | "other"
    raw_permittivity: bool = False
    shift: float = 0.0

    def _mu(self, eps_unf: float) -> float:
        c = SOIL_PRIOR_COEFFICIENTS
        return (c["intercept"] + c["log_eps_unf"] * np.log(eps_unf) + c["clay_per10"] * self.clay_pct / 10
                + c["log_soc"] * np.log(self.soc_g_kg) + c["bdod"] * self.bdod_g_cm3
                + c["probe_meter"] * (self.probe == "meter") + c["probe_other"] * (self.probe == "other")
                + c["signal_raw_eps"] * self.raw_permittivity + self.shift)

    def expected(self, eps_unf: float) -> float:
        return float(np.exp(self._mu(eps_unf)))

    def penalty(self, eps_fr: float, eps_unf: float) -> float:
        return (np.log(eps_fr) - self._mu(eps_unf)) / SOIL_PRIOR_COEFFICIENTS["sd_log"]

    def redrawn(self, rng: np.random.Generator) -> "SoilPrior":
        p = copy.copy(self)
        p.shift = float(rng.normal(0, SOIL_PRIOR_COEFFICIENTS["sd_log"]))
        return p


# --- inputs ----------------------------------------------------------------------------------
_EPS_GRID = np.linspace(1, 80, 4000)
_TOPP = -0.053 + 0.0292 * _EPS_GRID - 5.5e-4 * _EPS_GRID**2 + 4.3e-6 * _EPS_GRID**3


def topp_permittivity(theta) -> np.ndarray:
    """Pseudo-permittivity from volumetric water content (m3/m3) by inverting Topp et al. (1980)."""
    theta = np.asarray(theta, dtype=float)
    out = np.interp(theta, _TOPP, _EPS_GRID, left=np.nan, right=np.nan)
    return np.where(np.isfinite(theta), out, np.nan)


def read_standardized(path: str | Path, flags_path: str | Path | None = None) -> pd.DataFrame:
    """Hourly standardized CSV (and optional ISMN flag sidecar) as a UTC-naive DataFrame."""
    d = pd.read_csv(path, parse_dates=["timestamp_utc"]).set_index("timestamp_utc")
    d.index = d.index.tz_convert(None) if d.index.tz is not None else d.index
    if flags_path is not None and Path(flags_path).exists():
        f = pd.read_csv(flags_path, parse_dates=["timestamp_utc"]).set_index("timestamp_utc")
        f.index = f.index.tz_convert(None) if f.index.tz is not None else f.index
        d = d.join(f.reindex(d.index))
    return d


def sensor_frame(d: pd.DataFrame, raw_is_permittivity: bool) -> pd.DataFrame:
    """Columns T (degC) and g (sqrt permittivity) after range checks and ISMN flag screening."""
    T = d["soil_temperature_c"].where(d["soil_temperature_c"].between(-60, 60))
    theta = d["soil_moisture_m3_m3"]
    if "soil_temperature_ismn_flag" in d:
        T = T.where(d["soil_temperature_ismn_flag"].fillna("").str.startswith("G"))
    if "soil_moisture_ismn_flag" in d:
        flag = d["soil_moisture_ismn_flag"].fillna("")
        theta = theta.where(~(flag.str.contains("C0") | flag.str.contains("D06")))
    if raw_is_permittivity and d["raw_value"].notna().any():
        g = np.sqrt(d["raw_value"].where(d["raw_value"].between(1, 90)))
    else:
        g = pd.Series(np.sqrt(topp_permittivity(theta.where(theta.between(0, 0.8)))), index=d.index)
    return pd.DataFrame({"T": T, "g": g}, index=d.index)


def native_step_hours(index: pd.DatetimeIndex) -> float:
    """Typical time between readings, e.g. 1 for hourly and 3 for 3-hourly loggers."""
    if len(index) < 3:
        return 1.0
    return max(1.0, float(np.median(np.diff(index.values).astype("timedelta64[m]").astype(float))) / 60)


def readings_per_day(step_h: float, share: float) -> int:
    return max(2, int(np.ceil(share * 24 / step_h)))


def freeze_year(index: pd.DatetimeIndex) -> np.ndarray:
    return np.where(index.month >= 8, index.year, index.year - 1)


# --- one winter ------------------------------------------------------------------------------
def freezing_half(year_rows: pd.DataFrame, fyear: int, min_day: int, s: Settings) -> pd.DataFrame | None:
    """Paired rows from 1 Aug to the coldest paired day (searched before 1 Jul)."""
    pairs = year_rows.dropna(subset=["T", "g"])
    counts = pairs.groupby(pairs.index.normalize()).size()
    days = counts.index[(counts >= min_day) & (counts.index < pd.Timestamp(f"{fyear + 1}-07-01"))]
    if len(days) < s.min_days:
        return None
    rows = pairs[pairs.index.normalize().isin(days)]
    coldest = rows["T"].groupby(rows.index.normalize()).mean().idxmin()
    rows = rows[rows.index.normalize() <= coldest]
    return rows if rows.index.normalize().nunique() >= s.min_days else None


def bin_medians(rows: pd.DataFrame, s: Settings, min_n: int) -> pd.Series:
    g = rows.groupby(np.round(rows["T"] / s.bin_width_c) * s.bin_width_c)["g"].agg(["median", "size"])
    return g.loc[g["size"] >= min_n, "median"]


def unfrozen_level(bins: pd.Series, s: Settings) -> float:
    w = bins[(bins.index >= s.unfrozen_range_c[0]) & (bins.index <= s.unfrozen_range_c[1])]
    return float(w.median()) if len(w) >= 2 else np.nan


def frozen_fraction(T, t_on: float, t_fr: float, s: Settings) -> np.ndarray:
    """Bai-type curve F(T) = 1 - exp(b (T - Tf)) below Tf, 0 above, set by F(T_on)=q_on, F(T_fr)=q_fr."""
    width = max(t_on - t_fr, 1e-3)
    b = (np.log(1 - s.q_on) - np.log(1 - s.q_fr)) / width
    tf = t_on - np.log(1 - s.q_on) / b
    T = np.asarray(T, dtype=float)
    with np.errstate(over="ignore", invalid="ignore"):
        return np.where(T < tf, 1 - np.exp(b * (T - tf)), 0.0)


def _noise_sd(bins: pd.Series, s: Settings) -> float:
    w = bins[(bins.index >= s.unfrozen_range_c[0]) & (bins.index <= s.unfrozen_range_c[1])]
    if len(w) < 4:
        return 0.03
    return max(0.02, 1.4826 * float(np.median(np.abs(w - w.median()))))


def fit_winter(bins: pd.Series, g_unf: float, prior, width_prior: tuple, s: Settings):
    """Joint fit of (T_on, width, frozen fraction). Returns ((t_on, t_fr, g_fr), "fitted") or (None, reason)."""
    if not np.isfinite(g_unf):
        return None, "no_unfrozen_level"
    eps_unf = g_unf**2
    sel = bins[(bins.index >= s.fit_range_c[0]) & (bins.index <= s.fit_range_c[1])]
    cold = bins[bins.index <= s.unfrozen_range_c[0]]
    if len(sel) < 5 or cold.empty:
        return None, "too_few_bins"
    lowest = float(cold.rolling(3, center=True, min_periods=1).median().min())
    expected = prior.expected(eps_unf)
    if (g_unf - lowest) / max(g_unf - np.sqrt(min(expected, lowest**2)), 1e-6) < s.min_frozen_share:
        return None, "barely_frozen"
    f_cap = max(min(0.98, 1.05 * lowest**2 / eps_unf), 0.03)
    x, y = sel.index.values, sel.values
    sig = _noise_sd(bins, s)
    lw0, lsd = np.log(width_prior[0]), width_prior[1]

    def residuals(p):
        t_on, lw, f = p
        g_fr = np.sqrt(f * eps_unf)
        model = g_unf - frozen_fraction(x, t_on, t_on - np.exp(lw), s) * (g_unf - g_fr)
        return np.r_[(y - model) / sig, prior.penalty(f * eps_unf, eps_unf), (lw - lw0) / lsd]

    f0 = float(np.clip(expected / eps_unf, 0.03, f_cap - 0.005))
    best = None
    for t0, l0 in ((0.2, lw0), (-0.5, lw0), (0.8, lw0 - 0.7)):
        try:
            r = least_squares(residuals, [t0, l0, f0], bounds=([s.t_on_bounds_c[0], np.log(0.05), 0.02],
                                                               [s.t_on_bounds_c[1], np.log(8), f_cap]))
        except ValueError:
            continue
        if best is None or r.cost < best.cost:
            best = r
    if best is None:
        return None, "fit_failed"
    t_on, lw, f = best.x
    if min(abs(t_on - s.t_on_bounds_c[0]), abs(t_on - s.t_on_bounds_c[1])) < 0.02 or f < 0.03 or lw > np.log(7.5):
        return None, "parameter_at_bound"
    return (float(t_on), float(t_on - np.exp(lw)), float(np.sqrt(f * eps_unf))), "fitted"


def observed_frozen_level(bins: pd.Series, g_unf: float, s: Settings) -> float | None:
    """sqrt(eps) of the frozen level where the data show it, else None.

    The coldest bins must form a flat run: starting from the coldest bin and moving warmer, every bin stays within
    seen_flat_tol x (sqrt drop) of the median of the three coldest bins, over at least seen_flat_span_c. The soil
    must reach seen_min_coldest_c, and the frozen level must be plausible (drop and minimum permittivity)."""
    cold = bins[bins.index <= s.unfrozen_range_c[0]].sort_index()
    if len(cold) < 5 or not np.isfinite(g_unf) or cold.index.min() > s.seen_min_coldest_c or g_unf <= cold.min():
        return None
    ref = cold.iloc[:3].median()
    run = cold[((cold - ref).abs() <= s.seen_flat_tol * (g_unf - cold.min())).cumprod().astype(bool)]
    if len(run) < 3 or run.index.max() - run.index.min() < s.seen_flat_span_c - 1e-9:
        return None
    g_fr = float(run.median())
    if g_unf**2 - g_fr**2 <= s.seen_min_drop or g_fr**2 < s.seen_min_frozen_eps:
        return None
    return g_fr


def cold_side_misfit(bins: pd.Series, g_unf: float, t_on: float, t_fr: float, g_fr: float, s: Settings) -> float:
    """RMS misfit of the bins colder than T_on + 0.3 degC, as a share of the permittivity drop (sqrt units)."""
    sel = bins[(bins.index >= s.fit_range_c[0]) & (bins.index <= t_on + 0.3)]
    if sel.empty or g_unf <= g_fr:
        return np.nan
    model = g_unf - frozen_fraction(sel.index.values, t_on, t_fr, s) * (g_unf - g_fr)
    return float(np.sqrt(np.mean((sel.values - model) ** 2)) / (g_unf - g_fr))


# --- one sensor ------------------------------------------------------------------------------
@dataclass
class WinterFit:
    fyear: int
    status: str
    coldest_c: float
    eps_unfrozen: float
    eps_frozen: float = np.nan
    cold_misfit: float = np.nan
    n_boot_ok: int = 0
    boots: np.ndarray | None = None
    t_on: float = np.nan
    t_fr: float = np.nan
    t_on_sd: float = np.nan
    t_fr_sd: float = np.nan
    t_on_pooled: float = np.nan
    t_fr_pooled: float = np.nan
    t_on_pooled_sd: float = np.nan
    t_fr_pooled_sd: float = np.nan
    slow: bool = False
    t_fr_source: str = "fit"
    frozen_level_seen: bool = False

    @property
    def fitted(self) -> bool:
        return self.status == "fitted"


@dataclass
class SensorFit:
    sensor_id: str
    step_h: float
    winters: dict = field(default_factory=dict)
    average: dict = field(default_factory=dict)      # threshold -> (mean, sd) over fitted winters
    mean_se: dict = field(default_factory=dict)      # threshold -> (mean, se) used to combine sensors
    network: str = ""
    probe: str = "unknown"
    depth_class: str = ""
    ground: str = "unknown"                            # RESOLVE biome | soil texture class


def sensor_rng(sensor_id: str, s: Settings) -> np.random.Generator:
    return np.random.default_rng([s.seed, zlib.crc32(sensor_id.encode())])


def fit_sensor(sensor_id: str, frame: pd.DataFrame, s: Settings = Settings(), prior=None) -> SensorFit:
    """Fit every eligible winter of one sensor. frame: columns T and g (see sensor_frame)."""
    prior = prior or FractionPrior(*s.frozen_fraction)
    rng = sensor_rng(sensor_id, s)
    pairs = frame.dropna(subset=["T", "g"])
    step = native_step_hours(pairs.index)
    min_day = readings_per_day(step, s.day_fit_share)
    min_n = s.min_bin_readings if step <= 1.5 else 2
    fit = SensorFit(sensor_id, step)
    for fyear, rows in frame.groupby(freeze_year(frame.index)):
        half = freezing_half(rows, int(fyear), min_day, s)
        if half is None:
            continue
        bins = bin_medians(half, s, min_n)
        g_unf = unfrozen_level(bins, s)
        winter = WinterFit(int(fyear), "", float(half["T"].min()), g_unf**2)
        winter.frozen_level_seen = observed_frozen_level(bins, g_unf, s) is not None
        main, status = fit_winter(bins, g_unf, prior, s.width_prior, s)
        if main is not None:
            winter.eps_frozen = main[2] ** 2
            winter.cold_misfit = cold_side_misfit(bins, g_unf, *main, s)
            if not winter.cold_misfit <= s.max_cold_misfit:
                main, status = None, "poor_fit"
        days = half.index.normalize()
        by_day = {day: half[days == day] for day in days.unique()}
        day_list = list(by_day)
        pairs_boot = []
        if main is not None:
            for _ in range(s.n_boot):
                pick = rng.integers(0, len(day_list), len(day_list))
                b = bin_medians(pd.concat([by_day[day_list[i]] for i in pick]), s, min_n)
                width = (float(np.exp(rng.normal(np.log(s.width_prior[0]), s.width_prior[1]))), s.width_prior[1])
                out, _ = fit_winter(b, unfrozen_level(b, s), prior.redrawn(rng), width, s)
                if out is not None:
                    pairs_boot.append(out[:2])
        winter.n_boot_ok = len(pairs_boot)
        if main is not None and len(pairs_boot) >= s.min_boot_share * s.n_boot:
            boots = np.array(pairs_boot)
            winter.status, winter.boots = "fitted", boots
            winter.t_on, winter.t_fr = float(np.median(boots[:, 0])), float(np.median(boots[:, 1]))
            winter.t_on_sd = max(float(boots[:, 0].std()), 0.01)
            winter.t_fr_sd = max(float(boots[:, 1].std()), 0.01)
        else:
            winter.status = status if main is None else "unstable_bootstrap"
        fit.winters[int(fyear)] = winter
    return fit


# --- pooling ---------------------------------------------------------------------------------
def random_effects(x, se) -> tuple[float, float, float]:
    """DerSimonian-Laird mean, its standard error, and between-unit variance."""
    x, se = np.asarray(x, float), np.asarray(se, float)
    if len(x) == 0:
        raise ValueError("no estimates to pool")
    if len(x) == 1:
        return float(x[0]), float(se[0]), 0.0
    w = 1 / se**2
    q = np.sum(w * (x - np.sum(w * x) / np.sum(w)) ** 2)
    tau2 = max(0.0, (q - (len(x) - 1)) / (np.sum(w) - np.sum(w**2) / np.sum(w)))
    wr = 1 / (se**2 + tau2)
    return float(np.sum(wr * x) / np.sum(wr)), float(np.sqrt(1 / np.sum(wr))), float(tau2)


def pool_sensors(fits: list[SensorFit]) -> dict | None:
    """Pull winters toward their sensor mean (keeping each winter's own sd); return the average of the sensors."""
    for fit in fits:
        fitted = [w for w in fit.winters.values() if w.fitted]
        fit.average, fit.mean_se = {}, {}
        if not fitted:
            continue
        for k in ("t_on", "t_fr"):
            vals, sds = [getattr(w, k) for w in fitted], [getattr(w, f"{k}_sd") for w in fitted]
            mu, mu_se, tau2 = random_effects(vals, sds)
            fit.average[k] = (mu, float(np.sqrt(mu_se**2 + tau2)))
            fit.mean_se[k] = (mu, mu_se)
            for w, x, sd in zip(fitted, vals, sds):
                pooled = (x / sd**2 + mu / tau2) / (1 / sd**2 + 1 / tau2) if tau2 > 0 else mu
                setattr(w, f"{k}_pooled", float(pooled))
                setattr(w, f"{k}_pooled_sd", float(sd))
    return combine_sensors(fits)


def combine_sensors(fits: list[SensorFit]) -> dict | None:
    """Random-effects average of already pooled sensors (None when none has a fitted winter)."""
    fits = [f for f in fits if f.mean_se]
    if not fits:
        return None
    out = {}
    for k in ("t_on", "t_fr"):
        mu, mu_se, tau2 = random_effects([f.mean_se[k][0] for f in fits], [f.mean_se[k][1] for f in fits])
        out[k] = (mu, float(np.sqrt(mu_se**2 + tau2)))
    return out


def fallback_levels(fits: list[SensorFit]) -> dict:
    """Averages for the fallback chain: (network, probe), probe, global. Call after pool_sensors."""
    levels = {}
    for dc in {f.depth_class for f in fits}:
        same = [f for f in fits if f.depth_class == dc]
        levels[("global", dc)] = combine_sensors(same)
        for net, probe in {(f.network, f.probe) for f in same}:
            levels[("network_probe", net, probe, dc)] = combine_sensors(
                [f for f in same if (f.network, f.probe) == (net, probe)])
        for probe in {f.probe for f in same if f.probe != "unknown"}:
            levels[("probe", probe, dc)] = combine_sensors([f for f in same if f.probe == probe])
        for net in {f.network for f in same}:
            levels[("network", net, dc)] = combine_sensors([f for f in same if f.network == net])
        for ground in {f.ground for f in same if "unknown" not in f.ground}:
            members = [f for f in same if f.ground == ground and f.mean_se]
            if len(members) >= 3:
                levels[("ground", ground, dc)] = combine_sensors(members)
    return levels


def fallbacks_for(fit: SensorFit, levels: dict) -> list:
    """Ordered (label, average, same_probe) options after the sensor's own winters: same network and probe ->
    same probe anywhere -> same network, other probes -> same biome and soil texture -> global
    (the last three add the cross-probe sd)."""
    dc = fit.depth_class
    chain = [("network_probe_average", levels.get(("network_probe", fit.network, fit.probe, dc)), True)]
    if fit.probe != "unknown":
        chain.append(("probe_average", levels.get(("probe", fit.probe, dc)), True))
    chain.append(("network_average", levels.get(("network", fit.network, dc)), False))
    chain.append(("biome_soil_average", levels.get(("ground", fit.ground, dc)), False))
    chain.append(("global_average", levels.get(("global", dc)), False))
    return [c for c in chain if c[1]]


# --- slow freezes ----------------------------------------------------------------------------
def _reference(w: WinterFit) -> bool:
    return w.fitted and w.frozen_level_seen


def apply_slow_freeze_rule(fits: list[SensorFit], s: Settings = Settings()) -> float:
    """Winters whose fitted width exceeds the 90th percentile of reference widths (fitted winters with a seen frozen
    level) keep T_on; T_fr = T_on - donor width, with donors (reference, not slow) taken from: same sensor -> same
    network and probe -> same probe -> same biome and soil texture -> all.
    Call before pool_sensors. Returns the width cut-off used."""
    trusted = [(f, w) for f in fits for w in f.winters.values() if _reference(w)]
    widths = np.array([w.t_on - w.t_fr for _, w in trusted])
    cut = float(np.quantile(widths, s.slow_width_quantile)) if len(widths) >= 30 else s.slow_width_default_c
    donors = [(f, w) for f, w in trusted if w.t_on - w.t_fr <= cut]
    for fit in fits:
        rng = sensor_rng(fit.sensor_id + "|slow", s)
        for w in fit.winters.values():
            if not w.fitted or w.t_on - w.t_fr <= cut:
                continue
            same = [(f, d) for f, d in donors if f.depth_class == fit.depth_class]
            groups = (("sensor", [d for f, d in same if f is fit and d is not w]),
                      ("network_probe", [d for f, d in same if (f.network, f.probe) == (fit.network, fit.probe)]),
                      ("probe", [d for f, d in same if f.probe == fit.probe and fit.probe != "unknown"]),
                      ("biome_soil", [d for f, d in same if f.ground == fit.ground and "unknown" not in fit.ground]),
                      ("all", [d for _, d in same]))
            level, chosen = next(((lab, g) for lab, g in groups if len(g) >= s.min_donors), (None, []))
            if level is None:
                continue
            dw = np.array([d.t_on - d.t_fr for d in chosen])
            median, sd = float(np.median(dw)), max(float(dw.std()), 0.1)
            boots = w.boots.copy()
            boots[:, 1] = boots[:, 0] - np.clip(rng.normal(median, sd, len(boots)), 0.05, None)
            w.boots, w.slow, w.t_fr_source = boots, True, f"donor_{level}"
            w.t_fr = float(np.median(boots[:, 1]))
            w.t_fr_sd = max(float(boots[:, 1].std()), 0.01)
    return cut


# --- probabilities and dates -----------------------------------------------------------------
def _extra_fr_sd(w: WinterFit | None, s: Settings) -> float:
    if w is None or not w.fitted:
        return s.extra_sd_fr_c[1]
    margin = w.t_fr_pooled - w.coldest_c
    return s.extra_sd_fr_c[0] if margin >= 1 else s.extra_sd_fr_c[1] if margin >= 0 else s.extra_sd_fr_c[2]


def _keep_ordered(on, fr, redraw):
    for _ in range(20):
        bad = fr >= on - 0.02
        if not bad.any():
            break
        on[bad], fr[bad] = redraw(int(bad.sum()))
    bad = fr >= on - 0.02
    fr[bad] = on[bad] - 0.02
    return on, fr


def threshold_draws(fit: SensorFit, fyear: int, fallbacks, s: Settings,
                    rng: np.random.Generator, n: int | None = None):
    """(T_on, T_fr) draws for one freeze year, and where they came from.
    fallbacks: list from fallbacks_for(), or a single average dict / None (treated as a same-probe network)."""
    n = n or s.n_mc
    if fallbacks is None or isinstance(fallbacks, dict):
        fallbacks = [("network_average", fallbacks, True)] if fallbacks else []
    w = fit.winters.get(fyear)
    extra_fr = _extra_fr_sd(w, s)
    if w is not None and w.fitted:
        bs = w.boots
        m_on, m_fr = bs[:, 0].mean(), bs[:, 1].mean()
        k_on = np.hypot(max(w.t_on_pooled_sd, s.se_floor_c), s.extra_sd_on_c) / max(bs[:, 0].std(), 1e-6)
        k_fr = np.hypot(max(w.t_fr_pooled_sd, s.se_floor_c), extra_fr) / max(bs[:, 1].std(), 1e-6)

        def redraw(k):
            p = bs[rng.integers(0, len(bs), k)]
            return w.t_on_pooled + (p[:, 0] - m_on) * k_on, w.t_fr_pooled + (p[:, 1] - m_fr) * k_fr

        return (*_keep_ordered(*redraw(n), redraw), "own_winter")
    fallbacks = list(fallbacks)
    if not fit.average and not fallbacks:
        raise ValueError(f"{fit.sensor_id} {fyear}: no thresholds available at any fallback level")

    def sds(option):
        _, src, same_probe = option
        cross = 0.0 if same_probe else s.cross_probe_sd_c
        return (np.sqrt(max(src["t_on"][1], s.se_floor_c) ** 2 + s.extra_sd_on_c**2 + cross**2),
                np.sqrt(max(src["t_fr"][1], s.se_floor_c) ** 2 + extra_fr**2 + cross**2))

    # the sensor's own average competes with the first group level; the tighter one (T_on and T_fr variance) wins
    options = [o for o in ([("sensor_average", fit.average, True)] if fit.average else []) + fallbacks[:1]]
    label, src, _ = min(options, key=lambda o: sum(v**2 for v in sds(o)))
    sd_on, sd_fr = sds((label, src, _))

    def redraw(k):
        return rng.normal(src["t_on"][0], sd_on, k), rng.normal(src["t_fr"][0], sd_fr, k)

    return (*_keep_ordered(*redraw(n), redraw), label)


def freeze_legs(temperature: pd.Series) -> pd.Series:
    """'freezing' from 1 Aug to the freeze year's coldest day (daily mean, before 1 Jul), 'thawing' after it."""
    leg = pd.Series(np.nan, index=temperature.index, dtype=object)
    years = freeze_year(temperature.index)
    for fyear in np.unique(years):
        t = temperature[years == fyear]
        daily = t.resample("D").mean()
        daily = daily[daily.index < pd.Timestamp(f"{fyear + 1}-07-01")].dropna()
        if daily.empty:
            continue
        coldest = daily.idxmin()
        leg[years == fyear] = np.where(t.index.normalize() <= coldest, "freezing", "thawing")
    return leg


def hourly_probabilities(fit: SensorFit, temperature: pd.Series, fallbacks,
                         s: Settings = Settings()) -> pd.DataFrame:
    """P(thawed / transition / frozen), mean frozen fraction, threshold source and freeze/thaw leg per hour."""
    rng = sensor_rng(fit.sensor_id + "|mc", s)
    out = pd.DataFrame(index=temperature.index, columns=["p_thawed", "p_transition", "p_frozen", "frozen_fraction"],
                       dtype=float)
    out["source"] = ""
    years = freeze_year(temperature.index)
    for fyear in np.unique(years):
        mask = (years == fyear) & temperature.notna().values
        if not mask.any():
            continue
        on, fr, label = threshold_draws(fit, int(fyear), fallbacks, s, rng)
        T = temperature.values[mask][:, None] + rng.normal(0, s.thermometer_sd_c, (mask.sum(), len(on)))
        thawed, frozen = T > on, T < fr
        out.loc[mask, "p_thawed"] = thawed.mean(1)
        out.loc[mask, "p_frozen"] = frozen.mean(1)
        out.loc[mask, "p_transition"] = (~thawed & ~frozen).mean(1)
        out.loc[mask, "frozen_fraction"] = frozen_fraction_draws(T, on, fr, s).mean(1)
        out.loc[mask, "source"] = label
    out["leg"] = freeze_legs(temperature)
    probs = out[["p_thawed", "p_transition", "p_frozen"]].dropna()
    if not (((probs >= 0) & (probs <= 1)).all().all() and np.allclose(probs.sum(axis=1), 1)):
        raise AssertionError("invalid probabilities")
    return out


def frozen_fraction_draws(T: np.ndarray, on: np.ndarray, fr: np.ndarray, s: Settings) -> np.ndarray:
    b = (np.log(1 - s.q_on) - np.log(1 - s.q_fr)) / (on - fr)
    tf = on - np.log(1 - s.q_on) / b
    with np.errstate(over="ignore", invalid="ignore"):
        return np.where(T < tf, 1 - np.exp(b * (T - tf)), 0.0)


def daily_labels(prob: pd.DataFrame, s: Settings = Settings()) -> pd.Series:
    """Majority of hourly most-likely labels; days with too few readings are NaN."""
    p = prob[["p_thawed", "p_transition", "p_frozen"]].dropna()
    if p.empty:
        return pd.Series(dtype=object)
    labels = p.idxmax(axis=1).str.replace("p_", "", regex=False)
    counts = labels.groupby(labels.index.normalize()).value_counts().unstack(fill_value=0)
    need = readings_per_day(native_step_hours(p.index), s.day_label_share)
    daily = counts.idxmax(axis=1).where(counts.sum(axis=1) >= need)
    return daily.reindex(pd.date_range(daily.index.min(), daily.index.max(), freq="D"))


def _first_run(ok: pd.Series, last_start: pd.Timestamp, n: int):
    ok = ok.fillna(False).astype(bool)
    run = ok.astype(int).groupby((~ok).cumsum()).cumsum()
    for day in run[run >= n].index:
        start = day - pd.Timedelta(days=n - 1)
        if start <= last_start:
            return start
    return pd.NaT


def freeze_dates(prob: pd.DataFrame, s: Settings = Settings()) -> pd.DataFrame:
    """Per freeze year (1 Aug - 31 Jul):
    transition_onset / freeze_start: first day (on or before 1 Mar) that begins >= persist_days of
        'not thawed' / 'frozen' (day of first freezing, Rautiainen et al. 2025);
    freeze_end: first day of the thawing leg (after the year's coldest day; uses prob['leg'] when present)
        that begins >= persist_days of 'thawed' - only for years with a transition onset. The SMOS product
        defines no spring date, so this mirrors the autumn rule."""
    daily = daily_labels(prob, s)
    thaw_start = {}
    if "leg" in prob:
        legs = prob["leg"].dropna()
        thawing = legs[legs == "thawing"]
        for fyear in np.unique(freeze_year(thawing.index)):
            thaw_start[int(fyear)] = thawing[freeze_year(thawing.index) == fyear].index.min().normalize()
    rows = []
    for fyear in np.unique(freeze_year(daily.index)) if len(daily) else []:
        win = daily[f"{fyear}-08-01":f"{fyear + 1}-07-31"]
        valid = win.notna()
        if valid.sum() < 150:
            continue
        last = pd.Timestamp(f"{fyear + 1}-03-01")
        onset = _first_run(win.isin(["transition", "frozen"]).where(valid), last, s.persist_days)
        start = _first_run((win == "frozen").where(valid), last, s.persist_days)
        end = pd.NaT
        if pd.notna(onset):
            spring = win[thaw_start.get(int(fyear), onset):]
            end = _first_run((spring == "thawed").where(spring.notna()), pd.Timestamp(f"{fyear + 1}-07-31"),
                             s.persist_days)
        rows.append(dict(fyear=int(fyear), valid_days=int(valid.sum()), transition_onset=onset,
                         freeze_start=start, freeze_end=end))
    return pd.DataFrame(rows, columns=["fyear", "valid_days", "transition_onset", "freeze_start", "freeze_end"])


# --- package interface -----------------------------------------------------------------------
class SFCCProcessor:
    """FreezeThawProcessor for one fitted sensor (thresholds from fit_sensor + pool_sensors)."""

    model_version = MODEL_VERSION

    def __init__(self, fit: SensorFit, fallbacks=None, settings: Settings = Settings()):
        """fallbacks: list from fallbacks_for(), or a single network-average dict."""
        self.fit, self.fallbacks, self.settings = fit, fallbacks, settings

    def predict(self, sensor: SensorMetadata, hours: list[Observation]) -> list[Prediction]:
        index = pd.DatetimeIndex([h.timestamp_utc.astimezone(timezone.utc).replace(tzinfo=None) for h in hours])
        temperature = pd.Series([np.nan if h.soil_temperature_c is None else h.soil_temperature_c for h in hours],
                                index=index, dtype=float)
        prob = hourly_probabilities(self.fit, temperature, self.fallbacks, self.settings)
        out = []
        for h, (_, row) in zip(hours, prob.iterrows()):
            values = [None if pd.isna(row[c]) else float(row[c]) for c in ("p_frozen", "p_transition", "p_thawed")]
            out.append(Prediction(sensor.sensor_id, h.timestamp_utc, *values, self.model_version))
        return out

    def yearly_events(self, sensor: SensorMetadata, predictions: list[Prediction]) -> list[YearlyFreezeEvent]:
        index = pd.DatetimeIndex([p.timestamp_utc.astimezone(timezone.utc).replace(tzinfo=None) for p in predictions])
        prob = pd.DataFrame({"p_thawed": [p.p_thawed for p in predictions],
                             "p_transition": [p.p_transition for p in predictions],
                             "p_frozen": [p.p_frozen for p in predictions]}, index=index, dtype=float)
        dates = freeze_dates(prob, self.settings)
        utc = lambda d: None if pd.isna(d) else d.to_pydatetime().replace(tzinfo=timezone.utc)
        return [YearlyFreezeEvent(sensor.sensor_id, int(r.fyear), utc(r.freeze_start), utc(r.freeze_end),
                                  self.model_version) for r in dates.itertuples()]


# --- batch run -------------------------------------------------------------------------------
THRESHOLD_COLUMNS = ("sensor_id", "network", "probe", "depth_class", "biome_soil", "fyear", "status", "coldest_c", "eps_unfrozen",
                     "eps_frozen", "cold_misfit", "n_boot_ok", "frozen_level_seen", "slow_freeze", "t_fr_source", "t_on_c", "t_on_sd_c",
                     "t_fr_c", "t_fr_sd_c", "model_version")
EXTRA_PREDICTION_COLUMNS = ("leg", "frozen_fraction", "threshold_source")
LOCAL_NETWORK_PROBES = {"Kenaston": "HydraProbe", "Candle Lake": "HydraProbe", "Montmorency Forest": "TEROS12",
                        "James Bay": "TEROS12", "La Romaine": "TEROS12", "George River": "TEROS12"}


def probe_family(name) -> str:
    """Group temperature-probe names: all METER probes together, both Stevens HydraProbe versions together."""
    if not isinstance(name, str) or not name.strip() or name.strip().lower() in {"nan", "not-specified", "unknown"}:
        return "unknown"
    n = name.lower()
    if "hydra" in n:
        return "hydraprobe"
    if any(k in n for k in ("meter", "teros", "5tm", "5te", "gs3", "decagon")):
        return "meter"
    if "ibutton" in n:
        return "ibutton"
    if "pt100" in n:
        return "pt100"
    return n.split("-")[0] if "-" in n else n


def catalog_probes(catalog: pd.DataFrame, ismn_pairing: pd.DataFrame | None = None) -> pd.Series:
    """Temperature-probe family per catalog row: catalog type, ISMN file name, or local network table."""
    names = catalog.get("soil_temperature_sensor_type", pd.Series(np.nan, index=catalog.index)).copy()
    if ismn_pairing is not None:
        token = (ismn_pairing.temperature_files.str.split("/").str[-1].str.split(";").str[0].str.split("_").str[6])
        names = names.fillna(catalog["sensor_id"].map(dict(zip(ismn_pairing.sensor_id, token))))
    local = catalog["source"].eq("local")
    names = names.where(~local | names.notna(), catalog["network"].map(LOCAL_NETWORK_PROBES))
    return names.map(probe_family)


def _sensor_input(row: dict, observations_root: Path, flags_root: Path | None) -> pd.DataFrame:
    path = observations_root / row["source"] / f"{row['sensor_id']}.csv"
    flags = flags_root / row["source"] / f"{row['sensor_id']}.csv.gz" if flags_root else None
    d = read_standardized(path, flags if row["source"] == "ismn" else None)
    return sensor_frame(d, str(row.get("raw_variable")) in RAW_PERMITTIVITY)


def _fit_task(task):
    row, observations_root, flags_root, settings = task
    try:
        return row["sensor_id"], fit_sensor(row["sensor_id"], _sensor_input(row, observations_root, flags_root),
                                            settings), ""
    except (OSError, ValueError, KeyError) as exc:
        return row["sensor_id"], None, str(exc)


def _predict_task(task):
    row, fit, fallbacks, observations_root, flags_root, output_dir, settings = task
    frame = _sensor_input(row, observations_root, flags_root)
    prob = hourly_probabilities(fit, frame["T"], fallbacks, settings)
    probs = prob[["p_frozen", "p_transition", "p_thawed"]]
    valid = probs.notna().all(axis=1).values
    names = np.array(["frozen", "transition", "thawed"], dtype=object)
    out = pd.DataFrame({"timestamp_utc": prob.index.strftime("%Y-%m-%dT%H:00:00Z"),
                        "p_frozen": probs.p_frozen, "p_transition": probs.p_transition, "p_thawed": probs.p_thawed,
                        "label": np.where(valid, names[np.argmax(probs.fillna(-1).values, axis=1)], None),
                        "model_version": MODEL_VERSION, "leg": prob.leg,
                        "frozen_fraction": prob.frozen_fraction, "threshold_source": prob.source.replace("", np.nan)})
    out.to_csv(output_dir / "predictions" / f"{fit.sensor_id}.csv.gz", index=False, na_rep="NaN")
    dates = freeze_dates(prob, settings)
    dates.insert(0, "sensor_id", fit.sensor_id)
    return dates


def run_classification(catalog: pd.DataFrame, observations_root: Path, output_dir: Path,
                       flags_root: Path | None = None, settings: Settings = Settings(), workers: int = 1,
                       run_info: dict | None = None) -> dict:
    """Fit, apply the slow-freeze rule, pool, and write predictions/<id>.csv.gz, thresholds.csv, yearly_events.csv
    and manifest.json. catalog needs sensor_id, source, network, raw_variable, depth_cm and optionally probe,
    biome (RESOLVE Ecoregions 2017 biome) and soil_texture (SoilGrids USDA texture class) columns."""
    from concurrent.futures import ProcessPoolExecutor
    import json
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "predictions").mkdir(exist_ok=True)
    catalog = catalog.copy()
    if "probe" not in catalog:
        catalog["probe"] = catalog_probes(catalog)
    rows = catalog.to_dict("records")
    def ground(r):
        lc, tex = r.get("biome"), r.get("soil_texture")
        return f"{lc if isinstance(lc, str) else 'unknown'}|{tex if isinstance(tex, str) else 'unknown'}"

    meta = {r["sensor_id"]: (r["network"] if isinstance(r.get("network"), str) else r["source"], r["probe"],
                             depth_class(r.get("depth_cm"), r.get("depth_from_cm"), r.get("depth_to_cm")) or "unclassified", ground(r)) for r in rows}
    fits, errors = {}, {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for sid, fit, err in pool.map(_fit_task, [(r, observations_root, flags_root, settings) for r in rows]):
            if fit is None:
                errors[sid] = err
            else:
                fit.network, fit.probe, fit.depth_class, fit.ground = meta[sid]
                fits[sid] = fit
    cut = apply_slow_freeze_rule(list(fits.values()), settings)
    pool_sensors(list(fits.values()))
    levels = fallback_levels(list(fits.values()))
    table = []
    for sid, fit in fits.items():
        for w in fit.winters.values():
            ok = w.fitted
            table.append(dict(sensor_id=sid, network=fit.network, probe=fit.probe, depth_class=fit.depth_class,
                              biome_soil=fit.ground,
                              fyear=w.fyear, status=w.status,
                              coldest_c=w.coldest_c, eps_unfrozen=w.eps_unfrozen, eps_frozen=w.eps_frozen,
                              cold_misfit=w.cold_misfit, n_boot_ok=w.n_boot_ok,
                              frozen_level_seen=w.frozen_level_seen, slow_freeze=w.slow,
                              t_fr_source=w.t_fr_source if ok else np.nan,
                              t_on_c=w.t_on_pooled if ok else np.nan, t_on_sd_c=w.t_on_pooled_sd if ok else np.nan,
                              t_fr_c=w.t_fr_pooled if ok else np.nan, t_fr_sd_c=w.t_fr_pooled_sd if ok else np.nan,
                              model_version=MODEL_VERSION))
    pd.DataFrame(table, columns=THRESHOLD_COLUMNS).to_csv(output_dir / "thresholds.csv", index=False, na_rep="NaN")
    tasks, skipped = [], []
    for r in rows:
        fit = fits.get(r["sensor_id"])
        if fit is None:
            continue
        chain = fallbacks_for(fit, levels)
        if fit.average or chain:
            tasks.append((r, fit, chain, observations_root, flags_root, output_dir, settings))
        else:
            skipped.append(r["sensor_id"])
    with ProcessPoolExecutor(max_workers=workers) as pool:
        dates = list(pool.map(_predict_task, tasks))
    events = pd.concat(dates) if dates else pd.DataFrame(columns=["sensor_id", "fyear", "valid_days",
                                                                 "transition_onset", "freeze_start", "freeze_end"])
    events["model_version"] = MODEL_VERSION
    events.to_csv(output_dir / "yearly_events.csv", index=False, na_rep="NaN")
    fitted_winters = sum(w.fitted for f in fits.values() for w in f.winters.values())
    summary = dict(model_version=MODEL_VERSION, settings=settings.__dict__, sensors=len(rows),
                   processed_sensors=len(fits), winters=sum(len(f.winters) for f in fits.values()),
                   fitted_winters=fitted_winters, slow_width_cutoff_c=cut,
                   slow_winters=sum(w.slow for f in fits.values() for w in f.winters.values()),
                   predicted_sensors=len(tasks), errors=errors, skipped_no_thresholds=skipped,
                   fallback_levels={"|".join(map(str, k)): v for k, v in levels.items()})
    summary.update(run_info or {})
    (output_dir / "manifest.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary
