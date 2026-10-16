"""Composites an organizer's event logo onto served photo bytes.

Applied on the fly when photos are streamed to clients (never baked into the stored
`original`, which `photo_pipeline.index_photo` reads for face detection and must stay
pristine). A no-op when the event has no logo.
"""

import io

from PIL import Image

from app.models.event import Event

MARGIN_FRACTION = 0.02
LOGO_WIDTH_FRACTION = 0.1


def apply(photo_bytes: bytes, logo_png: bytes, quality: int) -> bytes:
    """Paste the logo (a transparent PNG, already ≤512px from `imaging.process_logo`) in
    the bottom-right corner, scaled to roughly a tenth of the photo's shorter side."""
    photo = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    logo = Image.open(io.BytesIO(logo_png)).convert("RGBA")

    target_w = max(1, round(min(photo.width, photo.height) * LOGO_WIDTH_FRACTION))
    scale = target_w / logo.width
    logo = logo.resize((target_w, max(1, round(logo.height * scale))), Image.Resampling.LANCZOS)

    margin = round(min(photo.width, photo.height) * MARGIN_FRACTION)
    x = photo.width - logo.width - margin
    y = photo.height - logo.height - margin
    photo.paste(logo, (x, y), mask=logo)

    out = io.BytesIO()
    photo.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def maybe_apply(photo_bytes: bytes, event: Event, logo_bytes: bytes | None, quality: int) -> bytes:
    """`apply` if the event has a logo, else the bytes unchanged."""
    if event.logo_key is None or logo_bytes is None:
        return photo_bytes
    return apply(photo_bytes, logo_bytes, quality)
