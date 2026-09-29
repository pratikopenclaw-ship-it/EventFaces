"""Face detection + ArcFace embeddings (InsightFace buffalo_l, CPU).

The model is loaded lazily once per process. Embeddings are L2-normalized 512-d
vectors, so cosine similarity = dot product and cosine distance = 1 - similarity.
"""

import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
from PIL import Image

from app.core.config import get_settings

# Detector input is resized internally to det_size; feeding a much larger image only
# costs memory, while ~2000px keeps enough detail for good aligned face crops.
DETECT_MAX_SIDE = 2048

_lock = threading.Lock()


@dataclass(frozen=True)
class DetectedFace:
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in the input image's pixels
    det_score: float
    embedding: np.ndarray  # shape (512,), L2-normalized float32


@lru_cache
def _model() -> Any:
    from insightface.app import FaceAnalysis

    s = get_settings()
    app = FaceAnalysis(
        name="buffalo_l",
        root=s.face_model_root,
        allowed_modules=["detection", "recognition"],
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=-1, det_size=(s.face_det_size, s.face_det_size))
    return app


def detect_faces(img: Image.Image) -> list[DetectedFace]:
    """Detect every face in an RGB image. Bboxes are returned in `img`'s pixel space."""
    scale = 1.0
    work = img
    if max(img.size) > DETECT_MAX_SIDE:
        scale = max(img.size) / DETECT_MAX_SIDE
        work = img.copy()
        work.thumbnail((DETECT_MAX_SIDE, DETECT_MAX_SIDE), Image.Resampling.LANCZOS)

    bgr = np.ascontiguousarray(np.asarray(work.convert("RGB"))[:, :, ::-1])
    with _lock:
        raw = _model().get(bgr)

    min_score = get_settings().face_min_det_score
    faces = []
    for f in raw:
        if float(f.det_score) < min_score or f.normed_embedding is None:
            continue
        x1, y1, x2, y2 = (float(v) * scale for v in f.bbox)
        faces.append(
            DetectedFace(
                bbox=(x1, y1, x2, y2),
                det_score=float(f.det_score),
                embedding=np.asarray(f.normed_embedding, dtype=np.float32),
            )
        )
    return faces


@lru_cache
def _selfie_model() -> Any:
    """Selfies also need head pose (3D landmarks); photos don't, so they use the lighter model."""
    from insightface.app import FaceAnalysis

    s = get_settings()
    app = FaceAnalysis(
        name="buffalo_l",
        root=s.face_model_root,
        allowed_modules=["detection", "landmark_3d_68", "recognition"],
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=-1, det_size=(s.face_det_size, s.face_det_size))
    return app


@dataclass(frozen=True)
class SelfieFace:
    bbox: tuple[float, float, float, float]
    det_score: float
    pitch: float
    yaw: float  # > 0: nose toward the right of the raw (unmirrored) frame = the person's left
    roll: float
    embedding: np.ndarray


def analyze_selfie(img: Image.Image) -> list[SelfieFace]:
    """All faces in a selfie (no score filtering: the quality gate reports low scores)."""
    bgr = np.ascontiguousarray(np.asarray(img.convert("RGB"))[:, :, ::-1])
    with _lock:
        raw = _selfie_model().get(bgr)
    return [
        SelfieFace(
            bbox=tuple(float(v) for v in f.bbox),  # type: ignore[arg-type]
            det_score=float(f.det_score),
            pitch=float(f.pose[0]),
            yaw=float(f.pose[1]),
            roll=float(f.pose[2]),
            embedding=np.asarray(f.normed_embedding, dtype=np.float32),
        )
        for f in raw
        if f.normed_embedding is not None
    ]
