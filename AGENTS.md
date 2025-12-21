# SDS011 Poller — Implementation Notes

## Current Implementation
- Entry point: `python -m sds011_poller` reads TOML via `load_config()` and starts `Poller`.
- Sensor client: `SensorClient` wraps `simple-sds011` in passive/query mode, manages wake/sleep, warmup, min query interval, retries, and reconnects.
- Scheduling: `Poller` loops with `interval_s` plus +/- `jitter_s`, enforces `max_consecutive_failures` then backs off `backoff_s`.
- Validation: rejects non-sample frames or failed checksums; retries; treats pm25/pm10 == 0 as suspect (one retry) and logs/prom marks accordingly.
- Output: formats to `jsonl` or `logfmt`, optional append to `output.file_path`. Prometheus mode runs an HTTP exporter (`sds011_*` gauges/counters) and still appends JSONL when `file_path` is set.
- Configured defaults live in `config.example.toml`; runtime config in `config.toml`.

## Configuration Surface
- `[serial]`: `port` (required), `baud` (9600), `timeout_ms` (1500).
- `[sensor]`: `mode="query"` only, `wake_before_read_s`, `sleep_after_read`, `max_query_retries`, `min_query_interval_s`.
- `[schedule]`: `interval_s`, `jitter_s`, `max_consecutive_failures`, `backoff_s`.
- `[output]`: `format` (`jsonl`|`logfmt`|`prometheus`), `prometheus_host`, `prometheus_port`, optional `file_path` for append-only logging.

## Data Flow & Interfaces
1) CLI (`__main__.py`): parses `--config`, sets logging, loads TOML.
2) Config: `load_config(Path)` returns `AppConfig` composed of `SerialConfig`, `SensorConfig`, `ScheduleConfig`, `OutputConfig`; validates mode, format, ranges.
3) Poller (`Poller.run_forever()`):
   - Calls `SensorClient.measure()`; on zero reading, retries once after 1–2s.
   - Tracks `_consecutive_failures`; on each error emits formatted line or Prom metrics; after threshold, sleeps `backoff_s`.
   - Calculates next delay with jitter and sleeps.
4) Sensor (`SensorClient`):
   - Ensures passive mode (`set_up(mode=MODE_PASSIVE, active=1)`), clears serial buffer.
   - `measure()` enforces min interval, optional warmup when waking, retries `_query_once()` up to `max_query_retries`, optional post-read sleep.
   - `_query_once()` expects `"type":"sample"` with `checksum=True`, returns `Measurement(pm25, pm10, timestamp, device_id, port)`.
5) Output (`output.py`):
   - `format_measurement(measurement, fmt, status="ok")` -> string line.
   - `format_error(exc, attempt, max_attempts, fmt)` -> error line.
   - `PrometheusExporter` exposes `/metrics` via `start_http_server`, updates gauges/counters on success/error/suspect.
6) Optional file sink: when `output.file_path` is set, lines are appended with line buffering alongside stdout/Prometheus.

## Operational Notes
- Target runtime Python 3.11+; falls back to `tomli` if needed.
- Serial path: prefer `/dev/serial/by-id/...` for stability; current config uses `/dev/ttyUSB0`.
- Warmup: controlled by `wake_before_read_s`; applies on first wake or after sleep.
- Sleep: `sleep_after_read=true` powers down fan/laser after each cycle; otherwise device stays active but honors warmup-once logic.
- Errors include `SensorError`, `SerialException`, and checksum/response validation; each failure triggers reconnect on next attempt.

## Architecture Overview
- Process model: single long-running Python process; no threads besides Prometheus HTTP server thread spawned by `prometheus_client`.
- Modules: CLI/bootstrap (`__main__.py`), configuration (`config.py`), polling loop (`poller.py`), sensor I/O (`sensor_client.py`), output/metrics (`output.py`).
- External deps: `simple-sds011` for protocol/serial framing, `pyserial` via that library, optional `prometheus_client`.
- State: `_consecutive_failures`, `_last_query_at`, `_awake`, `_warmed_once`, and optional file handle plus Prometheus gauges/counters.
- Failure handling: retries per read, circuit-breaker backoff after threshold, reconnect on every failed attempt.
- Output sinks: stdout/logfmt/Prometheus; optional JSONL file (append-only, line-buffered) for host volume capture.

## Future Development
- Hardening: udev/by-id path default, single-instance lock, systemd unit with restart policy, container/service install docs.
- Observability: textfile collector writer option; richer logging categories; device metadata surfacing.
- Testing: unit tests for config validation, scheduler/backoff timing, sensor client with mocked serial; integration smoke tests.
