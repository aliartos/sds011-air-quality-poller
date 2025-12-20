from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for <3.11
    import tomli as tomllib


@dataclass
class SerialConfig:
    port: str
    baud: int = 9600
    timeout_ms: int = 1500


@dataclass
class SensorConfig:
    mode: str = "query"
    wake_before_read_s: int = 0
    sleep_after_read: bool = False
    max_query_retries: int = 2
    min_query_interval_s: int = 3


@dataclass
class ScheduleConfig:
    interval_s: int = 60
    jitter_s: int = 0
    max_consecutive_failures: int = 5
    backoff_s: int = 10


@dataclass
class OutputConfig:
    format: str = "jsonl"  # "jsonl" | "logfmt" | "prometheus"
    prometheus_host: str = "0.0.0.0"
    prometheus_port: int = 9101
    file_path: str | None = None  # when set, append lines to this file


@dataclass
class AppConfig:
    serial: SerialConfig
    sensor: SensorConfig
    schedule: ScheduleConfig
    output: OutputConfig


def _get_section(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    return data.get(name, {}) if isinstance(data.get(name, {}), dict) else {}


def _merge_dataclass(cls: Any, values: Dict[str, Any]) -> Any:
    kwargs = {field.name: values.get(field.name, getattr(cls, field.name, field.default))
              for field in dataclasses.fields(cls)}
    return cls(**kwargs)


def load_config(path: Path) -> AppConfig:
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    serial_section = _get_section(raw, "serial")
    sensor_section = _get_section(raw, "sensor")
    schedule_section = _get_section(raw, "schedule")
    output_section = _get_section(raw, "output")

    if "port" not in serial_section or not serial_section["port"]:
        raise ValueError("serial.port is required in config")

    serial = _merge_dataclass(SerialConfig, serial_section)
    sensor = _merge_dataclass(SensorConfig, sensor_section)
    schedule = _merge_dataclass(ScheduleConfig, schedule_section)
    output = _merge_dataclass(OutputConfig, output_section)

    if sensor.mode not in {"query"}:
        raise ValueError("sensor.mode must be 'query'")
    if output.format not in {"jsonl", "logfmt", "prometheus"}:
        raise ValueError("output.format must be 'jsonl', 'logfmt', or 'prometheus'")
    if schedule.interval_s < 1:
        raise ValueError("schedule.interval_s must be >= 1")
    if output.prometheus_port < 1 or output.prometheus_port > 65535:
        raise ValueError("output.prometheus_port must be between 1 and 65535")
    if output.file_path is not None and not isinstance(output.file_path, str):
        raise ValueError("output.file_path must be a string path when set")

    return AppConfig(
        serial=serial,
        sensor=sensor,
        schedule=schedule,
        output=output,
    )
