"""Face-matching accuracy on a labeled synthetic fixture set (Phase C).

Identities: the 6 people in InsightFace's bundled group photo + the bundled portrait (7).
(The bundled masked-face samples yield no detectable face, so they can't serve as probes.)
Impostor: one of the 7 is held out of every event photo; their selfies must match nothing.
Gallery: 48 seeded composite "event photos", each with 1-4 identities pasted at random
face sizes (40-220 px), brightness, rotation, blur and JPEG quality, over noisy backgrounds.
Probes: per identity, an easy selfie (mirrored, brightened, upscaled) and a hard one
(low-res, dark). Everything runs the real pipeline: detect_faces → faces table →
search_faces (pgvector HNSW, event-scoped) at the configured thresholds.

LIMITATION: probes and gallery come from the same source photo per identity (different
crops/augmentations), which is optimistic compared with real selfies vs. event photos.
The floors below are regression guards; calibrate the threshold on consented real data
before launch (README "Tuning the threshold").
"""

import io
import itertools
import json
import os
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass

import pytest
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Face, IndexStatus, Photo, PhotoSource, PhotoStatus
from app.services.faces import detect_faces
from app.services.search import search_faces
from tests.helpers import SAMPLES, _group_image, group_faces

SEED = 20260929
GALLERY_SIZE = 48
HELD_OUT = "g5"  # impostor: a real, detectable person who is not at the event


def _loose_crop(img: Image.Image, box: tuple[float, float, float, float], margin: float = 0.6) -> Image.Image:
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    return img.crop((max(0, int(x1 - margin * w)), max(0, int(y1 - margin * h)), min(img.width, int(x2 + margin * w)), min(img.height, int(y2 + margin * h))))


def _with_context(img: Image.Image) -> Image.Image:
    """Tight, pre-aligned face crops need surrounding context for the detector."""
    big = img.resize((img.width * 3, img.height * 3), Image.Resampling.BICUBIC)
    canvas = Image.new("RGB", (big.width * 2, big.height * 2), (128, 128, 128))
    canvas.paste(big, (big.width // 2, big.height // 2))
    return canvas


def _largest_face_crop(path: str) -> Image.Image:
    img = Image.open(path).convert("RGB")
    if not detect_faces(img):
        img = _with_context(img)
    faces = detect_faces(img)
    assert faces, path
    box = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])).bbox
    return _loose_crop(img, box)


def _identities() -> dict[str, Image.Image]:
    group = _group_image()
    ids = {f"g{i}": _loose_crop(group, box) for i, box in enumerate(group_faces())}
    ids["hanks"] = _largest_face_crop(os.path.join(SAMPLES, "Tom_Hanks_54745.png"))
    return ids


@dataclass
class Placed:
    identity: str
    face_px: int


