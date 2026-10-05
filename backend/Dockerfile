# syntax=docker/dockerfile:1
# Base images pinned by version AND digest.
ARG PYTHON_IMAGE=python:3.12.14-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

# --- builder: compile wheels (insightface needs a C++ compiler) -------------------------
FROM ${PYTHON_IMAGE} AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*
# The base image's pip has known advisories (pip-audit); use a fixed release.
RUN pip install "pip==26.2.*"
WORKDIR /build
COPY requirements-ml.txt .
RUN pip wheel --wheel-dir /wheels/ml -r requirements-ml.txt
COPY requirements.txt requirements-dev.txt ./
RUN pip wheel --wheel-dir /wheels/app -r requirements.txt \
    && pip wheel --wheel-dir /wheels/dev -r requirements-dev.txt

# --- runtime: no compiler toolchain --------------------------------------------------------
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    INSIGHTFACE_ROOT=/models MPLCONFIGDIR=/tmp/matplotlib

# libgomp1: OpenMP runtime for onnxruntime. Pick up Debian security updates at build time.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install "pip==26.2.*"

COPY --from=builder /wheels/ml /wheels/ml
COPY requirements-ml.txt .
RUN pip install --no-index --find-links /wheels/ml -r requirements-ml.txt && rm -rf /wheels/ml

# Face model: pinned source, per-file SHA-256 verified (build fails on mismatch).
COPY scripts/fetch_model.py /tmp/fetch_model.py
RUN python /tmp/fetch_model.py /models && rm /tmp/fetch_model.py

COPY --from=builder /wheels/app /wheels/app
COPY requirements.txt .
RUN pip install --no-index --find-links /wheels/app -r requirements.txt && rm -rf /wheels/app

# Test/scan tooling only in dev images; production images stay minimal.
ARG DEV=0
COPY --from=builder /wheels/dev /wheels/dev
COPY requirements-dev.txt .
# Production images don't need an installer at runtime: pip is removed entirely.
RUN if [ "$DEV" = "1" ]; then pip install --no-index --find-links /wheels/dev -r requirements-dev.txt; \
    else pip uninstall -y pip; fi \
    && rm -rf /wheels/dev

COPY . .

RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

# The deployed build, shown by /api/health and attached to error reports (release).
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
