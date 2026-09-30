"""Download the InsightFace buffalo_l model at image build time and verify it.

Pinned source + per-file SHA-256: the build fails on any mismatch, so a tampered or
changed upstream archive can never end up in an image. Only the models the app loads
(detection, 3D landmarks for selfie pose, recognition) are kept.
"""

import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
PINNED = {
    "det_10g.onnx": "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91",
    "1k3d68.onnx": "df5c06b8a0c12e422b2ed8947b8869faa4105387f199c477af038aa01f9a45cc",
    "w600k_r50.onnx": "4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43",
}


def main(dest: str) -> None:
    out = Path(dest) / "models" / "buffalo_l"
    out.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(URL, timeout=300) as resp:  # noqa: S310 - fixed https URL
        archive = zipfile.ZipFile(io.BytesIO(resp.read()))
    names = {Path(n).name: n for n in archive.namelist()}
    for filename, expected in PINNED.items():
        data = archive.read(names[filename])
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            sys.exit(f"checksum mismatch for {filename}: {actual} != {expected}")
        (out / filename).write_bytes(data)
        print(f"verified {filename}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/models")
