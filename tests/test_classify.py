from datetime import timezone

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")
pytest.importorskip("scipy")

from sfcc_label.classify import (MODEL_VERSION, SFCCProcessor, Settings, fit_sensor, freeze_dates,
                                 frozen_fraction, hourly_probabilities, native_step_hours, pool_sensors,
                                 readings_per_day, threshold_draws, topp_permittivity)
from sfcc_label.models import Observation, SensorMetadata
from sfcc_label.processing import process_sensor

FAST = Settings(n_boot=20, n_mc=100)


def synthetic(t_on=0.2, width=1.0, eps_unf=16.0, frac=0.4, tmin=-6.0, seed=0, step_h=1):
    """One freeze year of hourly (or coarser) soil temperature and sqrt-permittivity with a known curve."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-08-01", "2021-04-30 23:00", freq=f"{step_h}h")
    day = (idx - idx[0]).total_seconds().values / 86400
    knots = [10, max(tmin, t_on + 0.8), max(tmin, t_on - width - 0.5), tmin, max(tmin, 0.2), 5]
    base = np.interp(day, [0, 100, 130, 165, 215, 272], knots)
    true_t = base + rng.normal(0, 0.05, len(day))
    f = frozen_fraction(true_t, t_on, t_on - width, FAST)
    g = np.sqrt(eps_unf) - f * (np.sqrt(eps_unf) - np.sqrt(frac * eps_unf)) + rng.normal(0, 0.02, len(day))
    return pd.DataFrame({"T": true_t + rng.normal(0, 0.05, len(day)), "g": g}, index=idx)


def test_topp_inversion_round_trip():
    eps = np.array([4.0, 10.0, 25.0])
    theta = -0.053 + 0.0292 * eps - 5.5e-4 * eps**2 + 4.3e-6 * eps**3
    assert np.allclose(topp_permittivity(theta), eps, atol=0.05)
    assert np.isnan(topp_permittivity([np.nan]))[0]


def test_daily_requirements_follow_logger_interval():
    index = pd.date_range("2021-01-01", periods=20, freq="3h")
    assert native_step_hours(index) == 3
    assert readings_per_day(3, 0.5) == 4 and readings_per_day(1, 0.5) == 12


def test_cold_winter_recovers_thresholds():
    fit = fit_sensor("synthetic_a", synthetic(), FAST)
    winter = fit.winters[2020]
    assert winter.status == "fitted"
    assert abs(winter.t_on - 0.2) < 0.15
    assert abs(winter.t_fr - (-0.8)) < 0.3


def test_three_hourly_logger_is_fitted():
    assert fit_sensor("synthetic_b", synthetic(step_h=3), FAST).winters[2020].status == "fitted"


def test_winter_without_freezing_is_not_fitted_and_borrows_network():
    cold, warm = fit_sensor("cold", synthetic(), FAST), fit_sensor("warm", synthetic(tmin=1.5, seed=1), FAST)
    assert warm.winters[2020].status != "fitted"
    network = pool_sensors([cold, warm])
    _, _, source = threshold_draws(warm, 2020, network, FAST, np.random.default_rng(0))
    assert source == "network_average"
    frame = synthetic(tmin=1.5, seed=1)
    prob = hourly_probabilities(warm, frame["T"], network, FAST)
    assert (prob.dropna()["p_thawed"] > 0.9).mean() > 0.9


def test_probabilities_are_valid_and_thresholds_ordered():
    fit = fit_sensor("synthetic_c", synthetic(), FAST)
    network = pool_sensors([fit])
    on, fr, _ = threshold_draws(fit, 2020, network, FAST, np.random.default_rng(1), n=500)
    assert (fr < on).all()
    prob = hourly_probabilities(fit, synthetic()["T"], network, FAST).dropna()
    assert np.allclose(prob[["p_thawed", "p_transition", "p_frozen"]].sum(axis=1), 1)
    assert prob["frozen_fraction"].between(0, 1).all()


def test_no_thresholds_available_raises():
    warm = fit_sensor("warm", synthetic(tmin=1.5, seed=1), FAST)
    assert pool_sensors([warm]) is None
    with pytest.raises(ValueError):
        threshold_draws(warm, 2020, None, FAST, np.random.default_rng(0))


def test_freeze_start_needs_five_frozen_days():
    idx = pd.date_range("2020-08-01", "2021-07-31 23:00", freq="h")
    frozen = (idx >= "2020-12-01") & (idx < "2021-03-01")
    prob = pd.DataFrame({"p_thawed": (~frozen).astype(float), "p_transition": 0.0,
                         "p_frozen": frozen.astype(float)}, index=idx)
    prob.loc["2020-11-20":"2020-11-22 23:00", ["p_thawed", "p_frozen"]] = [0.0, 1.0]   # 3-day cold snap
    dates = freeze_dates(prob)
    assert dates.loc[0, "freeze_start"] == pd.Timestamp("2020-12-01")
    assert dates.loc[0, "freeze_end"] == pd.Timestamp("2021-03-01")          # first of >= 5 thawed days after winter


def test_processor_fits_the_package_interface():
    frame = synthetic()
    fit = fit_sensor("local_x_005cm_s1", frame, FAST)
    processor = SFCCProcessor(fit, pool_sensors([fit]), FAST)
    sensor = SensorMetadata("local_x_005cm_s1", "local", 50.0, -100.0)
    hours = [Observation(t.to_pydatetime().replace(tzinfo=timezone.utc), float(v), None, None)
             for t, v in frame["T"].iloc[::24].items()]
    predictions, events = process_sensor(sensor, hours, processor)
    assert len(predictions) == len(hours) and predictions[0].model_version == MODEL_VERSION
    assert predictions[-1].label is not None
    assert events == [] or events[0].model_version == MODEL_VERSION


def test_leg_splits_the_year_at_the_coldest_day():
    from sfcc_label.classify import freeze_legs
    frame = synthetic()
    legs = freeze_legs(frame["T"])
    coldest = frame["T"].resample("D").mean().idxmin()
    assert (legs[:coldest + pd.Timedelta(hours=23)] == "freezing").all()
    assert (legs[coldest + pd.Timedelta(days=1):] == "thawing").all()


def test_slow_freeze_keeps_onset_and_borrows_width():
    from sfcc_label.classify import apply_slow_freeze_rule
    donors = [fit_sensor(f"d{i}", synthetic(width=0.8, seed=10 + i), FAST) for i in range(3)]
    slow = fit_sensor("slow", synthetic(width=5.0, tmin=-9, seed=3), FAST)
    for f in donors + [slow]:
        f.network, f.probe = "net", "meter"
    t_on_before = slow.winters[2020].t_on
    assert all(d.winters[2020].frozen_level_seen for d in donors)
    apply_slow_freeze_rule(donors + [slow], Settings(n_boot=20, n_mc=100, slow_width_default_c=3.0))
    w = slow.winters[2020]
    assert w.slow and w.t_fr_source == "donor_network_probe"
    assert w.t_on == t_on_before
    assert 0.4 < w.t_on - w.t_fr < 1.3


def test_fallback_chain_adds_cross_probe_uncertainty():
    from sfcc_label.classify import fallback_levels, fallbacks_for
    teros = fit_sensor("teros", synthetic(), FAST)
    ibutton = fit_sensor("ibutton", synthetic(tmin=1.5, seed=1), FAST)
    teros.network, teros.probe = "net", "meter"
    ibutton.network, ibutton.probe = "net", "ibutton"
    pool_sensors([teros, ibutton])
    chain = fallbacks_for(ibutton, fallback_levels([teros, ibutton]))
    assert [c[0] for c in chain] == ["network_average", "global_average"] and chain[0][2] is False
    ibutton.ground = teros.ground = "forest|sandy loam"
    on_cross, _, source = threshold_draws(ibutton, 2020, chain, FAST, np.random.default_rng(0), n=4000)
    on_same, _, _ = threshold_draws(ibutton, 2020, [("x", chain[0][1], True)], FAST, np.random.default_rng(0), n=4000)
    assert source == "network_average" and on_cross.std() > on_same.std()


def test_prediction_files_with_extra_columns_are_readable(tmp_path):
    from sfcc_label.io import read_predictions
    path = tmp_path / "p.csv"
    path.write_text("timestamp_utc,p_frozen,p_transition,p_thawed,label,model_version,leg,frozen_fraction,threshold_source\n"
                    "2021-01-01T00:00:00Z,0.7,0.3,0.0,frozen,sfcc-joint-1.0,freezing,0.8,own_winter\n")
    assert read_predictions(path, "x")[0].label == "frozen"


def test_depth_classes():
    from sfcc_label.classify import depth_class
    assert depth_class(0.0) == "skin" and depth_class(1.9) == "skin"
    assert depth_class(2.5) is None and depth_class(3.0) == "topsoil" and depth_class(5.08) == "topsoil"
    assert depth_class(7.4) == "topsoil" and depth_class(7.5) is None and depth_class(float("nan")) is None
    assert depth_class(2.5, 0.0, 5.0) == "topsoil" and depth_class(2.5, 2.5, 2.5) is None


def test_fallbacks_never_mix_depth_classes():
    from sfcc_label.classify import fallback_levels, fallbacks_for
    shallow = fit_sensor("shallow", synthetic(), FAST)
    deep_temp_only = fit_sensor("deep", synthetic(tmin=1.5, seed=1), FAST)
    shallow.network, shallow.depth_class = "net", "topsoil"
    deep_temp_only.network, deep_temp_only.depth_class = "net", "skin"
    pool_sensors([shallow, deep_temp_only])
    assert fallbacks_for(deep_temp_only, fallback_levels([shallow, deep_temp_only])) == []


def test_gzipped_prediction_files_are_readable(tmp_path):
    import gzip
    from sfcc_label.io import read_predictions
    path = tmp_path / "p.csv.gz"
    with gzip.open(path, "wt") as stream:
        stream.write("timestamp_utc,p_frozen,p_transition,p_thawed,label,model_version,leg\n"
                     "2021-01-01T00:00:00Z,0.1,0.2,0.7,thawed,sfcc-joint-1.0,freezing\n")
    assert read_predictions(path, "x")[0].label == "thawed"


def test_temperature_only_network_borrows_matching_land_cover_and_soil():
    from sfcc_label.classify import fallback_levels, fallbacks_for
    donors = [fit_sensor(f"d{i}", synthetic(seed=20 + i), FAST) for i in range(3)]
    other = fit_sensor("other_ground", synthetic(t_on=-0.5, seed=30), FAST)
    lonely = fit_sensor("lonely", synthetic(tmin=1.5, seed=1), FAST)
    for f in donors:
        f.network, f.probe, f.ground = "a", "meter", "forest|sandy loam"
    other.network, other.probe, other.ground = "b", "meter", "agriculture|clay loam"
    lonely.network, lonely.probe, lonely.ground = "ibutton_net", "ibutton", "forest|sandy loam"
    pool_sensors(donors + [other, lonely])
    chain = fallbacks_for(lonely, fallback_levels(donors + [other, lonely]))
    assert chain[0][0] == "land_cover_soil_average" and chain[0][2] is False


def test_frozen_level_seen_needs_cold_flat_run():
    cold = fit_sensor("cold", synthetic(tmin=-8), FAST).winters[2020]
    mild = fit_sensor("mild", synthetic(tmin=-3), FAST).winters[2020]
    assert cold.frozen_level_seen and not mild.frozen_level_seen
