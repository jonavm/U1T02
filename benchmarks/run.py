"""Run each extraction method in a fresh process and retain raw evidence."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil

from benchmarks.metrics import score
from benchmarks.ocr import make_rapid, tesseract, tesseract_command

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus"
RESULTS = ROOT / "results"
METHODS = [
    "pypdf",
    "pymupdf",
    "tesseract",
    "rapidocr",
    "hybrid_tesseract",
    "hybrid_rapidocr",
    "utf8",
]


def raster_page(path, index):
    import pypdfium2 as pdfium

    with pdfium.PdfDocument(path) as document:
        page = document[index]
        bitmap = page.render(scale=180 / 72)
        image = bitmap.to_pil().convert("RGB").copy()
        bitmap.close()
        page.close()
    return image


class Extractor:
    def __init__(self, method):
        self.method = method
        self.rapid = make_rapid() if "rapidocr" in method else None

    def ocr(self, image, language):
        if self.rapid is not None:
            result = self.rapid(image)
            return "\n".join(result.txts or ())
        return tesseract(image, language)

    def __call__(self, sample):
        path = CORPUS / sample["file"]
        if self.method == "utf8":
            return path.read_text(encoding="utf-8")
        if self.method == "pymupdf":
            import pymupdf

            with pymupdf.open(path) as document:
                return "\n".join(page.get_text("text", sort=False) for page in document)
        if self.method == "pypdf" or self.method.startswith("hybrid"):
            from pypdf import PdfReader

            document = PdfReader(path)
            texts = []
            for index, page in enumerate(document.pages):
                text = page.extract_text() or ""
                if self.method.startswith("hybrid") and not text.strip():
                    with raster_page(path, index) as image:
                        text = self.ocr(image, sample["language"])
                texts.append(text)
            return "\n".join(texts)
        if path.suffix == ".pdf":
            from pypdf import PdfReader

            texts = []
            for index in range(len(PdfReader(path).pages)):
                with raster_page(path, index) as image:
                    texts.append(self.ocr(image, sample["language"]))
            return "\n".join(texts)
        from PIL import Image

        with Image.open(path) as image:
            return self.ocr(image.convert("RGB"), sample["language"])


def applicable(method, sample):
    if method == "utf8":
        return sample["group"] == "text"
    if method in ("tesseract", "rapidocr"):
        return sample["group"] in ("image", "scanned_pdf")
    return sample["file"].endswith(".pdf")


class MemorySampler:
    """Approximate RSS of this process tree; sampled peaks are lower bounds."""

    def __init__(self):
        self.peak = 0
        self.failures = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        process = psutil.Process()
        while not self.stop.is_set():
            try:
                total = process.memory_info().rss
                for child in process.children(recursive=True):
                    try:
                        total += child.memory_info().rss
                    except psutil.Error:
                        self.failures += 1
                self.peak = max(self.peak, total)
            except psutil.Error:
                self.failures += 1
            self.stop.wait(0.02)


def worker(method, repetitions):
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    memory = MemorySampler()
    memory.thread.start()
    start = time.perf_counter()
    extractor = Extractor(method)
    initialization_ms = (time.perf_counter() - start) * 1000
    records = []
    outputs = RESULTS / "outputs" / method
    outputs.mkdir(parents=True, exist_ok=True)
    try:
        for sample in manifest:
            if not applicable(method, sample):
                continue
            path = CORPUS / sample["file"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == sample["sha256"]
            truth = (CORPUS / sample["expected"]).read_text(encoding="utf-8")
            timings, predictions = [], []
            for _ in range(repetitions + 1):
                started = time.perf_counter()
                prediction = extractor(sample)
                timings.append((time.perf_counter() - started) * 1000)
                predictions.append(prediction)
            if len(set(predictions)) != 1:
                raise RuntimeError(f"Non-deterministic output: {method}/{sample['id']}")
            (outputs / f"{sample['id']}.txt").write_text(predictions[-1], encoding="utf-8")
            records.append(
                {
                    "sample": sample["id"],
                    "group": sample["group"],
                    "method": method,
                    "first_call_ms": timings[0],
                    "measured_ms": timings[1:],
                    "median_ms": statistics.median(timings[1:]),
                    **score(truth, predictions[-1]),
                }
            )
            print(f"{method}: {sample['id']} finished", flush=True)
    finally:
        memory.stop.set()
        memory.thread.join()
    result = {
        "method": method,
        "initialization_ms": initialization_ms,
        "sampled_peak_process_tree_rss_mib": memory.peak / (1024 * 1024),
        "memory_sampling_errors": memory.failures,
        "records": records,
    }
    (RESULTS / f"{method}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


def main(repetitions):
    RESULTS.mkdir(exist_ok=True)
    versions = {
        distribution.metadata["Name"]: distribution.version
        for distribution in importlib.metadata.distributions()
    }
    tess = tesseract_command()
    tessdata = Path(os.environ.get("TESSDATA_PREFIX", str(Path(tess).parent / "tessdata")))
    models = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (ROOT / "models").rglob("*.onnx")
    }
    for language in ("eng", "spa"):
        path = tessdata / f"{language}.traineddata"
        if path.exists():
            models[f"tesseract/{path.name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    environment = {
        "started_at_utc": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
        "logical_cpus": psutil.cpu_count(),
        "physical_cpus": psutil.cpu_count(logical=False),
        "total_ram_gib": psutil.virtual_memory().total / 1024**3,
        "tesseract_version": subprocess.check_output([tess, "--version"]).decode().splitlines()[0],
        "tesseract_languages": subprocess.check_output([tess, "--list-langs"]).decode(),
        "model_sha256": models,
        "packages": versions,
        "repetitions": repetitions,
        "warmup_per_sample": 1,
        "pdf_raster_dpi": 180,
        "ocr_threads": 1,
        "tesseract_psm": 3,
        "gpu_enabled": False,
        "method_order": METHODS,
    }
    (RESULTS / "environment.json").write_text(json.dumps(environment, indent=2), encoding="utf-8")
    for method in METHODS:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "benchmarks.run",
                "--worker",
                method,
                "--repetitions",
                str(repetitions),
            ],
            check=True,
            timeout=600,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    rows = []
    for method in METHODS:
        rows.extend(json.loads((RESULTS / f"{method}.json").read_text())["records"])
    (RESULTS / "all-results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    lines = [
        "# Measured Results",
        "",
        "Generated from raw JSON. CER/WER preserve case and accents.",
        "",
        "| Method | Sample | CER (%) | WER (%) | Median (ms) |",
        "|---|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['method']} | {row['sample']} | {row['cer'] * 100:.2f} | "
            f"{row['wer'] * 100:.2f} | {row['median_ms']:.2f} |"
        )
    (RESULTS / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved {len(rows)} method/sample comparisons.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=METHODS)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("At least one measured repetition is required.")
    if args.worker:
        worker(args.worker, args.repetitions)
    else:
        main(args.repetitions)
