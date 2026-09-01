import tomllib
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]


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
