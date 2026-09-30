"""A deterministic stand-in face engine, used to prove engines are swappable by
configuration alone (FACE_ENGINE=tests.fake_engine:FakeEngine)."""

import numpy as np
from PIL import Image

from app.services.face_engine import DetectedFace, FaceEngine, SelfieFace


def _embedding(img: Image.Image, dim: int) -> np.ndarray:
    # Same image content → same vector; different content → different vector.
    small = np.asarray(img.convert("RGB").resize((8, 8)), dtype=np.float32).ravel()
    vec = np.resize(small + 1.0, dim)
    return (vec / np.linalg.norm(vec)).astype(np.float32)


class FakeEngine(FaceEngine):
    model_id = "fake/v1"
    embedding_dim = 512

    def detect(self, img: Image.Image) -> list[DetectedFace]:
        w, h = img.size
        return [DetectedFace(bbox=(0.0, 0.0, float(w), float(h)), det_score=0.99, embedding=_embedding(img, self.embedding_dim))]

    def analyze_selfie(self, img: Image.Image) -> list[SelfieFace]:
        (face,) = self.detect(img)
        return [SelfieFace(bbox=face.bbox, det_score=face.det_score, pitch=0.0, yaw=0.0, roll=0.0, embedding=face.embedding)]


class WrongDimEngine(FakeEngine):
    model_id = "fake/wrong-dim"
    embedding_dim = 128
