"""Server-side selfie quality gate. Every threshold comes from settings (env).

Each shot gets metrics, a pass/fail with a specific reason code, and a 0–100 quality
score (for the admin dashboard). Nothing here stores images or embeddings.
"""

from dataclasses import asdict, dataclass, field
from typing import Literal

import cv2
import numpy as np
from PIL import Image

from app.core.config import get_settings
from app.services.faces import SelfieFace, analyze_selfie

Shot = Literal["front", "left", "right", "any"]
SHOTS_CAMERA: tuple[Shot, ...] = ("front", "left", "right")

# The person turning to THEIR left moves the nose toward the right of the raw camera
# frame, which InsightFace reports as positive yaw. The browser uses the same convention.
LEFT_YAW_SIGN = 1

MESSAGES: dict[str, str] = {
    "resolution_too_low": "The photo is too small. Use a camera with at least 640×480.",
    "no_face": "We couldn't find a face. Center your face in the oval.",
    "multiple_faces": "More than one face is visible. Make sure you're alone in the picture.",
    "low_confidence": "Your face isn't clearly visible. Remove sunglasses or a mask and face the light.",
    "face_too_small": "Move closer: your face should fill the oval.",
    "face_too_large": "Move back a little: your whole face should fit in the oval.",
    "yaw_out_of_range": "Turn your head less: look toward the camera.",
    "pitch_out_of_range": "Keep your head level: don't look up or down.",
    "roll_out_of_range": "Keep your head straight: don't tilt it sideways.",
    "not_facing_camera": "For the first photo, look straight at the camera.",
    "wrong_turn_left": "For this photo, turn your head slightly to your left.",
    "wrong_turn_right": "For this photo, turn your head slightly to your right.",
    "too_blurry": "The photo is blurry. Hold still and make sure the camera is in focus.",
    "too_dark": "It's too dark. Move to a brighter place or face a window.",
    "too_bright": "It's too bright. Avoid direct sunlight or strong light behind the camera.",
    "different_people": "The three photos don't seem to show the same person. Please try again.",
    "unreadable": "We couldn't read this image.",
}


@dataclass
class ShotMetrics:
    width: int = 0
    height: int = 0
    face_count: int = 0
    det_score: float | None = None
    face_height_ratio: float | None = None
    yaw: float | None = None
    pitch: float | None = None
    roll: float | None = None
    blur: float | None = None
    brightness: float | None = None


@dataclass
class ShotResult:
    shot: Shot
    passed: bool
    reason: str | None
    metrics: ShotMetrics = field(default_factory=ShotMetrics)
    score: int = 0
    embedding: np.ndarray | None = None  # held in memory only for the current search

    @property
    def message(self) -> str | None:
        return MESSAGES.get(self.reason) if self.reason else None

    def metrics_dict(self) -> dict:
        return asdict(self.metrics)


def _face_crop_gray(img: Image.Image, face: SelfieFace) -> np.ndarray:
    x1, y1, x2, y2 = face.bbox
    w, h = img.size
    box = (max(0, int(x1)), max(0, int(y1)), min(w, int(x2)), min(h, int(y2)))
    gray = np.asarray(img.crop(box).convert("L"))
    # Normalize scale so sharpness is comparable between close-ups and distant faces.
    target_h = 160
    scale = target_h / max(gray.shape[0], 1)
    return cv2.resize(gray, (max(1, int(gray.shape[1] * scale)), target_h), interpolation=cv2.INTER_AREA)


