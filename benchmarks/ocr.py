import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def tesseract_command():
    command = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not command and Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists():
        command = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if not command:
        raise RuntimeError("Install Tesseract with eng and spa language data or set TESSERACT_CMD.")
    return command


def make_rapid():
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

    return RapidOCR(
        params={
            "Global.model_root_dir": str(ROOT / "models"),
            "Global.log_level": "warning",
            "Det.ocr_version": OCRVersion.PPOCRV4,
            "Det.model_type": ModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.lang_type": LangRec.LATIN,
            "EngineConfig.onnxruntime.intra_op_num_threads": 1,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        }
    )


def tesseract(image, language):
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    result = subprocess.run(
        [tesseract_command(), "stdin", "stdout", "-l", language, "--psm", "3"],
        input=buffer.getvalue(),
        capture_output=True,
        check=True,
        timeout=90,
        env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return result.stdout.decode("utf-8")


if __name__ == "__main__":
    make_rapid()
    print("RapidOCR Latin models are ready for local inference.")
