# Phase 3: Extraction Benchmark and Decision

Status: complete. The benchmark ran locally on 2026-09-19. The selected tools were subsequently integrated in phase 4; see `04-processing.md` for the runtime and verification record.

## Decision for Phase 4

Use **pypdf for native PDF text**, **PDFium through pypdfium2 to render pages needing OCR**, **Tesseract for OCR**, and **direct UTF-8 reading for TXT**. Process PDF pages individually so an image-only page does not disappear when another page contains selectable text.

This choice is supported by the measured corpus below. It is a starting point for this assignment, not a claim that these tools outperform every alternative on arbitrary documents.

## Corpus and Method

The experiment contains 11 synthetic documents: three digital PDFs, two scanned PDFs, one mixed PDF, four images, and one UTF-8 file. The samples include English, Spanish accents and punctuation, two columns, a receipt, and an intentionally degraded JPEG. Expected text was authored before extraction and visually checked against the generated samples.

Seven methods produced 37 method/sample comparisons. Each comparison used one first call followed by three measured repetitions, for 148 extraction calls. Outputs were identical across the four calls for each comparison. Each method ran in its own fresh process; OCR inference used CPU with one configured thread. The recorded host had 10 physical / 16 logical CPU cores, 31.71 GiB RAM, Windows 11, and Python 3.12.14. Exact versions, model hashes, and settings are in [environment.json](../benchmarks/results/environment.json).

CER and WER are character and word edit distances divided by reference length. Normalization collapses whitespace and normalizes Unicode to NFC while preserving case, accents, punctuation, and reading order. The following CER/WER aggregates sum errors and reference lengths across the stated subset. Time is the arithmetic mean of each sample's three-run median. Compare methods only within the same subset.

## Results

| Input subset | Method | Documents | CER | WER | Mean of median times |
|---|---|---:|---:|---:|---:|
| Digital PDFs | pypdf | 3 | 0.00% | 0.00% | 1.44 ms |
| Digital PDFs | PyMuPDF | 3 | 0.00% | 0.00% | 1.07 ms |
| Images and scanned PDFs | Tesseract | 6 | 0.34% | 2.65% | 441.50 ms |
| Images and scanned PDFs | RapidOCR Latin | 6 | 9.69% | 10.61% | 1761.84 ms |
| All PDFs | pypdf + Tesseract fallback | 6 | 0.34% | 2.16% | 309.06 ms |
| All PDFs | pypdf + RapidOCR fallback | 6 | 5.97% | 6.06% | 1063.21 ms |
| UTF-8 text | Direct reading | 1 | 0.00% | 0.00% | 0.05 ms |

The PDF subset contains fast digital cases and slower OCR cases, so its overall time should not be interpreted as typical OCR latency. Full per-case results are in the generated [summary](../benchmarks/results/summary.md), with [raw measurements](../benchmarks/results/all-results.json) and [extracted outputs](../benchmarks/results/outputs/).

### Observed failure modes

- Both native PDF readers returned no text from image-only PDFs: 100% CER on those cases. On the two-page mixed PDF, both missed the scanned page and reached 50.81% CER. This is expected for extraction without OCR and agrees with the distinction described in the [pypdf documentation](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).
- The Tesseract hybrid recovered the scanned page of the mixed PDF, reducing CER to 0.71% at a median of 775.01 ms. The remaining errors were OCR errors, not a missing page.
- Tesseract confused some isolated accented characters in the Spanish character list. On the clean Spanish image, it returned substitutions such as `€` for `é` and `A` for `ñ`. These errors remain in the stored output; they were not corrected before scoring.
- The tested RapidOCR configuration omitted one full line from both clean English and clean Spanish pages. For example, it omitted the English sentence beginning `Queue messages contain identifiers`. This explains much of its measured error; other model/configuration choices could behave differently.
- RapidOCR achieved 0% CER on the degraded English JPEG, compared with Tesseract's 0.21%. That case shows why the overall result must not be presented as universal OCR superiority.

### Memory and initialization

| Method process | Approximate peak process-tree RSS |
|---|---:|
| pypdf | 34.86 MiB |
| PyMuPDF | 51.71 MiB |
| Tesseract OCR | 141.86 MiB |
| RapidOCR OCR | 909.05 MiB |
| Hybrid Tesseract | 147.44 MiB |
| Hybrid RapidOCR | 755.89 MiB |

RSS was sampled every 20 ms across each method's initialization and all its cases, including child processes. No sampling errors were reported. These values include interpreter/library overhead, can double-count shared pages, and can miss short peaks; they are approximate observations rather than exact memory requirements.