def quality_score(m: ShotMetrics) -> int:
    """0–100 composite for dashboards (not used to accept/reject)."""
    s = get_settings()
    parts: list[float] = []
    if m.blur is not None:
        parts.append(min(m.blur / (2 * s.selfie_min_blur), 1.0))
    if m.brightness is not None:
        parts.append(max(0.0, 1 - abs(m.brightness - 135) / 135))
    if None not in (m.yaw, m.pitch, m.roll):
        worst = max(abs(m.yaw) / s.selfie_max_yaw, abs(m.pitch) / s.selfie_max_pitch, abs(m.roll) / s.selfie_max_roll)  # type: ignore[arg-type]
        parts.append(max(0.0, 1 - worst))
    if m.face_height_ratio is not None:
        mid = (s.selfie_face_height_min + s.selfie_face_height_max) / 2
        half = (s.selfie_face_height_max - s.selfie_face_height_min) / 2
        parts.append(max(0.0, 1 - max(0.0, abs(m.face_height_ratio - mid) - half) / half))
    if m.det_score is not None:
        parts.append(min(max((m.det_score - 0.5) / 0.5, 0.0), 1.0))
    return round(100 * sum(parts) / len(parts)) if parts else 0


def assess(img: Image.Image, shot: Shot) -> ShotResult:
    s = get_settings()
    m = ShotMetrics(width=img.width, height=img.height)

    def fail(reason: str) -> ShotResult:
        return ShotResult(shot, False, reason, m, quality_score(m))

    if min(img.width, img.height) < min(s.selfie_min_width, s.selfie_min_height) or max(
        img.width, img.height
    ) < max(s.selfie_min_width, s.selfie_min_height):
        return fail("resolution_too_low")

    faces = analyze_selfie(img)
    m.face_count = len(faces)
    if not faces:
        return fail("no_face")
    # A distant background face shouldn't fail a selfie, but a second real person should.
    main = max(faces, key=lambda f: (f.bbox[3] - f.bbox[1]))
    others = [f for f in faces if f is not main and (f.bbox[3] - f.bbox[1]) > 0.4 * (main.bbox[3] - main.bbox[1]) and f.det_score >= 0.5]

    face_h = main.bbox[3] - main.bbox[1]
    crop = _face_crop_gray(img, main)
    m.det_score = round(main.det_score, 3)
    m.face_height_ratio = round(face_h / img.height, 3)
    m.yaw, m.pitch, m.roll = round(main.yaw, 1), round(main.pitch, 1), round(main.roll, 1)
    m.blur = round(float(cv2.Laplacian(crop, cv2.CV_64F).var()), 1)
    m.brightness = round(float(crop.mean()), 1)

    if others:
        return fail("multiple_faces")
    # Order matters for helpful messages: darkness lowers contrast (reads as blur), and
    # both darkness and blur lower detector confidence. Check root causes first.
    if m.brightness < s.selfie_min_brightness:
        return fail("too_dark")
    if m.brightness > s.selfie_max_brightness:
        return fail("too_bright")
    if m.blur < s.selfie_min_blur:
        return fail("too_blurry")
    if main.det_score < s.selfie_min_det_score:
        return fail("low_confidence")
    if m.face_height_ratio < s.selfie_face_height_min:
        return fail("face_too_small")
    if m.face_height_ratio > s.selfie_face_height_max:
        return fail("face_too_large")
    if abs(main.pitch) > s.selfie_max_pitch:
        return fail("pitch_out_of_range")
    if abs(main.roll) > s.selfie_max_roll:
        return fail("roll_out_of_range")
    if abs(main.yaw) > s.selfie_max_yaw:
        return fail("yaw_out_of_range")
    if shot == "front" and abs(main.yaw) > s.selfie_front_max_yaw:
        return fail("not_facing_camera")
    if shot == "left" and LEFT_YAW_SIGN * main.yaw < s.selfie_side_min_yaw:
        return fail("wrong_turn_left")
    if shot == "right" and -LEFT_YAW_SIGN * main.yaw < s.selfie_side_min_yaw:
        return fail("wrong_turn_right")

    return ShotResult(shot, True, None, m, quality_score(m), embedding=main.embedding)


def same_person(results: list[ShotResult]) -> bool:
    embs = [r.embedding for r in results if r.embedding is not None]
    threshold = get_settings().selfie_same_person_min
    return all(float(np.dot(a, b)) >= threshold for i, a in enumerate(embs) for b in embs[i + 1 :])
