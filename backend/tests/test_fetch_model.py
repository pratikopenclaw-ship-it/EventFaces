"""The model fetcher (run at image build time) refuses files whose checksum doesn't match."""

import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fetch_model.py"


def _load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("fetch_model", SCRIPT)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(f"buffalo_l/{name}", data)
    return buf.getvalue()


class _Resp(io.BytesIO):
    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *a: object) -> None:
        pass


def test_tampered_model_aborts_build(tmp_path, monkeypatch) -> None:
    fm = _load()
    tampered = _zip({name: b"not the real model" for name in fm.PINNED})
    monkeypatch.setattr(fm.urllib.request, "urlopen", lambda *a, **k: _Resp(tampered))
    with pytest.raises(SystemExit, match="checksum mismatch"):
        fm.main(str(tmp_path))
    assert not any((tmp_path / "models" / "buffalo_l").glob("*.onnx"))


def test_only_pinned_https_source() -> None:
    fm = _load()
    assert fm.URL.startswith("https://github.com/deepinsight/insightface/releases/")
    assert set(fm.PINNED) == {"det_10g.onnx", "1k3d68.onnx", "w600k_r50.onnx"}
    assert all(len(h) == 64 for h in fm.PINNED.values())
