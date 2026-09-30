"""The face model sits behind app.services.face_engine.FaceEngine: swapping it is a
configuration change (FACE_ENGINE), not an application change. Embeddings from
different models are never compared, and `app.cli reindex-faces` moves photos over."""

import io
import uuid
from collections.abc import Iterator

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import storage
from app.core.config import get_settings
from app.models import Face, IndexStatus, Photo, PhotoSource, PhotoStatus
from app.services import face_engine, faces, photo_pipeline
from app.services.search import search_faces
from tests.helpers import group_photo_bytes, solid_jpeg


@pytest.fixture
def use_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    def _use(path: str) -> face_engine.FaceEngine:
        monkeypatch.setattr(get_settings(), "face_engine", path)
        face_engine.reset_engine()
        return face_engine.get_engine()

    yield _use
    face_engine.reset_engine()  # back to the configured default for other tests


def _photo(db: Session, event_id: uuid.UUID, data: bytes) -> Photo:
    p = Photo(id=uuid.uuid4(), event_id=event_id, source=PhotoSource.drive, drive_file_id=uuid.uuid4().hex, status=PhotoStatus.published, index_status=IndexStatus.queued)
    p.original_key = storage.photo_key(event_id, p.id, "original")
    storage.put_jpeg(p.original_key, data)
    db.add(p)
    db.commit()
    return p


def test_default_engine_is_insightface() -> None:
    engine = face_engine.get_engine()
    assert engine.model_id == "insightface/buffalo_l"
    assert engine.embedding_dim == 512


def test_engine_contract_on_the_real_model() -> None:
    """What every engine must return: boxes inside the image, unit-length embeddings of
    the declared size, scores in [0, 1], and head pose for selfies."""
    engine = face_engine.get_engine()
    img = Image.open(io.BytesIO(group_photo_bytes())).convert("RGB")
    found = engine.detect(img)
    assert len(found) >= 5
    for f in found:
        x1, y1, x2, y2 = f.bbox
        assert 0 <= x1 < x2 <= img.width + 1 and 0 <= y1 < y2 <= img.height + 1
        assert 0.0 <= f.det_score <= 1.0
        assert f.embedding.shape == (engine.embedding_dim,)
        assert abs(float(np.linalg.norm(f.embedding)) - 1.0) < 1e-3
    s = engine.analyze_selfie(img)
    assert s and all(isinstance(v, float) for v in (s[0].yaw, s[0].pitch, s[0].roll))
    assert engine.detect(Image.new("RGB", (400, 300), (90, 90, 90))) == []


def test_swapping_engine_needs_no_application_changes(use_engine, make_event, db: Session) -> None:  # type: ignore[no-untyped-def]
    engine = use_engine("tests.fake_engine:FakeEngine")
    assert faces.current_model_id() == "fake/v1"
    event = make_event("Swap")
    data = solid_jpeg((10, 200, 30), (320, 240))
    photo = _photo(db, event.id, data)

    assert photo_pipeline.index_photo(db, photo.id) == 1  # the normal pipeline, unchanged
    stored = db.scalars(select(Face).where(Face.photo_id == photo.id)).all()
    assert [f.model for f in stored] == ["fake/v1"]

    probe = faces.detect_faces(Image.open(io.BytesIO(data)).convert("RGB"))[0].embedding
    assert [m.photo_id for m in search_faces(db, event_id=event.id, embedding=probe, threshold=0.9, limit=10)] == [photo.id]
    assert engine.model_id == "fake/v1"


def test_search_never_compares_embeddings_from_another_model(use_engine, make_event, db: Session) -> None:  # type: ignore[no-untyped-def]
    use_engine("tests.fake_engine:FakeEngine")
    event = make_event("Mixed")
    data = solid_jpeg((10, 200, 30), (320, 240))
    photo = _photo(db, event.id, data)
    probe = faces.detect_faces(Image.open(io.BytesIO(data)).convert("RGB"))[0].embedding
    # An identical vector, but produced by a different model: must not match.
    db.add(Face(photo_id=photo.id, event_id=event.id, bbox=[0, 0, 1, 1], det_score=0.9, embedding=probe.tolist(), model="insightface/buffalo_l"))
    db.commit()
    assert search_faces(db, event_id=event.id, embedding=probe, threshold=0.5, limit=10) == []


@pytest.mark.parametrize(
    ("path", "message"),
    [("tests.fake_engine:WrongDimEngine", "512"), ("no-such-engine", "Unknown FACE_ENGINE"), ("tests.fake_engine:Missing", "Unknown FACE_ENGINE")],
)
def test_misconfigured_engines_fail_fast(use_engine, path: str, message: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(face_engine.FaceEngineError, match=message):
        use_engine(path)


def test_reindex_moves_photos_to_the_current_engine(use_engine, make_event, db: Session) -> None:  # type: ignore[no-untyped-def]
    from app.cli import reindex_faces

    event = make_event("Reindex")
    photo = _photo(db, event.id, solid_jpeg((200, 10, 30), (320, 240)))
    db.add(Face(photo_id=photo.id, event_id=event.id, bbox=[0, 0, 1, 1], det_score=0.9, embedding=[0.0] * 511 + [1.0], model="insightface/buffalo_l"))
    photo.index_status = IndexStatus.indexed
    photo.face_count = 1
    db.commit()

    use_engine("tests.fake_engine:FakeEngine")
    assert reindex_faces(all_photos=False) == 1  # only photos indexed by another model
    db.expire_all()
    assert {f.model for f in db.scalars(select(Face).where(Face.photo_id == photo.id))} == {"fake/v1"}
    assert reindex_faces(all_photos=False) == 0  # idempotent