RapidOCR model initialization took 677.13 ms for the OCR method and 693.45 ms for the hybrid method. Other methods load libraries lazily during their first call, so their near-zero constructor time is not comparable to RapidOCR initialization. First-call timings are retained separately. Tesseract startup remains included in every per-page call; RapidOCR reuses its models, reflecting a persistent worker design.

## Technical Rationale and Dependencies

| Component | Finding and decision |
|---|---|
| pypdf 6.19.0 | Matched expected text on all three digital PDFs. Its measured latency was adequate for this scope. Selected as the native parser. |
| PyMuPDF 1.28.2 | Also matched all three digital PDFs and was slightly faster. The sub-millisecond difference on this small corpus does not justify selecting it for this implementation. Retained as a benchmark alternative. |
| pypdfium2 5.13.0 | Used by both OCR candidates to render the same PDF pages at 180 DPI, avoiding a renderer difference between comparisons. Selected for rendering. |
| Tesseract 5.5.3.20260724 | Lower aggregate OCR error, time, and sampled memory on this corpus. Selected with English/Spanish trained data. Requires a native executable and language files in the worker image. |
| RapidOCR 3.9.2 + ONNX Runtime 1.30.0 | Runs locally and supports a Latin recognizer. The tested configuration needed more time and memory and omitted lines. Keep as an alternative if broader samples expose weaknesses in Tesseract. |

License and installation considerations also inform the choice:

- pypdf uses [BSD-3-Clause](https://github.com/py-pdf/pypdf/blob/main/LICENSE).
- PyMuPDF is offered under [AGPL or a commercial license](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright). Selecting pypdf avoids adding this dependency to the production image; PyMuPDF remains an explicitly installed benchmark dependency.
- pypdfium2 offers [Apache-2.0 / BSD-3-Clause terms](https://github.com/pypdfium2-team/pypdfium2#licensing); PDFium and bundled dependencies carry their own notices. Preserve the notices shipped with the wheel when building the worker image.
- Tesseract uses [Apache-2.0](https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE), and its [installation documentation](https://tesseract-ocr.github.io/tessdoc/Installation.html) describes the separate language data requirement.
- RapidOCR uses [Apache-2.0](https://github.com/RapidAI/RapidOCR/blob/main/LICENSE). The tested detector and Latin recognizer were explicitly selected through the [documented configuration interface](https://rapidai.github.io/RapidOCRDocs/main/en/install_usage/rapidocr/usage/); downloaded model hashes are recorded.

Production package additions and the Linux Tesseract installation will occur in phase 4. This run used the existing Windows Tesseract executable. Its timing and accuracy are not asserted to be identical to a future container build; pin and validate the selected container version then.

## Proposed Processing Rules

1. Read TXT as UTF-8 without OCR.
2. Parse each PDF page with pypdf. Preserve useful native text.
3. Render image-only pages with PDFium and run Tesseract using the requested language. The benchmark uses 180 DPI; keep this configurable and evaluate 300 DPI for small text if needed.
4. OCR PNG/JPG inputs with Tesseract after image decoding and basic orientation handling.
5. Record the per-page extraction method, OCR language, page count, duration, and warnings alongside the text.

The measured hybrid uses only an empty-text trigger. A page with a selectable header and a scanned body can therefore be incomplete even though its extracted text is nonempty. Before treating the worker as robust, add coverage for partially scanned pages, unreadable text layers, blank pages, and low-quality images; support an explicit OCR override or an improved detection rule. The benchmark proves handling of different page types within one document, not every mixed-content layout within a page.

## Limits and Completion

This is a small synthetic benchmark with reused text and three measured repetitions. It does not cover handwriting, real camera perspective, complex tables, 90-degree rotation, long documents, throughput under concurrency, or hostile/corrupted inputs. Fixed method ordering, other running applications, and warm filesystem caches can influence timings. Model settings were not tuned to the evaluation corpus.

Completed deliverables:

- A reproducible corpus with expected text, descriptions, and input hashes.
- A benchmark runner, raw timings, CER/WER counts, memory observations, model/version metadata, and saved extraction outputs.
- Five passing tests for scoring behavior and a visual review of the corpus.
- An evidence-based parser/OCR decision for phase 4.

See [benchmark instructions](../benchmarks/README.md) to reproduce the experiment. The subsequent Redis/Celery implementation is documented in [phase 4](04-processing.md).
