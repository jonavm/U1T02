# Extraction Benchmark

This phase 3 experiment compares PDF text extraction, OCR, and page-level hybrid extraction. It does not change the running API or enable document processing.

## Reproduce on Windows

Use Python 3.12 and install Tesseract with both `eng` and `spa` trained data. If Tesseract is not on PATH or in its standard Windows directory, set `TESSERACT_CMD` to its executable. Set `TESSDATA_PREFIX` if language data is stored elsewhere.

From the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r benchmarks/requirements.txt
.\.venv\Scripts\python.exe -m benchmarks.ocr
.\.venv\Scripts\python.exe -m benchmarks.generate
.\.venv\Scripts\python.exe -m benchmarks.run --repetitions 3
.\.venv\Scripts\python.exe -m pytest benchmarks/tests -q
```

The OCR preparation command downloads versioned public models into `benchmarks/models/` if needed. The benchmark then processes local files locally; it does not send document content to a service. Model files are excluded from version control; model hashes and all installed package versions are recorded with the results. Dependency installation and initial model download are excluded from inference timings.

The checked-in corpus can be reused without running the generator. Regeneration is deterministic under the recorded dependency versions; image encoders or rendering versions can change file hashes across environments. The runner verifies each input hash against the manifest before measuring it. Re-running replaces the recorded results, so copy `results/` first if preserving a comparison run.

## Corpus

Eleven synthetic documents with expected text authored in `generate.py` before extraction:

| Group | Count | Contents |
|---|---:|---|
| Digital PDF | 3 | English, Spanish, and two-column English text. |
| Scanned PDF | 2 | Image-only versions of the English and Spanish pages. |
| Mixed PDF | 1 | Digital English page followed by scanned Spanish page. |
| Images | 4 | Clean English/Spanish PNG, degraded English JPEG, Spanish receipt JPEG. |
| TXT | 1 | UTF-8 English and Spanish baseline. |

Spanish text is intentional language-coverage test data. Project documentation and code remain in English. The corpus is synthetic and contains no personal records. Some samples reuse content to isolate format effects; these are not eleven independent real-world documents. Handwriting, photographs with perspective, complex tables, rotation by 90 degrees, and large PDFs are outside this experiment.

`corpus/manifest.json` lists input hashes, categories, language settings, and expected-text filenames. `results/corpus-preview.png` shows every PDF page and image; the samples were visually checked for clipping and agreement with the intended text.

## Compared Methods

- **pypdf:** default native text extraction from each PDF page.
- **PyMuPDF:** native `get_text("text", sort=False)` extraction, preserving its default ordering behavior.
- **Tesseract:** page segmentation mode 3, single OpenMP thread, the sample's language (`eng`, `spa`, or `spa+eng`). A new CLI process is launched per page.
- **RapidOCR:** ONNX Runtime on CPU, one intra/inter-op thread, PP-OCRv4 mobile detector, mobile orientation classifier, and PP-OCRv5 Latin mobile recognizer. The same model covers both English and Spanish. Other settings retain version 3.9.2 defaults.
- **Hybrid Tesseract / Hybrid RapidOCR:** extract each page with pypdf; render and OCR only pages with no non-whitespace native text.
- **UTF-8:** direct file reading, used only as a baseline.

Both OCR engines use the same PDFium rasterizer at 180 DPI. Image inputs are read at their existing resolution. The PDFium render, image decoding, and Tesseract subprocess launch are included in the applicable measured call. RapidOCR retains a loaded model within each worker process, as a long-lived worker would. Its initialization time is recorded separately.

## Measurement Rules

- Each method runs in a fresh process, sequentially, using the same fixed sample order.
- Each method/sample pair has one first call (reported separately) and three measured repetitions; the median is reported. The first call to a method may include lazy imports. These measurements are warm-process timings, not controlled cold-cache measurements.
- Extracted text must be identical across all four calls. The run fails if it changes.
- Normalize Unicode to NFC and collapse whitespace before comparison. Preserve case, accents, punctuation, and reading order.
- Character error rate (CER) is character edit distance divided by reference character count. Word error rate (WER) uses whitespace-delimited token edit distance. Lower is better; insertion-heavy outputs can exceed 100%.
- Expected text comes from the authored corpus, never from an OCR engine. Two-column reading order is left column, then right column.
- OCR-only comparisons use the same six inputs: four images and two scanned PDFs. Native/hybrid PDF comparisons use the same six PDFs. Do not compare group aggregates across different input sets.
- Memory is an approximate peak RSS sum for the method process and its child processes, sampled every 20 ms over initialization and all its cases. It includes interpreter/library overhead and may miss short peaks or double-count shared pages. Sampling errors are recorded; memory is not a precise allocation metric or a capacity guarantee.
- Other applications and Docker services may be running. Three repetitions and short synthetic documents support a small assignment benchmark, not a general performance ranking.

## Evidence

- `results/environment.json`: platform, CPU/RAM, packages, models, settings, and timestamp.
- `results/<method>.json`: per-case timing repetitions, CER/WER counts, initialization, and sampled memory.
- `results/all-results.json`: combined machine-readable measurements.
- `results/summary.md`: generated per-case comparison table.
- `results/outputs/<method>/*.txt`: exact extracted text for error inspection.
- `../docs/03-extraction-benchmark.md`: findings and selected approach for phase 4.

Dependencies are isolated from production requirements. The benchmark is run locally; its timing results do not claim to describe container performance.
