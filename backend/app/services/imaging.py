"""Image validation and re-encoding.

Every stored image is decoded and re-encoded to JPEG here, which drops EXIF (incl. GPS)
and any other embedded metadata. Only JPEG, PNG and HEIC/HEIF are accepted, detected by
magic bytes rather than file names or claimed content types.
"""

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()
Image.MAX_IMAGE_PIXELS = 120_000_000  # decompression-bomb guard (~120 MP)

ORIGINAL_MAX_SIDE = 6000
PREVIEW_MAX_SIDE = 1600
THUMB_MAX_SIDE = 400

_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1"}


class UnsupportedImage(ValueError):
    pass


def sniff_type(data: bytes) -> str:
    """Return 'jpeg' | 'png' | 'heif' based on magic bytes, or raise UnsupportedImage."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        return "heif"
    raise UnsupportedImage("Only JPEG, PNG and HEIC images are supported")


@dataclass(frozen=True)
class ProcessedImage:
    original: bytes
    preview: bytes
    thumb: bytes
    width: int
    height: int
    sha256: str  # of the source bytes, for duplicate detection


def load_image(data: bytes) -> Image.Image:
    """Validate and decode to an upright RGB image (EXIF orientation applied)."""
    sniff_type(data)
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (Image.DecompressionBombError, OSError, ValueError) as e:
        raise UnsupportedImage(f"Could not decode image: {e}") from e
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        background = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    return img


def _encode(img: Image.Image, max_side: int, quality: int) -> bytes:
    copy = img.copy()
    copy.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    # No exif=/icc_profile= passed: Pillow writes a clean JPEG without metadata.
    copy.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def process(data: bytes) -> ProcessedImage:
    img = load_image(data)
    original = _encode(img, ORIGINAL_MAX_SIDE, 92)
    width, height = Image.open(io.BytesIO(original)).size
    return ProcessedImage(
        original=original,
        preview=_encode(img, PREVIEW_MAX_SIDE, 85),
        thumb=_encode(img, THUMB_MAX_SIDE, 80),
        width=width,
        height=height,
        sha256=hashlib.sha256(data).hexdigest(),
    )
