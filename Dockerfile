# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# ffmprobe ships with ffmpeg; OpenCV/Ultralytics runtime libs for headless use
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY assets ./assets

RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -e .

ENTRYPOINT ["python", "-m", "youtube_automation.app"]
CMD ["--help"]

FROM runtime AS test

RUN pip install --no-cache-dir -e ".[dev]"
COPY tests ./tests

ENTRYPOINT []
CMD ["python", "-m", "pytest"]
