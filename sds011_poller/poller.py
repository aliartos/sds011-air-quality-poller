from __future__ import annotations

import logging
import random
import sys
import time
from typing import Optional, TextIO

from .config import AppConfig
from .output import PrometheusExporter, format_error, format_measurement
from .sensor_client import SensorClient


log = logging.getLogger(__name__)


class Poller:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.sensor = SensorClient(config.serial, config.sensor)
        self._consecutive_failures: int = 0
        self._file: Optional[TextIO] = None
        self._prom: Optional[PrometheusExporter] = None
        if self.config.output.file_path:
            self._file = open(self.config.output.file_path, "a", buffering=1, encoding="utf-8")
            log.info("Appending measurements to file: %s", self.config.output.file_path)
        if self.config.output.format == "prometheus":
            self._prom = PrometheusExporter(
                host=self.config.output.prometheus_host,
                port=self.config.output.prometheus_port,
            )
            log.info(
                "Prometheus exporter listening on %s:%s",
                self.config.output.prometheus_host,
                self.config.output.prometheus_port,
            )

    def _calculate_delay(self, started_at: float) -> float:
        interval = float(self.config.schedule.interval_s)
        jitter = float(self.config.schedule.jitter_s)
        delay = interval + random.uniform(-jitter, jitter)
        elapsed = time.monotonic() - started_at
        remaining = delay - elapsed
        return remaining if remaining > 0 else 0

    def _emit_line(self, line: str) -> None:
        print(line, flush=True)
        self._write_file(line)

    def _write_file(self, line: str) -> None:
        if self._file:
            self._file.write(line + "\n")

    @staticmethod
    def _is_zero_reading(measurement) -> bool:
        return measurement.pm25 == 0.0 and measurement.pm10 == 0.0

    def run_forever(self) -> None:
        while True:
            started_at = time.monotonic()
            try:
                measurement = self.sensor.measure()
                retried_zero = False
                if self._is_zero_reading(measurement):
                    wait_s = random.uniform(1, 2)
                    retried_zero = True
                    log.warning("Zero reading (pm25=pm10=0). Retrying once in %.2fs", wait_s)
                    time.sleep(wait_s)
                    measurement = self.sensor.measure()

                if self._is_zero_reading(measurement):
                    self._consecutive_failures += 1
                    if self._prom:
                        self._prom.record_suspect(measurement)
                        if self._file:
                            self._write_file(format_measurement(measurement, "jsonl", status="suspect"))
                    else:
                        line = format_measurement(measurement, self.config.output.format, status="suspect")
                        self._emit_line(line)
                    log.warning(
                        "Suspect zero reading pm25=%.1f pm10=%.1f%s; last_success not updated",
                        measurement.pm25,
                        measurement.pm10,
                        " after retry" if retried_zero else "",
                    )
                else:
                    if self._prom:
                        self._prom.record_success(measurement)
                        if self._file:
                            self._write_file(format_measurement(measurement, "jsonl"))
                    else:
                        line = format_measurement(measurement, self.config.output.format)
                        self._emit_line(line)
                    log.info(
                        "Measurement ok pm25=%.1f pm10=%.1f device=%s",
                        measurement.pm25,
                        measurement.pm10,
                        measurement.device_id or "unknown",
                    )
                    self._consecutive_failures = 0
            except KeyboardInterrupt:
                log.info("Interrupted, shutting down")
                raise
            except Exception as exc:
                self._consecutive_failures += 1
                if self._prom:
                    self._prom.record_error(exc, self.config.serial.port)
                    if self._file:
                        self._write_file(
                            format_error(
                                exc,
                                attempt=self._consecutive_failures,
                                max_attempts=self.config.schedule.max_consecutive_failures,
                                fmt="jsonl",
                            )
                        )
                else:
                    error_line = format_error(
                        exc,
                        attempt=self._consecutive_failures,
                        max_attempts=self.config.schedule.max_consecutive_failures,
                        fmt=self.config.output.format,
                    )
                    self._emit_line(error_line)
                log.error("Measurement failed (%s/%s): %s",
                          self._consecutive_failures,
                          self.config.schedule.max_consecutive_failures,
                          exc,
                          exc_info=True)
                self.sensor.close()

            if self._consecutive_failures >= self.config.schedule.max_consecutive_failures:
                log.warning(
                    "Backing off for %ss after %s consecutive failures",
                    self.config.schedule.backoff_s,
                    self._consecutive_failures,
                )
                time.sleep(self.config.schedule.backoff_s)
                self._consecutive_failures = 0
                continue

            delay = self._calculate_delay(started_at)
            time.sleep(delay)

    def close(self) -> None:
        self.sensor.close()
        if self._file and not self._file.closed:
            self._file.close()


def run(config: AppConfig) -> None:
    poller = Poller(config)
    try:
        poller.run_forever()
    except KeyboardInterrupt:
        poller.close()
        sys.exit(0)
