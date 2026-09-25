"""Preliminary aggregation and in-memory querying of processed observations."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from .grid import grid_cell
from .models import Prediction, SensorMetadata, CLASSES


@dataclass(frozen=True)
class GriddedPrediction:
    cell_id: str
    timestamp_utc: datetime
    p_frozen: float
    p_transition: float
    p_thawed: float
    station_count: int
    model_version: str

    @property
    def label(self) -> str:
        values = (self.p_frozen, self.p_transition, self.p_thawed)
        return CLASSES[max(range(3), key=lambda index: values[index])]


def aggregate_probabilities(predictions: list[Prediction],
                            sensors: dict[str, SensorMetadata],
                            resolution: str = "9km") -> list[GriddedPrediction]:
    """Mean valid probabilities by cell/hour; each sensor counts at most once."""
    groups = defaultdict(list)
    seen = set()
    for prediction in predictions:
        if prediction.sensor_id not in sensors:
            raise ValueError(f"unknown sensor_id: {prediction.sensor_id}")
        if prediction.timestamp_utc.tzinfo is None or prediction.timestamp_utc.utcoffset() != timedelta(0):
            raise ValueError("prediction timestamp must be UTC")
        if prediction.timestamp_utc.minute or prediction.timestamp_utc.second or prediction.timestamp_utc.microsecond:
            raise ValueError("prediction timestamp must be on an exact hour")
        identity = (prediction.sensor_id, prediction.timestamp_utc)
        if identity in seen:
            raise ValueError(f"duplicate sensor/hour: {identity}")
        seen.add(identity)
        if prediction.p_frozen is None:
            continue
        sensor = sensors[prediction.sensor_id]
        cell = grid_cell(sensor.latitude, sensor.longitude, resolution)
        groups[(cell.cell_id, prediction.timestamp_utc, prediction.model_version)].append(prediction)
    result = []
    for (cell_id, timestamp, version), records in sorted(groups.items()):
        count = len(records)
        result.append(GriddedPrediction(cell_id, timestamp,
                                        sum(p.p_frozen for p in records) / count,
                                        sum(p.p_transition for p in records) / count,
                                        sum(p.p_thawed for p in records) / count,
                                        count, version))
    return result


def get_processed_data(rows: list[GriddedPrediction], *,
                       start_utc: datetime | None = None,
                       end_utc: datetime | None = None,
                       cell_ids: set[str] | None = None) -> list[GriddedPrediction]:
    """Return records in a half-open UTC interval [start_utc, end_utc)."""
    for value in (start_utc, end_utc):
        if value is not None and (value.tzinfo is None or value.utcoffset() != timedelta(0)):
            raise ValueError("query bounds must be timezone-aware UTC")
    return [row for row in rows
            if (start_utc is None or row.timestamp_utc >= start_utc)
            and (end_utc is None or row.timestamp_utc < end_utc)
            and (cell_ids is None or row.cell_id in cell_ids)]
