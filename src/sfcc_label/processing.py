"""Boundary for the scientific model, pending its specification."""

from typing import Protocol

from .models import Observation, Prediction, SensorMetadata, YearlyFreezeEvent


class FreezeThawProcessor(Protocol):
    """A versioned model that returns hourly labels and yearly event dates."""

    model_version: str

    def predict(self, sensor: SensorMetadata, hours: list[Observation]) -> list[Prediction]: ...

    def yearly_events(self, sensor: SensorMetadata,
                      predictions: list[Prediction]) -> list[YearlyFreezeEvent]: ...


def process_sensor(sensor: SensorMetadata, hours: list[Observation],
                   processor: FreezeThawProcessor | None = None
                   ) -> tuple[list[Prediction], list[YearlyFreezeEvent]]:
    if processor is None:
        raise NotImplementedError("Freeze/thaw algorithm and annual event rules are not specified yet")
    predictions = processor.predict(sensor, hours)
    events = processor.yearly_events(sensor, predictions)
    if any(prediction.sensor_id != sensor.sensor_id or
           prediction.model_version != processor.model_version for prediction in predictions):
        raise ValueError("processor returned predictions with inconsistent sensor or version")
    return predictions, events
