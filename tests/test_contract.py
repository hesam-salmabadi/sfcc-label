from datetime import datetime, timezone

import pytest

from sfcc_label import (Observation, Prediction, SensorMetadata, aggregate_probabilities,
                        get_processed_data, grid_cell, read_observations, write_observations)


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
    ], stations)
    assert len(rows) == 1
    assert rows[0].station_count == 2
    assert rows[0].p_frozen == pytest.approx(.5)
    assert rows[0].cell_id == grid_cell(45.5, -73.6).cell_id
    assert get_processed_data(rows, start_utc=time) == rows
    assert get_processed_data(rows, end_utc=time) == []


def test_global_grid_center_and_invalid_resolution():
    cell = grid_cell(0, 0)
    assert cell.row == 812
    assert cell.col == 1928
    with pytest.raises(ValueError, match="resolution"):
        grid_cell(0, 0, "10km")
