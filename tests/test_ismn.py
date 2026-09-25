import csv
import gzip
from datetime import datetime, timezone

from sfcc_label import read_observations
from sfcc_label.ismn import import_ismn_pair, pair_ismn, scan_ismn, sensor_metadata


def _write_stm(root, variable, depth, rows):
    station = root / "NET" / "S1"
    station.mkdir(parents=True, exist_ok=True)
    name = f"NET_NET_S1_{variable}_{depth}_{depth}_Probe_1_1_20200101_20200103.stm"
    path = station / name
    path.write_text(
        f"NET NET S1 50.000 -100.000 100.0 {float(depth):.4f} {float(depth):.4f} 'Probe'\n"
        + "\n".join(rows) + "\n", encoding="utf-8"
    )
    return path


def test_ismn_depth_pair_hourly_missingness_and_original_flags(tmp_path):
    root = tmp_path / "source"
    _write_stm(root, "ts", "0.050000", [
        "2020/01/01 00:00 -1.0 G M",
        "2020/01/01 01:00 -2.0 D01 M",
        "2020/01/01 02:00 -3.0 G M",
    ])
    _write_stm(root, "sm", "0.050000", [
        "2020/01/01 00:00 0.2 G M",
        "2020/01/01 02:00 -0.1 C01 M",
    ])
    _write_stm(root, "ts", "0.100000", [
        "2020/01/01 00:00 1.0 G M",
    ])
    files, issues = scan_ismn(root)
    assert issues == []
    pairs = pair_ismn(files)
    assert len(pairs) == 2
    paired = next(pair for pair in pairs if pair.moisture is not None)
    temp_only = next(pair for pair in pairs if pair.moisture is None)
    assert paired.pairing_method == "same_instrument"
    assert sensor_metadata(paired).depth_cm == 5.0
    assert sensor_metadata(paired).latitude == 50.0
    assert temp_only.pairing_method == "temperature_only"

    observations = tmp_path / "observations"
    flags = tmp_path / "flags"
    count = import_ismn_pair(paired,
                             datetime(2020, 1, 1, tzinfo=timezone.utc),
                             datetime(2020, 1, 2, tzinfo=timezone.utc),
                             observations, flags)
    assert count == 3
    hours = read_observations(observations / f"{paired.sensor_id}.csv")
    assert hours[1].soil_moisture_m3_m3 is None
    assert hours[2].soil_moisture_m3_m3 == -0.1  # Retain flagged anomaly for later QA/QC.
    assert all(hour.raw_value is None for hour in hours)
    with gzip.open(flags / f"{paired.sensor_id}.csv.gz", "rt", encoding="utf-8") as stream:
        flagged = list(csv.DictReader(stream))
    assert flagged[1]["soil_temperature_ismn_flag"] == "D01"
    assert flagged[1]["soil_moisture_ismn_flag"] == ""
    assert flagged[2]["soil_moisture_ismn_flag"] == "C01"
