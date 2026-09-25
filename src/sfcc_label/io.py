"""Read and write the normalized CSV contract."""

import csv
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path

from .models import Observation, Prediction, SensorMetadata

METADATA_COLUMNS = tuple(SensorMetadata.__dataclass_fields__)
OBSERVATION_COLUMNS = ("timestamp_utc", "soil_temperature_c", "soil_moisture_m3_m3", "raw_value")
PREDICTION_COLUMNS = ("timestamp_utc", "p_frozen", "p_transition", "p_thawed", "label", "model_version")


def _optional_text(value: str | None) -> str | None:
    if value is None or value.strip().lower() in {"", "nan"}:
        return None
    return value.strip()


def _optional_float(value: str | None) -> float | None:
    value = _optional_text(value)
    if value is None:
        return None
    result = float(value)
    if not isfinite(result):
        raise ValueError("numeric values must be finite or NaN")
    return result


def _utc_hour(value: str) -> datetime:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None or instant.utcoffset() != timedelta(0):
        raise ValueError("timestamp_utc must carry an explicit UTC offset")
    instant = instant.astimezone(timezone.utc)
    if instant.minute or instant.second or instant.microsecond:
        raise ValueError("timestamp_utc must be on an exact hour")
    return instant


def _read_csv(path: str | Path, columns: tuple[str, ...]):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or tuple(reader.fieldnames) != columns:
            raise ValueError(f"{path}: expected columns {', '.join(columns)}")
        for line_number, row in enumerate(reader, start=2):
            try:
                yield row
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc


def load_metadata(path: str | Path) -> dict[str, SensorMetadata]:
    sensors = {}
    for row in _read_csv(path, METADATA_COLUMNS):
        data = {name: _optional_text(row[name]) for name in METADATA_COLUMNS}
        data["latitude"] = float(row["latitude"])
        data["longitude"] = float(row["longitude"])
        data["depth_cm"] = _optional_float(row["depth_cm"])
        sensor = SensorMetadata(**data)
        if sensor.sensor_id in sensors:
            raise ValueError(f"duplicate sensor_id: {sensor.sensor_id}")
        sensors[sensor.sensor_id] = sensor
    return sensors


def read_observations(path: str | Path) -> list[Observation]:
    observations = []
    previous = None
    for row in _read_csv(path, OBSERVATION_COLUMNS):
        timestamp = _utc_hour(row["timestamp_utc"])
        if previous is not None and timestamp - previous != timedelta(hours=1):
            raise ValueError(f"{path}: timestamps must be consecutive UTC hours")
        moisture = _optional_float(row["soil_moisture_m3_m3"])
        if moisture is not None and not 0 <= moisture <= 1:
            raise ValueError(f"{path}: soil moisture must be a fraction in [0, 1]")
        observations.append(Observation(timestamp, _optional_float(row["soil_temperature_c"]),
                                        moisture, _optional_float(row["raw_value"])))
        previous = timestamp
    return observations


def write_observations(path: str | Path, observations: list[Observation]) -> None:
    path = Path(path)
    if not path.parent.exists():
        raise FileNotFoundError(path.parent)
    previous = None
    for observation in observations:
        timestamp = _utc_hour(observation.timestamp_utc.isoformat())
        if previous is not None and timestamp - previous != timedelta(hours=1):
            raise ValueError("timestamps must be consecutive UTC hours")
        for value in (observation.soil_temperature_c, observation.soil_moisture_m3_m3, observation.raw_value):
            if value is not None and not isfinite(value):
                raise ValueError("measurement must be finite or missing")
        if observation.soil_moisture_m3_m3 is not None and not 0 <= observation.soil_moisture_m3_m3 <= 1:
            raise ValueError("soil moisture must be a fraction in [0, 1]")
        previous = timestamp
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(OBSERVATION_COLUMNS)
        for item in observations:
            writer.writerow((item.timestamp_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00:00Z"),
                             *(_format_number(value) for value in (item.soil_temperature_c,
                               item.soil_moisture_m3_m3, item.raw_value))))


def _format_number(value: float | None) -> str:
    return "NaN" if value is None else str(value)


def read_predictions(path: str | Path, sensor_id: str) -> list[Prediction]:
    predictions = []
    previous = None
    for row in _read_csv(path, PREDICTION_COLUMNS):
        timestamp = _utc_hour(row["timestamp_utc"])
        if previous is not None and timestamp <= previous:
            raise ValueError(f"{path}: prediction timestamps must increase")
        prediction = Prediction(sensor_id, timestamp, _optional_float(row["p_frozen"]),
                                _optional_float(row["p_transition"]),
                                _optional_float(row["p_thawed"]), row["model_version"])
        if _optional_text(row["label"]) != prediction.label:
            raise ValueError(f"{path}: label does not match probabilities")
        predictions.append(prediction)
        previous = timestamp
    return predictions
