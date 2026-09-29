"""The server-side selfie quality gate returns the right, specific rejection reason."""

import io

import pytest
from PIL import Image, ImageEnhance, ImageFilter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import SearchAudit, SelfieQuality, UserRole
from app.services import drive
from app.services.search import FACE_CONSENT_VERSION
from app.services.selfie_quality import assess
from tests.helpers import FakeDrive, half_photo, selfie_body, selfie_frame, selfie_set, solid_jpeg

P0, P5 = 0, 5  # the two sample people with usable frontal/turned frames


def _img(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _reason(img: Image.Image, shot: str = "front") -> str | None:
    return assess(img, shot).reason  # type: ignore[arg-type]


def test_good_frames_pass_with_metrics() -> None:
    for shot, data in selfie_set(P5):
        result = assess(_img(data), shot)  # type: ignore[arg-type]
        assert result.passed, (shot, result.reason, result.metrics)
        m = result.metrics
        assert m.face_count == 1 and 0.3 <= m.face_height_ratio <= 0.6 and 0 < result.score <= 100


def test_resolution_too_low() -> None:
    assert _reason(_img(selfie_frame(P0)).resize((320, 240))) == "resolution_too_low"


def test_no_face() -> None:
    assert _reason(_img(solid_jpeg(size=(640, 480)))) == "no_face"


def test_multiple_faces() -> None:
    both = Image.new("RGB", (1280, 480))
    both.paste(_img(selfie_frame(P0)), (0, 0))
    both.paste(_img(selfie_frame(P5)), (640, 0))
    assert _reason(both) == "multiple_faces"


def test_low_confidence(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "selfie_min_det_score", 0.99)
    assert _reason(_img(selfie_frame(P0))) == "low_confidence"


def test_face_too_small() -> None:
    # Standing far back: shrink the frame onto a plain wall (zooming out on the group
    # photo would bring neighbours into view, which is correctly "multiple_faces").
    wall = Image.new("RGB", (640, 480), (190, 185, 175))
    wall.paste(_img(selfie_frame(P0)).resize((384, 288)), (128, 96))
    assert _reason(wall) == "face_too_small"


def test_face_too_large() -> None:
    assert _reason(_img(selfie_frame(P0, face_ratio=0.8))) == "face_too_large"


def test_roll_out_of_range() -> None:
    tilted = _img(selfie_frame(P0)).rotate(30, resample=Image.Resampling.BICUBIC)
    assert _reason(tilted) == "roll_out_of_range"


def test_pitch_out_of_range() -> None:
    assert _reason(_img(selfie_frame(3))) == "pitch_out_of_range"  # person 3 looks down ~21°


def test_yaw_out_of_range(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "selfie_min_det_score", 0.5)  # profile faces detect weakly
    assert _reason(_img(selfie_frame(1))) == "yaw_out_of_range"  # person 1 is turned ~36°


def test_front_shot_must_face_camera(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "selfie_front_max_yaw", 12.0)  # production default
    assert _reason(_img(selfie_frame(P5))) == "not_facing_camera"  # turned ~13°


def test_side_shots_must_turn_the_requested_way() -> None:
    turned_right = _img(selfie_frame(P5))  # yaw ≈ -13: the person's right
    turned_left = _img(selfie_frame(P5, mirror=True))  # yaw ≈ +15: the person's left
    assert _reason(turned_right, "left") == "wrong_turn_left"
    assert _reason(turned_left, "right") == "wrong_turn_right"
    assert _reason(turned_left, "left") is None and _reason(turned_right, "right") is None


def test_too_blurry() -> None:
    assert _reason(_img(selfie_frame(P0)).filter(ImageFilter.GaussianBlur(4))) == "too_blurry"


def test_too_dark_and_too_bright(monkeypatch) -> None:
    img = _img(selfie_frame(P0, brightness=1.0))
    dark = ImageEnhance.Brightness(img).enhance(0.3)
    assert _reason(dark) == "too_dark"
    monkeypatch.setattr(get_settings(), "selfie_max_brightness", 120.0)
    assert _reason(img) == "too_bright"


# --- Through the API -----------------------------------------------------------------------


@pytest.fixture
def camera_client(make_user, login_as, make_event, add_member):
    event = make_event("Q", drive_folder_id="1QualityFolderXXXXXX")
    admin = login_as(make_user("admin@example.com", UserRole.super_admin))
    drive.set_drive_client(FakeDrive({event.drive_folder_id: {"l": ("left.jpg", half_photo("left"))}}))
    admin.post(f"/api/events/{event.id}/sync")
    user = make_user("att@example.com")
    add_member(event, user)
    c = login_as(user)
    c.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION})
    return event, c


def _camera_search(c, event, shots):  # type: ignore[no-untyped-def]
    body, headers = selfie_body(shots)
    headers["x-capture-token"] = c.post(f"/api/events/{event.id}/capture-token").json()["token"]
    return c.post(f"/api/events/{event.id}/search?source=camera", content=body, headers=headers)


def test_api_returns_code_message_and_shot(camera_client, db: Session) -> None:
    event, c = camera_client
    front, left, right = selfie_set(P0)
    blurry = io.BytesIO()
    _img(left[1]).filter(ImageFilter.GaussianBlur(4)).save(blurry, format="JPEG")
    r = _camera_search(c, event, [front, ("left", blurry.getvalue()), right])
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "too_blurry" and body["shot"] == "left" and "blurry" in body["detail"]

    # Rejected attempts leave quality metrics (no image, no user) but no search/audit row.
    rows = db.scalars(select(SelfieQuality)).all()
    assert {r.shot for r in rows} == {"front", "left", "right"}
    assert [r.reason for r in rows if not r.passed] == ["too_blurry"]
    assert all(r.search_id is None for r in rows)
    assert db.scalar(select(SearchAudit.id)) is None


def test_api_rejects_mixed_people(camera_client) -> None:
    event, c = camera_client
    p0 = dict(selfie_set(P0))
    p5 = dict(selfie_set(P5))
    r = _camera_search(c, event, [("front", p0["front"]), ("left", p5["left"]), ("right", p0["right"])])
    assert r.status_code == 422 and r.json()["code"] == "different_people"


def test_api_requires_front_left_right_in_order(camera_client) -> None:
    event, c = camera_client
    shots = selfie_set(P0)
    assert _camera_search(c, event, [shots[1], shots[0], shots[2]]).status_code == 400
    assert _camera_search(c, event, shots[:2]).status_code == 400
