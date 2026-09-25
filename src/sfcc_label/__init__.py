"""Soil freeze/thaw data contracts and EASE-Grid aggregation."""

from .aggregate import aggregate_probabilities, get_processed_data
from .grid import GridCell, grid_cell
from .io import load_metadata, read_observations, read_predictions, write_observations
from .models import Observation, Prediction, SensorMetadata, YearlyFreezeEvent
from .processing import FreezeThawProcessor

__all__ = [
    "Observation", "Prediction", "SensorMetadata", "YearlyFreezeEvent",
    "FreezeThawProcessor", "GridCell", "grid_cell", "load_metadata",
    "read_observations", "read_predictions", "write_observations",
    "aggregate_probabilities", "get_processed_data",
]
