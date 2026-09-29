"""Test helpers: sample images and a fake Google Drive."""

import io
import os
from collections.abc import Iterator
from functools import lru_cache

import insightface
from PIL import Image

from app.services.drive import DriveAccessError, DriveFile

SAMPLES = os.path.join(os.path.dirname(insightface.__file__), "data", "images")


@lru_cache
def group_photo_bytes() -> bytes:
    """InsightFace's bundled sample: a group photo with 6 detectable faces."""
    with open(os.path.join(SAMPLES, "t1.jpg"), "rb") as f:
        return f.read()


def solid_jpeg(color: tuple[int, int, int] = (40, 120, 200), size: tuple[int, int] = (320, 240)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="JPEG")
    return out.getvalue()


class FakeDrive:
    """In-memory Drive folder: {folder_id: {file_id: (name, bytes)}}."""

    def __init__(self, folders: dict[str, dict[str, tuple[str, bytes]]], page_size: int = 100) -> None:
        self.folders = folders
        self.page_size = page_size
        self.downloads: list[str] = []

    def list_images(self, folder_id: str) -> Iterator[list[DriveFile]]:
        if folder_id not in self.folders:
            raise DriveAccessError(f"Drive folder {folder_id} was not found or isn't shared with importer@test")
        files = [
            DriveFile(id=fid, name=name, mime_type="image/jpeg", size=len(data))
            for fid, (name, data) in self.folders[folder_id].items()
        ]
        for i in range(0, len(files), self.page_size):
            yield files[i : i + self.page_size]

    def download(self, file_id: str, max_bytes: int) -> bytes:
        self.downloads.append(file_id)
        for files in self.folders.values():
            if file_id in files:
                return files[file_id][1]
        raise KeyError(file_id)


# --- Selfie search fixtures -----------------------------------------------------


def _group_image() -> Image.Image:
    return Image.open(io.BytesIO(group_photo_bytes())).convert("RGB")


def _jpeg(img: Image.Image, quality: int = 88) -> bytes:
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality)
    return out.getvalue()


@lru_cache
def group_faces() -> list[tuple[float, float, float, float]]:
    """Face boxes in the group photo, sorted left to right."""
    from app.services.faces import detect_faces

    return sorted((f.bbox for f in detect_faces(_group_image())), key=lambda b: b[0])


@lru_cache
def split_x() -> int:
    """A vertical cut with 3 whole faces on each side of the group photo."""
    boxes = group_faces()
    assert len(boxes) == 6
    left_edge_of_4th = boxes[3][0]
    right_edge_of_3rd = max(b[2] for b in boxes[:3])
    assert right_edge_of_3rd < left_edge_of_4th, "faces overlap horizontally; pick another split"
    return int((right_edge_of_3rd + left_edge_of_4th) / 2)


def half_photo(side: str) -> bytes:
    """Left or right half of the group photo: two photos with *different* people."""
    img = _group_image()
    x = split_x()
    return _jpeg(img.crop((0, 0, x, img.height)) if side == "left" else img.crop((x, 0, img.width, img.height)))


def selfie_of(face_index: int) -> bytes:
    """A 'selfie' of one person: a loose crop around their face, mirrored, brightened,
    upscaled and re-encoded, so it isn't pixel-identical to the event photo."""
    from PIL import ImageEnhance, ImageOps

    img = _group_image()
    x1, y1, x2, y2 = group_faces()[face_index]
    w, h = x2 - x1, y2 - y1
    crop = img.crop((max(0, int(x1 - 0.7 * w)), max(0, int(y1 - 0.7 * h)), int(x2 + 0.7 * w), int(y2 + 0.9 * h)))
    crop = ImageOps.mirror(crop)
    crop = ImageEnhance.Brightness(crop).enhance(1.15)
    scale = 640 / crop.height
    crop = crop.resize((int(crop.width * scale), 640), Image.Resampling.BICUBIC)
    return _jpeg(crop, quality=80)


