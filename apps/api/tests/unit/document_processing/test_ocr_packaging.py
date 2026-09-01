import importlib
import importlib.metadata
import tomllib
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
OCR_RUNTIME_DISTRIBUTIONS = {
    "opencv-python": "cv2",
    "onnxruntime": "onnxruntime",
    "rapidocr": "rapidocr",
}


def _missing_ocr_runtime_distributions() -> tuple[str, ...]:
    missing: list[str] = []
    for distribution_name in OCR_RUNTIME_DISTRIBUTIONS:
        try:
            importlib.metadata.distribution(distribution_name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(distribution_name)
    return tuple(missing)


def _import_installed_ocr_runtime_modules() -> None:
    missing = _missing_ocr_runtime_distributions()
    if missing:
        pytest.skip(f"OCR runtime distributions are not installed: {', '.join(missing)}")
    for module_name in OCR_RUNTIME_DISTRIBUTIONS.values():
        importlib.import_module(module_name)


def test_ocr_extra_declares_required_cpu_runtime_dependencies() -> None:
    config = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert set(config["project"]["optional-dependencies"]["ocr"]) == {
        "numpy>=2,<3",
        "onnxruntime>=1.20,<2",
        "opencv-python>=4.10,<5",
        "rapidocr>=3,<4",
    }


def test_runtime_image_installs_ocr_extra_and_cv2_runtime_library() -> None:
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert '"text-verification[dev,ocr]"' in dockerfile
    assert '".[dev,ocr]"' in dockerfile
    assert "libgl1" in dockerfile
    assert "opencv-python-headless" not in dockerfile


def test_missing_ocr_runtime_distribution_helper_reports_absent_distributions(
    monkeypatch,
) -> None:
    def fake_distribution(name: str) -> object:
        if name == "opencv-python":
            raise importlib.metadata.PackageNotFoundError(name)
        return object()

    monkeypatch.setattr(importlib.metadata, "distribution", fake_distribution)

    assert _missing_ocr_runtime_distributions() == ("opencv-python",)


def test_runtime_smoke_helper_skips_when_distribution_metadata_is_absent(
    monkeypatch,
) -> None:
    def fake_distribution(name: str) -> object:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "distribution", fake_distribution)

    with pytest.raises(pytest.skip.Exception, match="opencv-python"):
        _import_installed_ocr_runtime_modules()


def test_runtime_smoke_helper_fails_when_distribution_is_present_but_import_breaks(
    monkeypatch,
) -> None:
    monkeypatch.setattr(importlib.metadata, "distribution", lambda name: object())

    def fake_import_module(name: str) -> object:
        if name == "cv2":
            raise ImportError("broken native import")
        return object()

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    with pytest.raises(ImportError, match="broken native import"):
        _import_installed_ocr_runtime_modules()


def test_ocr_runtime_import_smoke_when_extras_are_installed() -> None:
    _import_installed_ocr_runtime_modules()
