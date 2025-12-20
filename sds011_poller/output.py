from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict

from .sensor_client import Measurement

try:
    from prometheus_client import Counter, Gauge, start_http_server
except ModuleNotFoundError as exc:  # pragma: no cover - optional for non-prometheus output
    Counter = Gauge = start_http_server = None  # type: ignore[assignment]
    _prometheus_import_error = exc
else:
    _prometheus_import_error = None


def _logfmt_escape(value: str) -> str:
    if " " in value or "=" in value:
        return f"\"{value}\""
    return value


def format_measurement(measurement: Measurement, fmt: str = "jsonl", status: str = "ok") -> str:
    data: Dict[str, str | float] = measurement.as_dict()
    data["status"] = status
    if fmt == "jsonl":
        return json.dumps(data, separators=(",", ":"))
    if fmt == "logfmt":
        parts = [
            f"timestamp={_logfmt_escape(str(data['timestamp']))}",
            f"pm25={data['pm25']}",
            f"pm10={data['pm10']}",
            f"device_id={_logfmt_escape(str(data['device_id']))}",
            f"port={_logfmt_escape(str(data['port']))}",
            f"status={_logfmt_escape(str(status))}",
        ]
        return " ".join(parts)
    raise ValueError(f"Unknown output format: {fmt}")


def format_error(exc: Exception, attempt: int, max_attempts: int, fmt: str = "jsonl") -> str:
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "error",
        "error": exc.__class__.__name__,
        "message": str(exc),
        "attempt": attempt,
        "max_attempts": max_attempts,
    }
    if fmt == "jsonl":
        return json.dumps(data, separators=(",", ":"))
    if fmt == "logfmt":
        parts = [
            f"timestamp={_logfmt_escape(data['timestamp'])}",
            "status=error",
            f"error={_logfmt_escape(data['error'])}",
            f"message={_logfmt_escape(data['message'])}",
            f"attempt={attempt}",
            f"max_attempts={max_attempts}",
        ]
        return " ".join(parts)
    raise ValueError(f"Unknown output format: {fmt}")


class PrometheusExporter:
    """
    Lightweight Prometheus HTTP exporter started inside the poller process.
    """

    def __init__(self, host: str, port: int) -> None:
        if _prometheus_import_error:
            raise ImportError(
                "prometheus_client is required for prometheus output"
            ) from _prometheus_import_error

        self.pm25 = Gauge(
            "sds011_pm25_ugm3",
            "PM2.5 measurement in ug/m3",
            ["port", "device_id"],
        )
        self.pm10 = Gauge(
            "sds011_pm10_ugm3",
            "PM10 measurement in ug/m3",
            ["port", "device_id"],
        )
        self.last_success = Gauge(
            "sds011_last_success_timestamp_seconds",
            "Unix timestamp of last successful measurement",
            ["port", "device_id"],
        )
        self.last_success_ms = Gauge(
            "sds011_last_success_timestamp_millis",
            "Unix timestamp of last successful measurement in milliseconds (Grafana-friendly)",
            ["port", "device_id"],
        )
        self.last_status = Gauge(
            "sds011_last_status",
            "1=last read succeeded, 0=last read failed",
            ["port", "device_id"],
        )
        self.errors_total = Counter(
            "sds011_errors_total",
            "Total measurement errors",
            ["port", "cause"],
        )
        self.last_error = Gauge(
            "sds011_last_error_timestamp_seconds",
            "Unix timestamp of last measurement error",
            ["port"],
        )

        start_http_server(port, addr=host)

    def record_success(self, measurement: Measurement) -> None:
        labels = {"port": measurement.port, "device_id": measurement.device_id or "unknown"}
        ts = measurement.timestamp.timestamp()
        self.pm25.labels(**labels).set(measurement.pm25)
        self.pm10.labels(**labels).set(measurement.pm10)
        self.last_success.labels(**labels).set(ts)
        self.last_success_ms.labels(**labels).set(ts * 1000.0)
        self.last_status.labels(**labels).set(1)

    def record_error(self, exc: Exception, port: str) -> None:
        cause = exc.__class__.__name__
        ts = datetime.now(timezone.utc).timestamp()
        labels = {"port": port}
        self.errors_total.labels(port=port, cause=cause).inc()
        self.last_error.labels(**labels).set(ts)
        self.last_status.labels(port=port, device_id="unknown").set(0)

    def record_suspect(self, measurement: Measurement) -> None:
        labels = {"port": measurement.port, "device_id": measurement.device_id or "unknown"}
        ts = datetime.now(timezone.utc).timestamp()
        self.errors_total.labels(port=measurement.port, cause="suspect_zero").inc()
        self.last_error.labels(port=measurement.port).set(ts)
        self.last_status.labels(**labels).set(0)