def jpeg_with_gps(img_bytes: bytes) -> bytes:
    """Re-save a JPEG with EXIF GPS + camera make, to prove uploads get stripped."""
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"
    exif.get_ifd(0x8825).update({1: "N", 2: (52.0, 31.0, 12.0), 3: "E", 4: (13.0, 24.0, 18.0)})
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif, quality=90)
    return out.getvalue()


def png_bytes() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 64), (5, 5, 5)).save(out, format="PNG")
    return out.getvalue()


# --- Guided-capture selfies (640×480 frames, like a webcam) ------------------------------


@lru_cache
def _leveled_group(face_index: int) -> tuple[Image.Image, tuple[float, float, float, float]]:
    """The group photo rotated so that face `face_index` has ~no roll, plus its new bbox."""
    from app.services.faces import analyze_selfie

    base = _group_image()
    x1, y1, x2, y2 = group_faces()[face_index]
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

    def face_near_center(img: Image.Image):  # type: ignore[no-untyped-def]
        faces = analyze_selfie(img)
        return min(faces, key=lambda f: ((f.bbox[0] + f.bbox[2]) / 2 - cx) ** 2 + ((f.bbox[1] + f.bbox[3]) / 2 - cy) ** 2)

    roll = face_near_center(base).roll
    candidates = [base.rotate(a, center=(cx, cy), resample=Image.Resampling.BICUBIC) for a in (roll, -roll)]
    best = min(candidates, key=lambda im: abs(face_near_center(im).roll))
    return best, face_near_center(best).bbox


def selfie_frame(face_index: int, mirror: bool = False, face_ratio: float = 0.42, brightness: float = 1.1) -> bytes:
    """A 640×480 'webcam' selfie of one person from the group photo."""
    from PIL import ImageEnhance, ImageOps

    img, (x1, y1, x2, y2) = _leveled_group(face_index)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    crop_h = (y2 - y1) / face_ratio
    crop_w = crop_h * 4 / 3
    frame = img.crop((int(cx - crop_w / 2), int(cy - crop_h / 2), int(cx + crop_w / 2), int(cy + crop_h / 2)))
    frame = frame.resize((640, 480), Image.Resampling.BICUBIC)
    if mirror:
        frame = ImageOps.mirror(frame)
    frame = ImageEnhance.Brightness(frame).enhance(brightness)
    return _jpeg(frame, quality=88)


@lru_cache
def selfie_set(face_index: int) -> list[tuple[str, bytes]]:
    """(shot, jpeg) for front / left / right of one person, choosing original or mirrored
    frames so the head turns the right way (positive yaw = the person's left)."""
    from app.services.faces import analyze_selfie

    frames = {m: selfie_frame(face_index, mirror=m) for m in (False, True)}
    yaw = {m: analyze_selfie(Image.open(io.BytesIO(b)).convert("RGB"))[0].yaw for m, b in frames.items()}
    front = min(frames, key=lambda m: abs(yaw[m]))
    left = max(frames, key=lambda m: yaw[m])
    right = min(frames, key=lambda m: yaw[m])
    return [("front", frames[front]), ("left", frames[left]), ("right", frames[right])]


def selfie_body(shots: list[tuple[str, bytes]]) -> tuple[bytes, dict[str, str]]:
    """Encode several selfies into one raw request body (see app/api/selfie.py)."""
    return b"".join(data for _, data in shots), {
        "content-type": "application/x-selfie-set",
        "x-selfie-shots": ",".join(shot for shot, _ in shots),
        "x-selfie-lengths": ",".join(str(len(data)) for _, data in shots),
    }


def search_as(client, event, face_index: int = 0):  # type: ignore[no-untyped-def]
    """Full camera search: capture token → 3-shot selfie set → search response."""
    token = client.post(f"/api/events/{event.id}/capture-token")
    if token.status_code != 200:
        return token  # e.g. 403 for non-members or missing consent
    body, headers = selfie_body(selfie_set(face_index))
    headers["x-capture-token"] = token.json()["token"]
    return client.post(f"/api/events/{event.id}/search?source=camera", content=body, headers=headers)
