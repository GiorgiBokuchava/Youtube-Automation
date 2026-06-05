# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# ffprobe ships with ffmpeg; OpenCV/Ultralytics runtime libs for headless use;
# libsndfile1 is required by soundfile (inaSpeechSegmenter dependency).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libsndfile1 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY assets ./assets

# inaSpeechSegmenter’s setup.py pulls tensorflow[and-cuda] + onnxruntime-gpu on Linux,
# which fails in our CPU-only slim image.  Install CPU stacks explicitly, then ina
# without re-resolving those platform deps.
RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -e . \
    && pip install --no-cache-dir \
         "tensorflow>=2.15,<2.21" \
         onnxruntime \
         pandas scikit-image pyannote.core Pyro4 pytextgrid soundfile \
    && pip install --no-cache-dir "inaSpeechSegmenter>=0.7,<0.8" --no-deps

ENTRYPOINT ["python", "-m", "youtube_automation.app"]
CMD ["--help"]

FROM runtime AS test

RUN pip install --no-cache-dir -e ".[dev]"
COPY tests ./tests

ENTRYPOINT []
CMD ["python", "-m", "pytest"]
