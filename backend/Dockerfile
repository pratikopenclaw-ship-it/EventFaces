FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    INSIGHTFACE_ROOT=/models

# g++ is needed to build insightface's Cython extension; libgomp for onnxruntime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-ml.txt .
RUN pip install -r requirements-ml.txt

# Bake the buffalo_l face model into the image (~280 MB, downloaded once at build).
RUN python -c "from insightface.app import FaceAnalysis; FaceAnalysis(name='buffalo_l', root='/models', providers=['CPUExecutionProvider'])" \
    && ls /models/models/buffalo_l

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
