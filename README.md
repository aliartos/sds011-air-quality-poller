# SDS011 Air Quality Poller (Ubuntu / Docker)

A small, reliable tool that reads **PM2.5** and **PM10** particulate measurements from an **SDS011** air-quality sensor and makes the results easy to store, inspect, and visualize.

This project is intended for “set it and forget it” home or small-office monitoring: plug the sensor into a Linux machine (via a USB-UART dongle), run the poller as a service, and you get a clean stream of measurements plus an easy path to dashboards.

---

## What it does

- **Reads PM2.5 / PM10** from an SDS011 sensor over a serial (USB) connection.
- Runs in **query (passive) mode**, meaning the sensor is sampled periodically instead of streaming constantly.
- Writes results as **JSON Lines (JSONL)** so they are:
  - human-readable,
  - easy to archive,
  - easy to post-process or correct.
- Designed to be **stable**:
  - configurable warm-up,
  - retries on transient failures,
  - optional sleep between samples to reduce wear.
- Ready monitoring stacks: 
  - Docker Compose + Prometheus + Grafana, plus a file sink for host-side archiving.

## Features
- Enforces passive/query mode on startup; optional wake/warmup/sleep between cycles.
- Bounded retries, backoff after consecutive failures, and jittered schedule.
- Prometheus exporter (HTTP) and optional JSONL/logfmt output with host file sink.
- Zero-reading guard: if pm25=pm10=0.0, re-queries once after 1–2s; if still zero, marks `status="suspect"` and does not advance last_success.
- Docker Compose stack with Prometheus scrape and pre-provisioned Grafana dashboard.

## Requirements
- Local run: Python 3.11+ (or 3.8+ with `tomli`), ability to open the serial device (`dialout` group on Debian/Ubuntu), and a stable device path like `/dev/serial/by-id/...`.
- Docker run: Docker + Docker Compose, host access to the serial device (the user must be allowed to use Docker and the tty), and the correct device mapping in `docker-compose.yml`.

## Configuration (TOML)
Copy the example and adjust:
- `serial.port`: set to your stable path (e.g., `/dev/serial/by-id/...`).
- `sensor.*`: warmup/sleep/retry knobs.
- `schedule.*`: interval, jitter, backoff thresholds.
- `output.format`: `jsonl`, `logfmt`, or `prometheus`.
- `output.file_path`: optional JSONL append (works alongside Prometheus).
- `output.prometheus_host` / `output.prometheus_port`: bind for exporter.

## Local quick start
1. `python3 -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. `cp config.example.toml config.toml` and edit `serial.port` to `/dev/serial/by-id/...`
4. Choose output: set `output.format` and optionally `output.file_path`.
5. Run: `python -m sds011_poller --config config.toml --log-level DEBUG`

## Docker + Prometheus + Grafana
1. Ensure `config.toml` uses your device path and `output.format = "prometheus"`.
2. Adjust `devices` in `docker-compose.yml` to match `ls -l /dev/serial/by-id/`.
3. Start stack: `docker compose up --build`
4. Host paths:
   - Config: `./config.toml` -> `/config/config.toml`
   - Data log: `./data` -> `/data` (set `output.file_path = "/data/readings.jsonl"`)
5. URLs:
   - Prometheus: http://localhost:9090
   - Grafana: http://localhost:3000 (admin/admin), dashboard auto-provisioned from `docker/grafana/dashboards-json/sds011.json`

## Prometheus metrics
- `sds011_pm25_ugm3`, `sds011_pm10_ugm3` (labels: port, device_id)
- `sds011_last_success_timestamp_seconds`, `sds011_last_success_timestamp_millis`, `sds011_last_status`
- `sds011_errors_total` (labels: port, cause), `sds011_last_error_timestamp_seconds`
- On suspect zero read, `cause="suspect_zero"` increments errors, and `last_success` is not updated.

## Zero-reading handling
- If pm25 and pm10 are both 0.0, the poller waits 1–2s, re-queries once, and marks the sample as `status="suspect"` if still zero.
- Suspect samples are emitted to stdout/log/file; Prometheus records error counters and `last_status=0` but leaves `last_success` untouched.

## Troubleshooting
- Check device path: `ls -l /dev/ttyUSB* /dev/serial/by-id/* 2>/dev/null`
- Permission: ensure your user is in `dialout` (re-login after adding).
- Prometheus up: visit `http://localhost:9090/api/v1/label/__name__/values`
- Grafana dashboard missing data: confirm poller logs show measurements and that Prometheus scrape target `poller:9101` is UP.