def _composite(rng: random.Random, ids: dict[str, Image.Image]) -> tuple[bytes, list[Placed]]:
    canvas = Image.effect_noise((1600, 1066), rng.uniform(20, 60)).convert("RGB")
    tint = Image.new("RGB", canvas.size, tuple(rng.randint(40, 220) for _ in range(3)))
    canvas = Image.blend(canvas, tint, 0.6)
    people = rng.sample(sorted(ids), rng.randint(1, 4))
    slots = rng.sample(range(8), len(people))  # 4x2 grid of 400x533 slots, no overlap
    placed = []
    for person, slot in zip(people, slots, strict=True):
        face_px = rng.choice([40, 60, 80, 110, 150, 220])
        crop = ids[person]
        scale = face_px / (crop.height / 2.2)  # the loose crop is ~2.2 face-heights tall
        tile = crop.resize((max(8, int(crop.width * scale)), max(8, int(crop.height * scale))), Image.Resampling.BICUBIC)
        tile = ImageEnhance.Brightness(tile).enhance(rng.uniform(0.6, 1.4))
        tile = tile.rotate(rng.uniform(-12, 12), resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(128, 128, 128))
        if rng.random() < 0.4:
            tile = tile.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.2)))
        tile.thumbnail((390, 520))
        sx, sy = (slot % 4) * 400, (slot // 4) * 533
        canvas.paste(tile, (sx + (400 - tile.width) // 2, sy + (533 - tile.height) // 2))
        placed.append(Placed(person, face_px))
    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=rng.randint(55, 90))
    return out.getvalue(), placed


def _probe_embeddings(crop: Image.Image) -> dict[str, list[float]]:
    easy = ImageOps.mirror(crop)
    easy = ImageEnhance.Brightness(easy).enhance(1.15).resize((int(crop.width * 640 / crop.height), 640), Image.Resampling.BICUBIC)
    small = crop.resize((max(8, crop.width * 110 // crop.height), 110), Image.Resampling.BILINEAR)
    hard = ImageEnhance.Brightness(small.resize(easy.size, Image.Resampling.BICUBIC)).enhance(0.7)
    result = {}
    for name, img in (("easy", easy), ("hard", hard)):
        faces = detect_faces(img)
        if faces:
            result[name] = max(faces, key=lambda f: f.det_score).embedding.tolist()
    return result


@pytest.fixture(scope="module")
def fixture_set() -> dict:
    rng = random.Random(SEED)
    everyone = _identities()
    held_out = {k: everyone.pop(k) for k in (HELD_OUT,)}  # never placed in any event photo
    gallery = [_composite(rng, everyone) for _ in range(GALLERY_SIZE)]
    return {"ids": everyone, "gallery": gallery, "impostors": held_out}


def test_face_matching_accuracy(fixture_set: dict, make_event, db: Session) -> None:  # type: ignore[no-untyped-def]
    s = get_settings()
    event = make_event("Accuracy")
    truth: dict[uuid.UUID, set[str]] = {}
    sizes: dict[tuple[uuid.UUID, str], int] = {}
    for data, placed in fixture_set["gallery"]:
        photo = Photo(id=uuid.uuid4(), event_id=event.id, source=PhotoSource.drive, drive_file_id=uuid.uuid4().hex, status=PhotoStatus.published, index_status=IndexStatus.indexed)
        db.add(photo)
        db.flush()
        faces = detect_faces(Image.open(io.BytesIO(data)).convert("RGB"))
        for f in faces:
            db.add(Face(photo_id=photo.id, event_id=event.id, bbox=list(f.bbox), det_score=f.det_score, embedding=f.embedding.tolist()))
        photo.face_count = len(faces)
        truth[photo.id] = {p.identity for p in placed}
        for p in placed:
            sizes[(photo.id, p.identity)] = p.face_px
    db.commit()

    report: dict = {"thresholds": {}, "by_face_px": {}, "impostors": {}}
    for tier, threshold in (("possible", s.face_match_threshold), ("best", s.match_best_threshold)):
        tp = fp = fn = 0
        size_hits: dict[int, list[int]] = defaultdict(lambda: [0, 0])
        for identity, crop in fixture_set["ids"].items():
            for variant, emb in _probe_embeddings(crop).items():
                got = {m.photo_id for m in search_faces(db, event_id=event.id, embedding=emb, threshold=threshold, limit=500)}
                want = {pid for pid, people in truth.items() if identity in people}
                tp += len(got & want)
                fp += len(got - want)
                fn += len(want - got)
                if tier == "possible" and variant == "easy":
                    for pid in want:
                        bucket = size_hits[sizes[(pid, identity)]]
                        bucket[0] += pid in got
                        bucket[1] += 1
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        report["thresholds"][tier] = {"threshold": threshold, "tp": tp, "fp": fp, "fn": fn, "precision": round(precision, 3), "recall": round(recall, 3)}
        if tier == "possible":
            report["by_face_px"] = {px: round(h / n, 3) for px, (h, n) in sorted(size_hits.items())}

    for name, crop in fixture_set["impostors"].items():
        for variant, emb in _probe_embeddings(crop).items():
            report["impostors"][f"{name}/{variant}"] = len(
                search_faces(db, event_id=event.id, embedding=emb, threshold=s.face_match_threshold, limit=500)
            )

    report["edge_cases"] = _edge_cases(fixture_set["ids"], db, event.id, truth, s.face_match_threshold)

    print("\nFACE_ACCURACY " + json.dumps(report))
    with open("/tmp/face_accuracy.json", "w") as f:  # noqa: S108 - picked up by the report script
        json.dump(report, f, indent=2)

    possible, best = report["thresholds"]["possible"], report["thresholds"]["best"]
    # Regression floors (see module docstring for why these aren't real-world numbers).
    assert possible["precision"] >= 0.95, report
    assert best["precision"] >= 0.98, report
    assert possible["recall"] >= 0.80, report
    assert all(rate >= 0.9 for px, rate in report["by_face_px"].items() if px >= 80), report
    assert len(report["impostors"]) >= 2, "impostor probes must exist, or this check is vacuous"
    # Degraded probes may miss (lower recall is acceptable) but must never match a photo
    # that doesn't contain the person (a false positive leaks someone else's photos).
    for case, result in report["edge_cases"].items():
        assert result["false_positives"] == 0, (case, result)
    assert sum(report["impostors"].values()) == 0, report


def _sunglasses(crop: Image.Image) -> Image.Image:
    from PIL import ImageDraw

    img = crop.copy()
    faces = detect_faces(img)
    if not faces:
        return img
    x1, y1, x2, y2 = faces[0].bbox
    w, h = x2 - x1, y2 - y1
    d = ImageDraw.Draw(img)
    for cx in (x1 + 0.3 * w, x1 + 0.7 * w):
        cy = y1 + 0.4 * h
        d.ellipse((cx - 0.17 * w, cy - 0.1 * h, cx + 0.17 * w, cy + 0.1 * h), fill=(10, 10, 10))
    d.line((x1 + 0.45 * w, y1 + 0.4 * h, x1 + 0.55 * w, y1 + 0.4 * h), fill=(10, 10, 10), width=max(2, int(w * 0.03)))
    return img


def _edge_cases(ids: dict[str, Image.Image], db: Session, event_id: uuid.UUID, truth: dict, threshold: float) -> dict:
    """Degraded or confusable probes: report how often they still find the person and,
    crucially, whether they ever match someone else's photo."""

    def upscale(img: Image.Image) -> Image.Image:
        return img.resize((int(img.width * 640 / img.height), 640), Image.Resampling.BICUBIC)

    transforms = {
        "sunglasses": lambda c: upscale(_sunglasses(c)),
        "low_light": lambda c: ImageEnhance.Brightness(upscale(c)).enhance(0.3),
        "profile_proxy": lambda c: upscale(c).resize((int(upscale(c).width * 0.55), 640)),  # strong horizontal squeeze
        "heavy_blur": lambda c: upscale(c).filter(ImageFilter.GaussianBlur(6)),
    }
    out: dict = {}
    for case, fn in transforms.items():
        found = fps = probes = undetected = 0
        for identity, crop in ids.items():
            faces = detect_faces(fn(crop))
            if not faces:
                undetected += 1
                continue
            probes += 1
            emb = max(faces, key=lambda f: f.det_score).embedding.tolist()
            got = {m.photo_id for m in search_faces(db, event_id=event_id, embedding=emb, threshold=threshold, limit=500)}
            want = {pid for pid, people in truth.items() if identity in people}
            found += len(got & want)
            fps += len(got - want)
        out[case] = {"probes": probes, "no_face_detected": undetected, "true_matches": found, "false_positives": fps}

    # "Twins-like": a 50/50 blend of two different people. It may resemble both, but must
    # only ever match photos that contain at least one of the two.
    names = sorted(ids)
    fps = matched = 0
    for a, b in itertools.pairwise(names):
        size = (256, 320)
        blend = Image.blend(ids[a].resize(size), ids[b].resize(size), 0.5)
        faces = detect_faces(upscale(blend))
        if not faces:
            continue
        emb = faces[0].embedding.tolist()
        got = {m.photo_id for m in search_faces(db, event_id=event_id, embedding=emb, threshold=threshold, limit=500)}
        allowed = {pid for pid, people in truth.items() if a in people or b in people}
        matched += len(got)
        fps += len(got - allowed)
    out["lookalike_blend"] = {"pairs": len(names) - 1, "matches": matched, "false_positives": fps}
    return out


def test_no_face_and_garbage_probes_match_nothing(fixture_set: dict, make_event, db: Session) -> None:  # type: ignore[no-untyped-def]
    """A face-free image yields no embedding, so the search layer is never reached."""
    for img in (Image.new("RGB", (640, 480), (90, 90, 90)), Image.effect_noise((640, 480), 80).convert("RGB")):
        assert detect_faces(img) == []
