"""Stable records exchanged between pipeline stages."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

CLASSES = ("frozen", "transition", "thawed")


@dataclass(frozen=True)
class SensorMetadata:
    sensor_id: str
    source: str
    latitude: float
    longitude: float
    site_id: str | None = None
    network: str | None = None
    station: str | None = None
    depth_cm: float | None = None
    depth_from_cm: float | None = None
    depth_to_cm: float | None = None
    raw_variable: str | None = None
    raw_unit: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    timezone_original: str | None = None
    soil_moisture_method: str | None = None
    land_cover: str | None = None
    land_cover_source: str | None = None
    modeled_soil_variable: str | None = None
    modeled_soil_value: str | None = None
    modeled_soil_unit: str | None = None
    modeled_soil_source: str | None = None

    def __post_init__(self) -> None:
        if not self.sensor_id or not all(c.isalnum() or c in "_-" for c in self.sensor_id):
            raise ValueError("sensor_id must contain only letters, digits, '_' or '-'")
        if self.source not in {"ismn", "ameriflux", "local"}:
            raise ValueError("source must be ismn, ameriflux, or local")
        if not isfinite(self.latitude) or not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not isfinite(self.longitude) or not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")
        if self.depth_cm is not None and (not isfinite(self.depth_cm) or self.depth_cm < 0):
            raise ValueError("depth_cm must be nonnegative or missing")
        for value in (self.depth_from_cm, self.depth_to_cm):
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError("depth bounds must be nonnegative or missing")
        if (self.depth_from_cm is not None and self.depth_to_cm is not None
                and self.depth_from_cm > self.depth_to_cm):
            raise ValueError("depth_from_cm must not exceed depth_to_cm")


@dataclass(frozen=True)
class Observation:
    timestamp_utc: datetime
    soil_temperature_c: float | None
    soil_moisture_m3_m3: float | None
    raw_value: float | None


@dataclass(frozen=True)
class Prediction:
    sensor_id: str
    timestamp_utc: datetime
    p_frozen: float | None
    p_transition: float | None
    p_thawed: float | None
    model_version: str

    def __post_init__(self) -> None:
        values = (self.p_frozen, self.p_transition, self.p_thawed)
        if all(value is None for value in values):
            return
        if any(value is None or not isfinite(value) or not 0 <= value <= 1 for value in values):
            raise ValueError("probabilities must all be finite values in [0, 1] or all missing")
        if abs(sum(values) - 1) > 1e-6:
            raise ValueError("probabilities must sum to one")

    @property
    def label(self) -> str | None:
        values = (self.p_frozen, self.p_transition, self.p_thawed)
        if self.p_frozen is None:
            return None
        return CLASSES[max(range(3), key=lambda index: values[index])]


@dataclass(frozen=True)
class YearlyFreezeEvent:
    sensor_id: str
    year: int
    freeze_start_utc: datetime | None
    freeze_end_utc: datetime | None
    model_version: str
