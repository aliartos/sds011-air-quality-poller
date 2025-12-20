from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import serial

from .config import SensorConfig, SerialConfig

try:
    from simple_sds011 import MODE_PASSIVE, SensorError, SDS011
except ModuleNotFoundError as exc:  # pragma: no cover - handled at runtime
    raise ImportError(
        "simple-sds011 is required. Install with `pip install -r requirements.txt`."
    ) from exc


log = logging.getLogger(__name__)


@dataclass
class Measurement:
    pm25: float
    pm10: float
    timestamp: datetime
    device_id: str
    port: str

    def as_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "pm25": self.pm25,
            "pm10": self.pm10,
            "device_id": self.device_id,
            "port": self.port,
        }


class SensorClient:
    def __init__(self, serial_cfg: SerialConfig, sensor_cfg: SensorConfig) -> None:
        self.serial_cfg = serial_cfg
        self.sensor_cfg = sensor_cfg
        self._device: Optional[SDS011] = None
        self._last_query_at: Optional[float] = None
        self._awake: bool = False
        self._warmed_once: bool = False

    def connect(self) -> None:
        timeout_s = self.serial_cfg.timeout_ms / 1000
        self._device = SDS011(self.serial_cfg.port, read_timeout=timeout_s)
        # Idempotently enforce passive/query mode and wake the device.
        self._device.set_up(mode=MODE_PASSIVE, active=1)
        self._device.clear()
        self._awake = True
        log.info("Connected to SDS011 on %s in passive mode", self.serial_cfg.port)

    def close(self) -> None:
        if self._device and self._device._sd.is_open:  # type: ignore[attr-defined]
            self._device._sd.close()  # Close the underlying serial port.
        self._device = None
        self._awake = False

    def _ensure_device(self) -> SDS011:
        if self._device is None:
            self.connect()
        return self._device  # type: ignore[return-value]

    def _respect_min_interval(self) -> None:
        if self._last_query_at is None:
            return
        elapsed = time.monotonic() - self._last_query_at
        remaining = self.sensor_cfg.min_query_interval_s - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _wake_if_needed(self) -> bool:
        """
        Wake the device if it is currently sleeping.

        Returns True if a wake action occurred.
        """
        device = self._ensure_device()
        if self._awake:
            return False
        device.active = 1
        self._awake = True
        log.debug("Sensor woken before read")
        return True

    def _sleep_if_configured(self) -> None:
        if not self.sensor_cfg.sleep_after_read:
            return
        device = self._ensure_device()
        device.active = 0
        self._awake = False
        self._warmed_once = False
        log.debug("Sensor put to sleep after read")

    def _warmup_if_needed(self, just_woke: bool) -> None:
        warm_time = self.sensor_cfg.wake_before_read_s
        if warm_time <= 0:
            return
        # Only warm on first cycle or after waking from sleep to avoid repeated delays.
        if self.sensor_cfg.sleep_after_read:
            should_wait = just_woke
        else:
            should_wait = just_woke or not self._warmed_once
        if should_wait:
            log.debug("Warming sensor for %ss", warm_time)
            time.sleep(warm_time)
            self._warmed_once = True

    def _query_once(self) -> Measurement:
        device = self._ensure_device()
        response = device.query()
        if response.get("type") != "sample":
            raise ValueError(f"Unexpected response type: {response}")
        if response.get("checksum") is not True:
            raise ValueError("Checksum validation failed")
        values = response["value"]
        pm25 = float(values["pm2.5"])
        pm10 = float(values["pm10.0"])
        device_id_bytes: bytes = response.get("id", b"")
        device_id = device_id_bytes.hex() if isinstance(device_id_bytes, (bytes, bytearray)) else str(device_id_bytes)
        self._last_query_at = time.monotonic()
        return Measurement(
            pm25=pm25,
            pm10=pm10,
            timestamp=datetime.now(timezone.utc),
            device_id=device_id,
            port=self.serial_cfg.port,
        )

    def measure(self) -> Measurement:
        """
        Perform a single measurement with retries, warm-up, and optional sleep.
        """
        attempt = 0
        last_error: Optional[Exception] = None
        while attempt <= self.sensor_cfg.max_query_retries:
            attempt += 1
            try:
                just_woke = self._wake_if_needed()
                self._warmup_if_needed(just_woke)
                self._respect_min_interval()
                measurement = self._query_once()
                self._sleep_if_configured()
                return measurement
            except (SensorError, serial.SerialException, serial.serialutil.SerialException, ValueError) as exc:
                last_error = exc
                log.warning("Measurement attempt %s failed: %s", attempt, exc)
                time.sleep(1)
                # Force reconnection on next attempt to clear state.
                self.close()
        raise RuntimeError(f"Failed to read from sensor after {self.sensor_cfg.max_query_retries + 1} attempts") from last_error
