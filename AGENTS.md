# SDS011 Periodic Poller (Ubuntu) — Plan & Implementation (Python + TOML)

## 1. Objective

Build a robust, long-running Linux service that:
- Connects to an SDS011 sensor via USB-UART (CH341 on Ubuntu).
- Forces **query/passive mode** (no continuous streaming).
- Performs a **periodic measurement** at a configurable interval.
- Emits readings in a stable format (initially stdout JSONL), with a clean path to Prometheus/Grafana later.

Rationale:
- In **passive/query mode**, the SDS011 only returns data when explicitly queried. :contentReference[oaicite:0]{index=0}  
- The sensor supports an internal **sleep/working** model and a sampling **period** concept to extend lifetime and reduce noise. :contentReference[oaicite:1]{index=1}  

---

## 2. Scope (phased)

### Phase A — “Solid Reader” (MVP)
- Read configuration from TOML.
- Open serial port reliably.
- Put sensor in query mode at startup (idempotent).
- Periodically:
  - Wake sensor (if configured)
  - Warm up (if configured)
  - Trigger a query measurement
  - Validate frame
  - Emit PM2.5 / PM10
  - Optionally sleep sensor again
- Structured logging and basic failure handling (timeouts/retries/backoff).

### Phase B — Operational Hardening
- Stable device path via `/dev/serial/by-id` or udev SYMLINK (avoid `/dev/ttyUSB0` drift). :contentReference[oaicite:2]{index=2}  
- systemd service unit with restart policy. :contentReference[oaicite:3]{index=3}  
- Single-instance locking.
- Test harness for parser and serial I/O abstractions.

### Phase C — Prometheus/Grafana Integration
Choose one:
1) **Node Exporter Textfile Collector** (write `.prom` file periodically) :contentReference[oaicite:4]{index=4}  
2) **Native HTTP Exporter** via `prometheus-client` (expose `/metrics`) :contentReference[oaicite:5]{index=5}  

---

## 3. Technology Choices

### Python runtime
- Prefer Python **3.11+** to use the stdlib TOML parser `tomllib`. :contentReference[oaicite:6]{index=6}
- Follow best practises, e.g. venv etc
- If Python < 3.11 is unavoidable, fallback to `tomli` (compat option).

### Serial I/O
- `pyserial` for device access and timeouts. Its `read()` behavior with timeouts is well-defined and enables robust framing logic. :contentReference[oaicite:7]{index=7}  

### SDS011 protocol / library
Start with **simple-sds011** to reduce protocol risk:
- Supports `mode` (continuous vs passive), `active` (fan/laser on/off), `period`, and querying in passive mode. :contentReference[oaicite:8]{index=8}  

Keep a thin abstraction layer (`SensorClient` interface) so we can switch to:
- `sds011lib` (typed, broader coverage) if needed. :contentReference[oaicite:9]{index=9}  
- Or a custom protocol implementation using known command frames if you want full control. :contentReference[oaicite:10]{index=10}  

---

## 4. Configuration (TOML)

### `config.toml` (example)
```toml
[serial]
port = "/dev/ttyUSB0"         # later: /dev/serial/by-id/... or /dev/sds011
baud = 9600
timeout_ms = 1500

[sensor]
mode = "query"                # "query" only for now
wake_before_read_s = 30       # warm-up before querying (typical: ~30s)
sleep_after_read = true
max_query_retries = 2
min_query_interval_s = 3      # keep >= 3s as safety baseline

[schedule]
interval_s = 60               # periodic check cadence
jitter_s = 2                  # random +/- jitter to avoid strict periodicity
max_consecutive_failures = 5
backoff_s = 10                # wait before reconnect attempts

[output]
format = "jsonl"              # "jsonl" | "logfmt"
```

 

## 5. Repository Layout (proposed)

`sds011-poller/   pyproject.toml   README.md   config/     config.example.toml   src/     sds011_poller/       __init__.py       main.py       config.py       logging.py       scheduler.py       sensor/         __init__.py         client.py          # SensorClient interface         simple_sds011.py    # implementation using simple-sds011       output/         __init__.py         stdout_jsonl.py   systemd/     sds011-poller.service   udev/     99-sds011.rules   tests/     test_parser.py     test_scheduler.py`

---

## 6. Core Runtime Flow (state machine)

### Startup

1. Load and validate TOML config (`tomllib`).
    
