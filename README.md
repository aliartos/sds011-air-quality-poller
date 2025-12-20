# SDS011 Periodic Poller

Python service for querying an SDS011 particulate matter sensor in passive/query mode and emitting readings as JSONL/logfmt or directly as Prometheus metrics.

## Local quick start (no docker)
1. Create a virtualenv (recommended due to PEP 668): `python3 -m venv .venv && source .venv/bin/activate`
2. Install deps: `pip install -r requirements.txt`
3. Copy and edit config: `cp config.example.toml config.toml` then set `serial.port` to `/dev/serial/by-id/...`
4. Choose an output format:
   - JSON to stdout: `output.format = "jsonl"` (default logging format)
   - Logfmt to stdout: `output.format = "logfmt"`
   - Prometheus HTTP exporter: `output.format = "prometheus"` (listens on `output.prometheus_host:output.prometheus_port`)
   - Optional file sink: set `output.file_path` to append JSONL lines (also works while Prometheus is enabled).
5. Run: `python -m sds011_poller --config config.toml`

When using Prometheus output, the exporter exposes:
- `sds011_pm25_ugm3` and `sds011_pm10_ugm3` (labels: `port`, `device_id`)
- `sds011_last_success_timestamp_seconds` / `sds011_last_success_timestamp_millis` / `sds011_last_status`
- `sds011_errors_total` (labels: `port`, `cause`) and `sds011_last_error_timestamp_seconds`

## Docker + Prometheus + Grafana
1. Ensure `config.toml` has `output.format = "prometheus"` and `serial.port` set to your device (e.g., `/dev/serial/by-id/...`).  
2. Build and launch the stack (poller + Prometheus + Grafana):
   - `docker compose up --build`
3. Device mapping: the compose file maps `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`. Adjust the `devices` entry (and `config.toml`) to match the path shown by `ls -l /dev/serial/by-id/`.
4. Data persistence: measurements/errors are appended to `output.file_path` inside the container; the compose file mounts `./data` to `/data`, so set `output.file_path = "/data/readings.jsonl"` to keep a host-side log.
5. URLs:
   - Prometheus: http://localhost:9090
   - Grafana: http://localhost:3000 (default admin/admin)
6. Grafana is pre-provisioned with a Prometheus data source and an SDS011 dashboard (`docker/grafana/dashboards-json/sds011.json`).

## Troubleshoot


```
ls -l /dev/ttyUSB* /dev/serial/by-id/* 2>/dev/null
```

http://localhost:9090/api/v1/label/__name__/values

