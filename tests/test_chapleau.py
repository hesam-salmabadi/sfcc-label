from datetime import datetime, timezone

from sfcc_label.chapleau import _local_to_utc, _rounded_hour


def test_hour_rounding_for_publisher_seconds():
    assert _rounded_hour(datetime(2018, 1, 1, 4, 59, 59)) == datetime(2018, 1, 1, 5)
    assert _rounded_hour(datetime(2018, 1, 1, 5, 0, 9)) == datetime(2018, 1, 1, 5)


def test_local_dst_mapping_is_conservative():
    summer, reason = _local_to_utc(datetime(2017, 6, 2, 0), 7.2, {})
    assert summer == datetime(2017, 6, 2, 4, tzinfo=timezone.utc)
    assert reason == "unambiguous"
    winter, _ = _local_to_utc(datetime(2018, 1, 1, 0), None, {})
    assert winter == datetime(2018, 1, 1, 5, tzinfo=timezone.utc)
    missing, reason = _local_to_utc(datetime(2022, 3, 13, 2), None, {})
    assert missing is None and reason == "nonexistent"
    ambiguous, reason = _local_to_utc(datetime(2021, 11, 7, 1), None, {})
    assert ambiguous is None and reason == "ambiguous"
    resolved, reason = _local_to_utc(
        datetime(2021, 11, 7, 1), 2.5, {datetime(2021, 11, 7, 6): 2.5})
    assert resolved == datetime(2021, 11, 7, 6, tzinfo=timezone.utc)
    assert reason == "resolved_from_temperature"
