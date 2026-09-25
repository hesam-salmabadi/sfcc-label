"""Preliminary aggregation and in-memory querying of processed observations."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from .grid import grid_cell
from .models import Prediction, SensorMetadata


@dataclass(frozen=True)
class GriddedPrediction:
    cell_id: str
    timestamp_utc: datetime
    mean_sensor_p_frozen: float
    mean_sensor_p_transition: float
    mean_sensor_p_thawed: float
    frozen_count: int
    transition_count: int
    thawed_count: int
    sensor_count: int
    model_version: str

    @property
    def frozen_label_share(self) -> float:
        return self.frozen_count / self.sensor_count

    @property
    def transition_label_share(self) -> float:
        return self.transition_count / self.sensor_count

    @property
    def thawed_label_share(self) -> float:
        return self.thawed_count / self.sensor_count


def aggregate_probabilities(predictions: list[Prediction],
                            sensors: dict[str, SensorMetadata],
                            resolution: str = "9km") -> list[GriddedPrediction]:
    """Summarize sampled sensor states by cell/hour, without asserting a cell label."""
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
                                        sum(p.label == "frozen" for p in records),
                                        sum(p.label == "transition" for p in records),
                                        sum(p.label == "thawed" for p in records),
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
