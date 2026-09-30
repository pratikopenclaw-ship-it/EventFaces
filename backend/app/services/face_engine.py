"""The face-recognition engine behind EventFaces, as a swappable interface.

Application code never talks to a model directly: it calls `services/faces.py`
(`detect_faces`, `analyze_selfie`), which delegates to the engine chosen by the
`FACE_ENGINE` setting:

- `insightface` (default): InsightFace buffalo_l on CPU, bundled in the image.
- `package.module:ClassName`: any class implementing `FaceEngine` (e.g. a GPU build, a
  different open model, or a cloud API such as AWS Rekognition).

Rules every engine must follow (checked by `tests/test_face_engine.py`):
- `detect` returns every face with a bbox in the input image's pixels, a detection score
  in [0, 1] and an **L2-normalised** embedding of length `embedding_dim` (cosine
  similarity = dot product; the database column is `vector(512)`).
- `analyze_selfie` also returns head pose in degrees, in InsightFace's convention:
  yaw > 0 = the person turned to *their* left; pitch < 0 = looking down.
- `model_id` names the embedding space. Faces are stored with it, and search only
  compares embeddings from the current model. After switching engines, run
  `python -m app.cli reindex-faces` and recalibrate `FACE_MATCH_THRESHOLD` /
  `MATCH_BEST_THRESHOLD` (similarity scales differ between models).

Privacy: an engine that sends images to a third party (a cloud API) moves biometric
processing outside your infrastructure. That needs a data-processing agreement, an EU
region, an updated consent text (bump `FACE_CONSENT_VERSION`) and a DPIA update, and it
must not persist selfies on the provider's side.
"""

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image

from app.core.config import get_settings
from app.models.photo import EMBEDDING_DIM

BUILTIN_ENGINES = {
    "insightface": "app.services.face_engines.insightface:InsightFaceEngine",
}


class FaceEngineError(RuntimeError):
    """The configured engine can't be used (unknown, or incompatible with the schema)."""


@dataclass(frozen=True)
class DetectedFace:
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in the input image's pixels
    det_score: float
    embedding: np.ndarray  # shape (embedding_dim,), L2-normalised float32


@dataclass(frozen=True)
class SelfieFace:
    bbox: tuple[float, float, float, float]
    det_score: float
    pitch: float
    yaw: float  # > 0: the person turned to THEIR left
    roll: float
    embedding: np.ndarray


class FaceEngine(ABC):
    #: Identifies the embedding space; stored on every face row.
    model_id: str
    #: Must equal the database column's dimension (EMBEDDING_DIM).
    embedding_dim: int

    @abstractmethod
    def detect(self, img: Image.Image) -> list[DetectedFace]:
        """All faces in an RGB event photo (no score filtering needed; callers filter)."""

    @abstractmethod
    def analyze_selfie(self, img: Image.Image) -> list[SelfieFace]:
        """All faces in an RGB selfie, with head pose, unfiltered (the quality gate judges)."""


def _load(spec: str) -> FaceEngine:
    path = BUILTIN_ENGINES.get(spec, spec)
    module_name, _, class_name = path.partition(":")
    if not class_name:
        raise FaceEngineError(f"Unknown FACE_ENGINE {spec!r}: use one of {sorted(BUILTIN_ENGINES)} or 'module:Class'")
    try:
        cls = getattr(importlib.import_module(module_name), class_name)
    except (ImportError, AttributeError) as e:
        raise FaceEngineError(f"Unknown FACE_ENGINE {spec!r}: {e}") from e
    if not (isinstance(cls, type) and issubclass(cls, FaceEngine)):
        raise FaceEngineError(f"Unknown FACE_ENGINE {spec!r}: {path} is not a FaceEngine")
    engine = cls()
    if engine.embedding_dim != EMBEDDING_DIM:
        raise FaceEngineError(
            f"FACE_ENGINE {spec!r} produces {engine.embedding_dim}-d embeddings, but the database stores "
            f"{EMBEDDING_DIM}-d vectors. Add a migration for the new dimension (and reindex) first."
        )
    return engine


@lru_cache
def get_engine() -> FaceEngine:
    return _load(get_settings().face_engine)


def reset_engine() -> None:
    """Forget the loaded engine so the next use re-reads FACE_ENGINE (tests, reloads)."""
    get_engine.cache_clear()
