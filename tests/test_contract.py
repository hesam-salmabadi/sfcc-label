from datetime import datetime, timezone

import pytest

from sfcc_label import (Observation, Prediction, SensorMetadata, YearlyFreezeEvent,
                        aggregate_probabilities, aggregate_yearly_events,
                        get_processed_data, grid_cell, read_land_cover_screens,
                        read_observations, screen_land_cover, write_observations)


def _screen(sensor, resolution="9km", sensor_class="forest", cell_class="forest",
            share=0.9, water=0.0, other=0.0):
    cell = grid_cell(sensor.latitude, sensor.longitude, resolution).cell_id
    return screen_land_cover(sensor.sensor_id, resolution, cell, sensor_class, cell_class,
                             share, water, other)


def matching_screens(stations, resolution="9km"):
    return {(key, f"N{resolution}"): _screen(sensor, resolution) for key, sensor in stations.items()}


def test_missing_moisture_round_trip(tmp_path):
    path = tmp_path / "station.csv"
    time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [Observation(time, -1.2, None, 8321.0)]
    write_observations(path, rows)
    assert ",NaN," in path.read_text()
    assert read_observations(path) == rows


def test_probability_contract_and_aggregation():
    time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    stations = {
        "a": SensorMetadata("a", "local", 45.5, -73.6),
        "b": SensorMetadata("b", "ismn", 45.5, -73.6),
    }
    with pytest.raises(ValueError, match="sum to one"):
        Prediction("a", time, .2, .2, .2, "v1")
    rows = aggregate_probabilities([
        Prediction("a", time, .8, .1, .1, "v1"),
        Prediction("b", time, .2, .2, .6, "v1"),
    ], stations, matching_screens(stations))
    assert len(rows) == 1
    assert rows[0].sensor_count == 2
    assert rows[0].mean_sensor_p_frozen == pytest.approx(.5)
    assert rows[0].frozen_count == 1
    assert rows[0].thawed_count == 1
    assert rows[0].cell_id == grid_cell(45.5, -73.6).cell_id
    assert get_processed_data(rows, start_utc=time) == rows
    assert get_processed_data(rows, end_utc=time) == []


def test_northern_grid_pole_and_invalid_resolution():
    cell = grid_cell(90, 0)
    assert cell.row == 1000
    assert cell.col == 1000
    assert cell.cell_id.startswith("EASE2_N_9km")
    with pytest.raises(ValueError, match="resolution"):
        grid_cell(90, 0, "10km")
    with pytest.raises(ValueError, match="Northern Hemisphere"):
        grid_cell(-1, 0)


def test_yearly_event_summary_preserves_missing_end_dates():
    stations = {key: SensorMetadata(key, "local", 45.5, -73.6)
                for key in ("a", "b", "c")}
    def date(day):
        return datetime(2023, 10, day, tzinfo=timezone.utc)
    events = [
        YearlyFreezeEvent("a", 2023, date(1), datetime(2024, 4, 20, tzinfo=timezone.utc), "v1"),
        YearlyFreezeEvent("b", 2023, date(10), None, "v1"),
        YearlyFreezeEvent("c", 2023, date(31), datetime(2024, 4, 30, tzinfo=timezone.utc), "v1"),
    ]
    row, = aggregate_yearly_events(events, stations, matching_screens(stations))
    assert row.freeze_start.median_utc == date(10)
    assert row.freeze_start.earliest_utc == date(1)
    assert row.freeze_start.latest_utc == date(31)
    assert row.freeze_start.sensor_count == 3
    assert row.freeze_end.sensor_count == 2
    assert row.freeze_end.median_utc == datetime(2024, 4, 25, tzinfo=timezone.utc)


def test_smos_style_screen_reasons():
    sensor = SensorMetadata("a", "local", 45.5, -73.6)
    assert _screen(sensor).reason == "representative"
    assert _screen(sensor, cell_class="agriculture").reason == "class_mismatch"
    assert _screen(sensor, share=0.69).reason == "class_below_70pct"
    assert _screen(sensor, share=0.70).eligible
    assert _screen(sensor, water=0.06).reason == "water_above_5pct"
    assert _screen(sensor, other=0.051).reason == "other_above_5pct"
    assert _screen(sensor, sensor_class=None).reason == "missing_sensor_class"
    assert _screen(sensor, share=None).reason == "class_below_70pct"


def test_unrepresentative_or_missing_screen_is_excluded(tmp_path):
    sensor = SensorMetadata("a", "local", 45.5, -73.6)
    stations = {"a": sensor}
    time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    prediction = Prediction("a", time, .8, .1, .1, "v1")
    wet = _screen(sensor, water=0.2)
    assert aggregate_probabilities([prediction], stations, {("a", "N9km"): wet}) == []
    assert aggregate_probabilities([prediction], stations, {}) == []
    good = {("a", "N9km"): _screen(sensor)}
    assert len(aggregate_probabilities([prediction], stations, good)) == 1
    assert aggregate_probabilities([prediction], stations, good, "25km") == []
    table = tmp_path / "sensor_landcover_cci.csv"
    cell = grid_cell(45.5, -73.6).cell_id
    table.write_text(
        "sensor_id,grid,cell_id,sensor_class,cell_class,sensor_class_fraction,"
        "water_fraction,other_fraction\n"
        f"a,N9km,{cell},forest,forest,0.8000,0.0100,0.0000\n"
        "a,M9km,NaN,forest,NaN,NaN,NaN,NaN\n")
    screens = read_land_cover_screens(table)
    assert list(screens) == [("a", "N9km")]
    assert screens[("a", "N9km")].eligible
    assert len(aggregate_probabilities([prediction], stations, screens)) == 1
