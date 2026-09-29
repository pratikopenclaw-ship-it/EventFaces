import io

import pytest
from PIL import Image
from pillow_heif import from_pillow

from app.services import imaging
from tests.helpers import solid_jpeg

GPS_IFD = 0x8825
ORIENTATION = 0x0112


def _jpeg_with_exif(size: tuple[int, int] = (300, 200), orientation: int = 1) -> bytes:
    img = Image.new("RGB", size, (200, 30, 30))
    exif = Image.Exif()
    exif[ORIENTATION] = orientation
    exif[0x010F] = "SecretCam"  # Make
    exif.get_ifd(GPS_IFD).update({1: "N", 2: (52.0, 31.0, 12.0), 3: "E", 4: (13.0, 24.0, 18.0)})
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif)
    return out.getvalue()


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (b"\xff\xd8\xff\xe0rest", "jpeg"),
        (b"\x89PNG\r\n\x1a\nrest", "png"),
        (b"\x00\x00\x00\x18ftypheic\x00\x00", "heif"),
        (b"\x00\x00\x00\x18ftypmif1\x00\x00", "heif"),
    ],
)
def test_sniff_accepts(data: bytes, kind: str) -> None:
    assert imaging.sniff_type(data) == kind


@pytest.mark.parametrize(
    "data",
    [b"GIF89a....", b"<svg xmlns=...>", b"%PDF-1.7", b"\x00\x00\x00\x18ftypmp42\x00\x00", b""],
)
def test_sniff_rejects(data: bytes) -> None:
    with pytest.raises(imaging.UnsupportedImage):
        imaging.sniff_type(data)


def test_truncated_jpeg_rejected() -> None:
    with pytest.raises(imaging.UnsupportedImage):
        imaging.process(solid_jpeg()[:200])


def test_reencode_strips_exif_and_gps() -> None:
    source = _jpeg_with_exif()
    assert Image.open(io.BytesIO(source)).getexif().get_ifd(GPS_IFD)  # sanity: GPS present

    result = imaging.process(source)
    for variant in (result.original, result.preview, result.thumb):
        img = Image.open(io.BytesIO(variant))
        assert img.format == "JPEG"
        assert len(img.getexif()) == 0
        assert b"SecretCam" not in variant


def test_orientation_applied_before_stripping() -> None:
    # Orientation 6 = rotate 90° CW for display: a 300x200 sensor image displays as 200x300.
    result = imaging.process(_jpeg_with_exif((300, 200), orientation=6))
    assert (result.width, result.height) == (200, 300)


def test_sizes() -> None:
    result = imaging.process(solid_jpeg(size=(4000, 3000)))
    assert max(Image.open(io.BytesIO(result.preview)).size) == imaging.PREVIEW_MAX_SIDE
    assert max(Image.open(io.BytesIO(result.thumb)).size) == imaging.THUMB_MAX_SIDE
    assert (result.width, result.height) == (4000, 3000)


def test_png_with_alpha_becomes_rgb_jpeg() -> None:
    out = io.BytesIO()
    Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(out, format="PNG")
    result = imaging.process(out.getvalue())
    assert Image.open(io.BytesIO(result.original)).mode == "RGB"


def test_heic_supported() -> None:
    out = io.BytesIO()
    from_pillow(Image.new("RGB", (64, 48), (10, 200, 10))).save(out, quality=80)
    data = out.getvalue()
    assert imaging.sniff_type(data) == "heif"
    result = imaging.process(data)
    assert (result.width, result.height) == (64, 48)


def test_decompression_bomb_rejected(monkeypatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(imaging.UnsupportedImage):
        imaging.process(solid_jpeg(size=(200, 200)))
