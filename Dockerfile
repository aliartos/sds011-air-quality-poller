FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sds011_poller ./sds011_poller
COPY README.md .
COPY config.example.toml ./config.example.toml

CMD ["python", "-m", "sds011_poller", "--config", "/config/config.toml"]