2. Resolve port path:
    
    - Use configured `serial.port`.
        
    - Log a warning if it looks like `/dev/ttyUSB*` and recommend `/dev/serial/by-id`. [wiki.domoticz.com+1](https://wiki.domoticz.com/PersistentUSBDevices?utm_source=chatgpt.com)
        
3. Open serial with `pyserial`:
    
    - Set `baud=9600`, `timeout=timeout_ms`.
        
    - Handle exceptions and retry with backoff. [pyserial.readthedocs.io+1](https://pyserial.readthedocs.io/en/latest/pyserial_api.html?utm_source=chatgpt.com)
        
4. Initialize sensor:
    
    - Set `mode = passive/query`. [PyPI+1](https://pypi.org/project/simple-sds011/?utm_source=chatgpt.com)
        
    - Set `active = 1` if using app-managed sleep/wake.
        

### Periodic loop

For each tick:

1. If configured, `wake` (or `active=1`).
    
2. Sleep for `wake_before_read_s` warmup.
    
3. Perform `query`:
    
    - Up to `max_query_retries` retries on timeout/checksum failure.
        
4. Emit reading:
    
    - `stdout` JSONL line: `{"ts":"...","pm25":...,"pm10":...,"status":"ok"}`
        
5. If configured, `sleep` (or `active=0`).
    
6. Sleep until next tick (with jitter).
    

### Error handling

- Consecutive failure counter:
    
    - If exceeds `max_consecutive_failures`, close port and re-open after `backoff_s`.
        
- Always log:
    
    - cause category: `timeout`, `bad_frame`, `checksum`, `serial_exception`, `config_error`.
        

---

## 7. Output Contract (initial)

### JSONL (stdout)

One line per successful cycle:

`{"ts":"2025-12-20T18:10:00+02:00","pm25":12.3,"pm10":19.8,"unit":"ug/m3","status":"ok"}`

One line per failed cycle (still valuable for ops):

`{"ts":"...","status":"error","error":"timeout","attempt":2}`

This is intentionally compatible with:

- journald ingestion (systemd)
    
- later Prometheus exporter module
    
- log-based pipelines (e.g., Fluent Bit)
    

---

## 8. Stable Device Naming (recommended for production)

### Option A — Prefer `/dev/serial/by-id`

This is usually the simplest and most stable approach; avoid hardcoding `/dev/ttyUSB0`. [wiki.domoticz.com+1](https://wiki.domoticz.com/PersistentUSBDevices?utm_source=chatgpt.com)

Steps:

1. Plug the dongle in.
    
2. Use:
    
    - `ls -l /dev/serial/by-id/`
        
3. Copy the path into `config.toml`.
    

### Option B — udev SYMLINK (if you need a short name)

Create `/etc/udev/rules.d/99-sds011.rules` (template):

`SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", SYMLINK+="sds011", GROUP="dialout", MODE="0660"`

Notes:

- Vendor/product IDs are typically discovered via `lsusb`.
    
- Reload rules and replug the device.  
    General udev symlink patterns are well-established. [Ask Ubuntu+2wiki.domoticz.com+2](https://askubuntu.com/questions/783357/create-a-symlink-in-dev-using-etc-udev-rules?utm_source=chatgpt.com)  
    Applying updated rules commonly requires a udev reload and replug. [Raspberry Pi Forums](https://forums.raspberrypi.com/viewtopic.php?t=290401&utm_source=chatgpt.com)
    

---

## 9. systemd Service (run continuously)

### `systemd/sds011-poller.service` (template)

`[Unit] Description=SDS011 periodic PM poller After=network.target  [Service] Type=simple User=kostas Group=dialout WorkingDirectory=/opt/sds011-poller ExecStart=/opt/sds011-poller/.venv/bin/python -m sds011_poller.main --config /etc/sds011/config.toml Restart=on-failure RestartSec=5 StartLimitIntervalSec=30 StartLimitBurst=3  # Optional: load env vars from file # EnvironmentFile=/etc/default/sds011-poller  [Install] WantedBy=multi-user.target`

Notes:

- `Restart=on-failure` and restart semantics are defined in the systemd service docs. [FreeDesktop+1](https://www.freedesktop.org/software/systemd/man/systemd.service.html?utm_source=chatgpt.com)
    
- Unit file knobs like `ExecStartPre/ExecStartPost`, restart tuning, etc., are standard and documented. [Red Hat Docs](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/using_systemd_unit_files_to_customize_and_optimize_your_system/assembly_working-with-systemd-unit-files_working-with-systemd?utm_source=chatgpt.com)
    
- Environment files are a conventional way to externalize service settings when needed. [Flatcar+1](https://www.flatcar.org/docs/latest/setup/systemd/environment-variables?utm_source=chatgpt.com)
    

---

## 10. Prometheus/Grafana Integration (later)

### Path 1: Node Exporter Textfile Collector

- App writes `sds011.prom` in a configured directory.
    
- Node exporter scrapes it when started with `--collector.textfile.directory=...`. [Robust Perception+1](https://www.robustperception.io/using-the-textfile-collector-from-a-shell-script?utm_source=chatgpt.com)
    

Example metrics:

`sds011_pm25_ugm3 12.3 sds011_pm10_ugm3 19.8 sds011_last_success_unixtime 1734711000`

### Path 2: Native HTTP exporter

- Add `prometheus-client` and expose `/metrics` via `start_http_server()`. [GitHub+1](https://github.com/prometheus/client_python?utm_source=chatgpt.com)
    
- Follow Prometheus exporter guidance for naming/labels and failure semantics. [Prometheus](https://prometheus.io/docs/instrumenting/writing_exporters/?utm_source=chatgpt.com)
    

---

## 11. Testing Strategy

1. **Unit tests**
    
    - Config parsing/validation (TOML fields, ranges, required keys).
        
    - Scheduler logic (interval, jitter bounds, backoff behavior).
        
2. **Protocol integration**
    
    - Mock `pyserial.Serial` to inject frames/timeouts.
        
3. **Hardware smoke test**
    
    - Run a 10-minute test with `interval_s=10`, log PM values, ensure no memory growth and clean shutdown.
        

---

## 12. Acceptance Criteria (Phase A)

- Service runs for 24h without manual intervention.
    
- Handles temporary unplug/replug:
    
    - recovers within backoff window
        
- Emits at least:
    
    - `pm25`, `pm10`, timestamp, status
        
- Query mode enforced on startup (even if sensor retained a previous mode). [GitHub+1](https://github.com/opendata-stuttgart/sensors-software/issues/379?utm_source=chatgpt.com)
    

---

## 13. Next Implementation Step (what we will build first)

Implement:

- `config.py` using `tomllib` [Python documentation](https://docs.python.org/3/library/tomllib.html?utm_source=chatgpt.com)
    
- `sensor/simple_sds011.py` using `simple-sds011` mode/active/period/query semantics [PyPI+1](https://pypi.org/project/simple-sds011/?utm_source=chatgpt.com)
    
- `main.py` with loop + retries + JSONL output
    
- systemd unit template
    

Once Phase A is stable, we add:

- udev/by-id stabilization
    
- Prometheus output module (textfile or HTTP)
    

`If you want, I can also generate (in the next message) a full initial project skeleton (all files listed above, with working code) that you can paste into your repo directly. ::contentReference[oaicite:28]{index=28}`

add all previous sections in an md file

Thought for 33s

# SDS011 Periodic Poller (Ubuntu) — Plan & Implementation (Python + TOML)

## 1. Objective

Build a robust, long-running Linux service that:

- Connects to an **SDS011** sensor via USB-UART (your dongle is **CH341**).
    
- Forces **query/passive mode** (no continuous streaming).
    
- Performs a **periodic measurement** at a configurable interval.
    
- Emits readings in a stable format (initially **stdout JSONL**), with a clean path to **Prometheus/Grafana** later.
    

In **passive/query mode**, the SDS011 only returns sample data when explicitly queried, which is ideal for periodic polling and sensor longevity. [PyPI+2cdn-reichelt.de+2](https://pypi.org/project/simple-sds011/?utm_source=chatgpt.com)

---

## 2. Current Environment Snapshot (as implemented today)

- Kernel detects: `ch341-uart converter detected`
    
- Device attached to: **`/dev/ttyUSB0`**
    
- Permissions: `crw-rw---- root dialout … /dev/ttyUSB0`
    

This is the correct baseline; next steps focus on stability (e.g., `/dev/serial/by-id` or a udev symlink) and an application that tolerates disconnects/reconnects.

---

## 3. Scope and Phasing

### Phase A — “Solid Reader” (MVP)

- Read configuration from TOML.
    
- Open serial port reliably.
    
- Put sensor in **query mode** at startup (idempotent).
    
- Periodically:
    
    - Wake sensor (if configured)
        
    - Warm up (if configured)
        
    - Trigger a query measurement
        
    - Validate frame
        
    - Emit PM2.5 / PM10
        
    - Optionally sleep sensor again
        
- Structured logging and basic failure handling (timeouts/retries/backoff).
    

### Phase B — Operational Hardening

- Stable device path via `/dev/serial/by-id` or udev SYMLINK (avoid `/dev/ttyUSB0` drift).
    
- systemd service unit with restart policy.
    
- Single-instance locking.
    
- Test harness for config + scheduler + sensor client.
    

### Phase C — Prometheus/Grafana Integration

Pick one:

1. **Node Exporter Textfile Collector** (write `.prom` file periodically) [GitHub+2prometheus.github.io+2](https://github.com/prometheus-community/node-exporter-textfile-collector-scripts?utm_source=chatgpt.com)
    
2. **Native HTTP Exporter** (expose `/metrics` and follow exporter conventions) [Prometheus+1](https://prometheus.io/docs/instrumenting/writing_exporters/?utm_source=chatgpt.com)
    

---

## 4. Functional and Non-Functional Requirements

### Functional

1. Serial: connect to configured port at **9600 baud**.
    
2. Sensor: force **passive/query mode** at startup. [PyPI+2cdn-reichelt.de+2](https://pypi.org/project/simple-sds011/?utm_source=chatgpt.com)
    
3. Scheduler: run measurements every `interval_s` with optional jitter.
    
4. Output: print one reading per cycle, machine-parseable.
    

### Non-Functional

- Robust to: partial reads, stale bytes, checksum errors, device unplug/replug.
    
- Observability: structured logs + counters for failures.
    
- Configuration-driven behavior (no code edits for interval/warmup/sleep).
    

---

## 5. Protocol Strategy (Query Mode + Periodic Sampling)

### Reporting mode

We use **passive/query mode**, meaning the sensor transmits sample data only when the host sends a query. [PyPI+2nettigo.pl+2](https://pypi.org/project/simple-sds011/?utm_source=chatgpt.com)

### Working/sleep model and warmup

Two viable strategies:

**Strategy A (recommended for MVP: app-managed warmup/sleep)**  
Per cycle:

- Set “work”/active on
    
- Warm up for `wake_before_read_s` (e.g., ~30s)
    
- Send query, read once
    
- Optionally sleep/disable after read
    

This aligns with common operational practice where the SDS011 is powered for a warmup interval before measurement. [PyPI+1](https://pypi.org/project/simple-sds011/?utm_source=chatgpt.com)

**Strategy B (device-managed period)**  
Configure the sensor’s internal **period** (1–30 minutes) and query near its ready window. The `simple-sds011` library documents that the device sleeps for `N*60 - 30` seconds and warms up for ~30 seconds before sampling. [PyPI+1](https://pypi.org/project/simple-sds011/?utm_source=chatgpt.com)

For Phase A, implement Strategy A first (predictable and easy to reason about), then add Strategy B as an optional mode.

---

## 6. Technology Choices

### Python runtime and TOML

- Target Python **3.11+** and use the standard library’s `tomllib` for TOML parsing. `tomllib` is read-only (parsing; no writing). [Python documentation+1](https://docs.python.org/3/library/tomllib.html?utm_source=chatgpt.com)
    

### Serial I/O

- Use `pyserial`. With a configured timeout, `read(size)` may return fewer bytes than requested; this is important for robust framing/accumulation logic. [pyserial.readthedocs.io+1](https://pyserial.readthedocs.io/en/latest/pyserial_api.html?utm_source=chatgpt.com)
    

### SDS011 driver

- Start with **`simple-sds011`** (PyPI) for rapid correctness:
    
    - `mode` (continuous vs passive)
        
    - `active` (fan/laser on/off)
        
    - `period` (0 or 1–30 minutes) with documented warmup model
        
    - query operation in passive mode [PyPI](https://pypi.org/project/simple-sds011/?utm_source=chatgpt.com)
        

Keep an internal interface so you can swap to a custom protocol implementation later if needed (the SDS011 datasheet and common protocol PDFs describe command frames and query mode). [cdn-reichelt.de+1](https://cdn-reichelt.de/documents/datenblatt/X200/SDS011-DATASHEET.pdf?utm_source=chatgpt.com)

---

## 7. Configuration (TOML)

### Example `config.toml`

`[serial] port = "/dev/ttyUSB0"          # recommended later: /dev/serial/by-id/... or /dev/sds011 baud = 9600 timeout_ms = 1500  [sensor] mode = "query"                 # "query" only for now wake_before_read_s = 30        # warm-up before querying sleep_after_read = true max_query_retries = 2 min_query_interval_s = 3       # safety baseline  [schedule] interval_s = 60                # periodic check cadence jitter_s = 2                   # random +/- jitter max_consecutive_failures = 5 backoff_s = 10                 # wait before reconnect attempts  [output] format = "jsonl"               # "jsonl" | "logfmt"`

Notes:

- The 30s warmup model is explicitly described for SDS011 period behavior in `simple-sds011` and mirrored by ESPHome’s SDS011 guidance. [PyPI+1](https://pypi.org/project/simple-sds011/?utm_source=chatgpt.com)
    

---

## 8. Proposed Repository Layout

`sds011-poller/   pyproject.toml   README.md   config/     config.example.toml   src/     sds011_poller/       __init__.py       main.py       config.py       logging.py       scheduler.py       sensor/         __init__.py         client.py          # SensorClient interface         simple_sds011.py    # implementation using simple-sds011       output/         __init__.py         stdout_jsonl.py   systemd/     sds011-poller.service   udev/     99-sds011.rules   tests/     test_scheduler.py     test_config.py`

---

## 9. Application Architecture

### Modules and responsibilities

- **`config.py`**
    
    - Load TOML with `tomllib.load()` and validate ranges/types. [Python documentation](https://docs.python.org/3/library/tomllib.html?utm_source=chatgpt.com)
        
- **`sensor/client.py`**
    
    - Define a minimal interface: `set_query_mode()`, `wake()`, `sleep()`, `query()`.
        
- **`sensor/simple_sds011.py`**
    
    - Implement the interface via `simple-sds011`. [PyPI](https://pypi.org/project/simple-sds011/?utm_source=chatgpt.com)
        
- **`scheduler.py`**
    
    - Tick loop with interval, jitter, deadlines, retry handling.
        
- **`output/stdout_jsonl.py`**
    
    - Emit JSON lines; later add `output/prometheus_*`.
        

---

## 10. Core Runtime Flow (State Machine)

### Startup

1. Load and validate TOML configuration (`tomllib`). [Python documentation](https://docs.python.org/3/library/tomllib.html?utm_source=chatgpt.com)
    
2. Open serial port using `pyserial` with `timeout=timeout_ms/1000`. [pyserial.readthedocs.io+1](https://pyserial.readthedocs.io/en/latest/pyserial_api.html?utm_source=chatgpt.com)
    
3. Initialize sensor:
    
    - Force passive/query mode (idempotent). [PyPI+1](https://pypi.org/project/simple-sds011/?utm_source=chatgpt.com)
        
    - Optionally set `active=1` to ensure fan/laser is on before warmup, then manage sleep around each sample. [PyPI](https://pypi.org/project/simple-sds011/?utm_source=chatgpt.com)
        

### Periodic loop (each cycle)

1. Wake/activate (if configured).
    
2. Sleep for `wake_before_read_s` warmup.
    
3. Query measurement (with up to `max_query_retries`).
    
4. Emit result (JSONL).
    
5. Sleep/deactivate (if configured).
    
6. Wait until next tick (include `jitter_s`).
    

---

## 11. Output Contract (Phase A)

### JSONL on stdout

Success:

`{"ts":"2025-12-20T18:10:00+02:00","pm25":12.3,"pm10":19.8,"unit":"ug/m3","status":"ok"}`

Error (still useful for operations):

`{"ts":"2025-12-20T18:11:00+02:00","status":"error","error":"timeout","attempt":2}`

This is designed to be friendly to journald/systemd logging and later ingestion.

---

## 12. Robustness Checklist (do these early)

1. **Stable device path**
    
    - Prefer `/dev/serial/by-id/...` (best default) or a udev symlink.
        
2. **Framing + partial read tolerance**
    
    - `pyserial.read()` can return fewer bytes than requested with timeouts; always accumulate and validate before parsing. [pyserial.readthedocs.io+1](https://pyserial.readthedocs.io/en/latest/pyserial_api.html?utm_source=chatgpt.com)
        
3. **Retry policy**
    
    - Short bounded retries per cycle; do not block indefinitely.
        
4. **Consecutive failure circuit breaker**
    
    - After `max_consecutive_failures`, close and re-open serial port after `backoff_s`.
        
5. **Single instance**
    
    - Use `flock` or PID file to prevent two services from reading the same tty.
        

---

## 13. Stable Device Naming (Production Recommendation)

### Option A — Use `/dev/serial/by-id`

- List stable identifiers:
    

`ls -l /dev/serial/by-id/`

Use that path in `config.toml`.

### Option B — udev SYMLINK `/dev/sds011`

Template udev rule (match CH341 commonly `idVendor=1a86`, `idProduct=7523`):

`SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", SYMLINK+="sds011", GROUP="dialout", MODE="0660"`

Reload and replug.

---

## 14. systemd Service (Phase B)

### `systemd/sds011-poller.service` (template)

`[Unit] Description=SDS011 periodic PM poller After=network.target  [Service] Type=simple User=kostas Group=dialout WorkingDirectory=/opt/sds011-poller ExecStart=/opt/sds011-poller/.venv/bin/python -m sds011_poller.main --config /etc/sds011/config.toml Restart=on-failure RestartSec=5 StartLimitIntervalSec=30 StartLimitBurst=3  [Install] WantedBy=multi-user.target`

Notes:

- `Restart=on-failure` and restart behavior are standard service options documented in `systemd.service`. [FreeDesktop](https://www.freedesktop.org/software/systemd/man/systemd.service.html?utm_source=chatgpt.com)
    
- Use restart burst/interval limits to avoid endless crash loops; these patterns are commonly recommended for “self-healing” services. [Red Hat+1](https://www.redhat.com/en/blog/systemd-automate-recovery?utm_source=chatgpt.com)
    

---

## 15. Prometheus/Grafana Integration (Phase C)

### Option 1: Node Exporter Textfile Collector

- App writes metrics to a `.prom` file (atomically) in a directory node_exporter scrapes.
    
- Prometheus ecosystem provides scripts and patterns for textfile collector usage; atomic writes are recommended. [GitHub+1](https://github.com/prometheus-community/node-exporter-textfile-collector-scripts?utm_source=chatgpt.com)
    

Example output:

`sds011_pm25_ugm3 12.3 sds011_pm10_ugm3 19.8 sds011_last_success_unixtime 1734711000`

### Option 2: HTTP `/metrics` exporter

- Follow Prometheus guidance when writing exporters (naming, labels, scrape-time behavior). [Prometheus](https://prometheus.io/docs/instrumenting/writing_exporters/?utm_source=chatgpt.com)
    

---

## 16. Testing Strategy

1. **Unit tests**
    
    - Config parsing/validation (types and ranges).
        
    - Scheduler timing logic (interval and jitter bounds).
        
2. **Serial mocking**
    
    - Mock sensor client methods to force timeouts/errors and validate backoff logic.
        
3. **Hardware smoke test**
    
    - Run 10–30 minutes at short interval (e.g., 10s) and verify stability.
        

---

## 17. Acceptance Criteria (Phase A)

- Runs continuously for **24 hours** without manual intervention.
    
- Enforces **query mode** at startup. [PyPI+1](https://pypi.org/project/simple-sds011/?utm_source=chatgpt.com)
    
- Produces consistent JSONL output:
    
    - `pm25`, `pm10`, timestamp, status
        
- Recovers from transient failures (timeouts/checksum errors) without crashing.
    

---

## 18. Implementation Milestones (Execution Plan)

### Milestone 1 — MVP Poller

- `config.py` (TOML parsing via `tomllib`). [Python documentation](https://docs.python.org/3/library/tomllib.html?utm_source=chatgpt.com)
    
- `sensor/simple_sds011.py` (query mode + wake/query/sleep).
    
- `main.py` (loop + retries + JSONL output).
    

### Milestone 2 — Hardening

- Switch `serial.port` to `/dev/serial/by-id/...` or `/dev/sds011`.
    
- Add systemd unit and install instructions. [FreeDesktop+1](https://www.freedesktop.org/software/systemd/man/systemd.service.html?utm_source=chatgpt.com)
    
- Add locking (`flock`) and improved error categorization.
    

### Milestone 3 — Prometheus Module

- Implement either textfile writer or HTTP exporter per the chosen approach. [GitHub+2Prometheus+2](https://github.com/prometheus-community/node-exporter-textfile-collector-scripts?utm_source=chatgpt.com)