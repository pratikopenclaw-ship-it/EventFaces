"""InsightFace buffalo_l on CPU (the default engine; the model is baked into the image)."""

import threading
from functools import cached_property
from typing import Any

import numpy as np
from PIL import Image

from app.core.config import get_settings
from app.services.face_engine import DetectedFace, FaceEngine, SelfieFace


class InsightFaceEngine(FaceEngine):
    model_id = "insightface/buffalo_l"
    embedding_dim = 512

    def __init__(self) -> None:
        # One model call at a time per process: onnxruntime sessions are shared, and the
        # CPU is the bottleneck anyway (see core/face_slots.py).
        self._lock = threading.Lock()

    def _build(self, modules: list[str]) -> Any:
        from insightface.app import FaceAnalysis

        s = get_settings()
        app = FaceAnalysis(name="buffalo_l", root=s.face_model_root, allowed_modules=modules, providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1, det_size=(s.face_det_size, s.face_det_size))
        return app

    @cached_property
    def _photo_model(self) -> Any:
        return self._build(["detection", "recognition"])

    @cached_property
    def _selfie_model(self) -> Any:
        # Selfies also need head pose (3D landmarks); photos don't, so they use the lighter model.
        return self._build(["detection", "landmark_3d_68", "recognition"])

    @staticmethod
    def _bgr(img: Image.Image) -> np.ndarray:
        return np.ascontiguousarray(np.asarray(img.convert("RGB"))[:, :, ::-1])

    def detect(self, img: Image.Image) -> list[DetectedFace]:
        with self._lock:
            raw = self._photo_model.get(self._bgr(img))
        return [
            DetectedFace(
                bbox=tuple(float(v) for v in f.bbox),  # type: ignore[arg-type]
                det_score=float(f.det_score),
                embedding=np.asarray(f.normed_embedding, dtype=np.float32),
            )
            for f in raw
            if f.normed_embedding is not None
        ]

    def analyze_selfie(self, img: Image.Image) -> list[SelfieFace]:
        with self._lock:
            raw = self._selfie_model.get(self._bgr(img))
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
