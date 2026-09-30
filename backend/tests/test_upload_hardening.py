"""Upload/image hardening (Phase B §4): pixel limits enforced before decoding (SEC-025),
animated frames, polyglots, non-image formats, filename handling."""

import io
import time

import pytest
from PIL import Image

from app.core.config import get_settings
from app.services import downloads, imaging
from tests.helpers import solid_jpeg


def _png(mode: str, size: tuple[int, int], **save: object) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, 1).save(buf, format="PNG", **save)
    return buf.getvalue()


def test_pixel_bomb_below_pillows_hard_limit_is_rejected_before_decoding() -> None:
    """A 32 KB PNG declaring 144 MP used to decode (Pillow only warns between 1x and
    2x MAX_IMAGE_PIXELS) and peak at ~1.8 GB RSS in the API process."""
    bomb = _png("1", (12000, 12000), optimize=True)
    assert len(bomb) < 64 * 1024
    t = time.monotonic()
    with pytest.raises(imaging.UnsupportedImage, match="too large"):
        imaging.load_image(bomb)
    assert time.monotonic() - t < 0.5, "must be refused from the header, without decoding"


def test_selfies_have_a_lower_pixel_limit() -> None:
    limit = get_settings().selfie_max_pixels
    side = int(limit**0.5) + 10
    big = _png("1", (side, side))
    with pytest.raises(imaging.UnsupportedImage, match="too large"):
        imaging.load_image(big, max_pixels=limit)
    assert imaging.load_image(big).size == (side, side)  # fine as an event photo


def test_photo_limit_matches_setting() -> None:
    limit = get_settings().image_max_pixels
    ok_side = int(limit**0.5) - 1
    img = _png("1", (ok_side, 10))
    assert imaging.load_image(img).size == (ok_side, 10)
    with pytest.raises(imaging.UnsupportedImage):
        imaging.load_image(_png("1", (limit // 1000 + 1, 1000)))


def test_animated_png_keeps_first_frame_only_and_is_cheap() -> None:
    frames = [Image.new("RGB", (400, 300), (i, 0, 0)) for i in range(200)]
    buf = io.BytesIO()
    frames[0].save(buf, format="PNG", save_all=True, append_images=frames[1:], duration=10)
    t = time.monotonic()
    out = imaging.process(buf.getvalue())
    assert time.monotonic() - t < 2
    assert Image.open(io.BytesIO(out.original)).getpixel((5, 5))[0] < 8  # first frame
    assert getattr(Image.open(io.BytesIO(out.original)), "n_frames", 1) == 1


def test_polyglot_payload_does_not_survive_reencoding() -> None:
    polyglot = solid_jpeg() + b"<html><script>alert(1)</script></html>" + b"PK\x03\x04zipdata"
    out = imaging.process(polyglot)
    for blob in (out.original, out.preview, out.thumb):
        assert b"<script" not in blob and b"PK\x03\x04" not in blob


@pytest.mark.parametrize(
    "payload",
    [
        b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b"<!doctype html><script>alert(1)</script>",
        b"GIF89a\x01\x00\x01\x00\x00\x00\x00;",
        b"RIFF\x00\x00\x00\x00WEBPVP8 ",
        b"%PDF-1.7\n",
        b"\x00" * 64,
        b"",
        b"\xff\xd8\xff" + b"\x00" * 16,  # JPEG magic, garbage body
    ],
    ids=["svg", "html", "gif", "webp", "pdf", "nulls", "empty", "fake-jpeg"],
)
def test_non_images_and_garbage_are_rejected_cleanly(payload: bytes) -> None:
    with pytest.raises(imaging.UnsupportedImage):
        imaging.process(payload)


@pytest.mark.parametrize("mode", ["L", "P", "LA", "CMYK", "I;16", "1"])
def test_every_pixel_mode_becomes_rgb(mode: str) -> None:
    buf = io.BytesIO()
    img = Image.new(mode, (50, 40))
    img.save(buf, format="JPEG" if mode == "CMYK" else "PNG")
    out = imaging.process(buf.getvalue())
    assert Image.open(io.BytesIO(out.original)).mode == "RGB"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("../../etc/passwd", "etc_passwd.jpg"),
        ("..\\..\\windows\\win.ini", "windows_win.jpg"),
        ("evil\x00.php.jpg", "evil_.php.jpg"),
        ('a"; filename="x.exe', "a_filename_x.jpg"),
        ("line\r\nSet-Cookie: x=1.jpg", "line_Set-Cookie_x_1.jpg"),
        ("\u202egpj.exe", "gpj.jpg"),
        ("", "fallback.jpg"),
        ("....", "fallback.jpg"),
        ("x" * 500 + ".png", "x" * 80 + ".jpg"),
    ],
)
def test_download_filenames_are_inert(name: str, expected: str) -> None:
    safe = downloads.safe_filename(name, "fallback")
    assert safe == expected
    assert all(c.isalnum() or c in "._-" for c in safe)
    assert "/" not in safe and "\\" not in safe and ".." not in safe
