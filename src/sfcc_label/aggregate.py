"""Preliminary aggregation and in-memory querying of processed observations."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import defaultdict

from .grid import grid_cell
from .landcover import LandCoverScreen, is_representative
from .models import Prediction, SensorMetadata, YearlyFreezeEvent


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


@dataclass(frozen=True)
class EventDateSummary:
    median_utc: datetime | None
    earliest_utc: datetime | None
    latest_utc: datetime | None
    sensor_count: int


@dataclass(frozen=True)
class GriddedYearlyEvents:
    cell_id: str
    year: int
    freeze_start: EventDateSummary
    freeze_end: EventDateSummary
    model_version: str


def aggregate_probabilities(predictions: list[Prediction],
                            sensors: dict[str, SensorMetadata],
                            screens: dict[tuple[str, int, str], LandCoverScreen],
                            resolution: str = "9km") -> list[GriddedPrediction]:
    """Summarize only land-cover-matched sensors by cell/hour."""
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
        if not is_representative(prediction.sensor_id, prediction.timestamp_utc.year,
                                 resolution, cell.cell_id, screens):
            continue
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


def _event_date_summary(dates: list[datetime]) -> EventDateSummary:
    if not dates:
        return EventDateSummary(None, None, None, 0)
    dates.sort()
    middle = len(dates) // 2
    median = (dates[middle] if len(dates) % 2
              else dates[middle - 1] + (dates[middle] - dates[middle - 1]) / 2)
    return EventDateSummary(median, dates[0], dates[-1], len(dates))


def aggregate_yearly_events(events: list[YearlyFreezeEvent],
                            sensors: dict[str, SensorMetadata],
                            screens: dict[tuple[str, int, str], LandCoverScreen],
                            resolution: str = "9km") -> list[GriddedYearlyEvents]:
    """Summarize per-sensor event dates; missing start/end dates have separate counts.

    Callers should first filter to sensors at scientifically comparable depths.
    These dates describe sampled sensors, not a cell-wide freeze/thaw event.
    """
    groups = defaultdict(list)
    seen = set()
    for event in events:
        if event.sensor_id not in sensors:
            raise ValueError(f"unknown sensor_id: {event.sensor_id}")
        identity = (event.sensor_id, event.year, event.model_version)
        if identity in seen:
            raise ValueError(f"duplicate sensor/year/version: {identity}")
        seen.add(identity)
        for date in (event.freeze_start_utc, event.freeze_end_utc):
            if date is not None and (date.tzinfo is None or date.utcoffset() != timedelta(0)):
                raise ValueError("event dates must be timezone-aware UTC")
        sensor = sensors[event.sensor_id]
        cell = grid_cell(sensor.latitude, sensor.longitude, resolution)
        if not is_representative(event.sensor_id, event.year, resolution,
                                 cell.cell_id, screens):
            continue
        groups[(cell.cell_id, event.year, event.model_version)].append(event)
    return [
        GriddedYearlyEvents(
            cell_id, year,
            _event_date_summary([event.freeze_start_utc for event in records
                                 if event.freeze_start_utc is not None]),
            _event_date_summary([event.freeze_end_utc for event in records
                                 if event.freeze_end_utc is not None]),
            version,
        )
        for (cell_id, year, version), records in sorted(groups.items())
    ]


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
