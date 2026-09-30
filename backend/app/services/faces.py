"""Face detection + embeddings for the application, via the configured FaceEngine.

This is the only module application code uses for faces; the model behind it is chosen
by FACE_ENGINE (see services/face_engine.py). Embeddings are L2-normalised, so cosine
similarity = dot product and cosine distance = 1 - similarity.
"""

from PIL import Image

from app.core.config import get_settings
from app.services.face_engine import DetectedFace, SelfieFace, get_engine

__all__ = ["DetectedFace", "SelfieFace", "analyze_selfie", "current_model_id", "detect_faces"]

# Detectors resize their input internally; feeding a much larger image only costs
# memory, while ~2000px keeps enough detail for good aligned face crops.
DETECT_MAX_SIDE = 2048


def current_model_id() -> str:
    """The embedding space of the configured engine (stored on, and filtered by, faces)."""
    return get_engine().model_id


def detect_faces(img: Image.Image) -> list[DetectedFace]:
    """Detect every face in an RGB image. Bboxes are returned in `img`'s pixel space."""
    scale = 1.0
    work = img
    if max(img.size) > DETECT_MAX_SIDE:
        scale = max(img.size) / DETECT_MAX_SIDE
        work = img.copy()
        work.thumbnail((DETECT_MAX_SIDE, DETECT_MAX_SIDE), Image.Resampling.LANCZOS)
    min_score = get_settings().face_min_det_score
    return [
        DetectedFace(bbox=tuple(v * scale for v in f.bbox), det_score=f.det_score, embedding=f.embedding)  # type: ignore[arg-type]
        for f in get_engine().detect(work)
        if f.det_score >= min_score
    ]


def analyze_selfie(img: Image.Image) -> list[SelfieFace]:
    """All faces in a selfie (no score filtering: the quality gate reports low scores)."""
    return get_engine().analyze_selfie(img)
