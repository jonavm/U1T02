# Measured Results

Generated from raw JSON. CER/WER preserve case and accents.

| Method | Sample | CER (%) | WER (%) | Median (ms) |
|---|---|---:|---:|---:|
| pypdf | digital_eng | 0.00 | 0.00 | 1.44 |
| pypdf | scanned_eng | 100.00 | 100.00 | 1.05 |
| pypdf | digital_spa | 0.00 | 0.00 | 1.48 |
| pypdf | scanned_spa | 100.00 | 100.00 | 1.00 |
| pypdf | digital_columns | 0.00 | 0.00 | 1.40 |
| pypdf | mixed | 50.81 | 52.11 | 2.02 |
| pymupdf | digital_eng | 0.00 | 0.00 | 1.09 |
| pymupdf | scanned_eng | 100.00 | 100.00 | 1.34 |
| pymupdf | digital_spa | 0.00 | 0.00 | 1.14 |
| pymupdf | scanned_spa | 100.00 | 100.00 | 1.11 |
| pymupdf | digital_columns | 0.00 | 0.00 | 0.99 |
| pymupdf | mixed | 50.81 | 52.11 | 1.82 |
| tesseract | clean_eng | 0.00 | 0.00 | 348.76 |
| tesseract | scanned_eng | 0.00 | 0.00 | 391.55 |
| tesseract | clean_spa | 0.80 | 5.41 | 635.68 |
| tesseract | scanned_spa | 0.80 | 5.41 | 661.69 |
| tesseract | degraded_eng | 0.21 | 2.94 | 285.57 |
| tesseract | receipt_spa | 0.00 | 0.00 | 325.73 |
| rapidocr | clean_eng | 12.94 | 11.76 | 2180.56 |
| rapidocr | scanned_eng | 12.94 | 11.76 | 2164.49 |
| rapidocr | clean_spa | 12.75 | 13.51 | 2041.32 |
| rapidocr | scanned_spa | 12.75 | 13.51 | 2076.95 |
| rapidocr | degraded_eng | 0.00 | 0.00 | 1445.83 |
| rapidocr | receipt_spa | 1.13 | 16.00 | 661.87 |
| hybrid_tesseract | digital_eng | 0.00 | 0.00 | 1.45 |
| hybrid_tesseract | scanned_eng | 0.00 | 0.00 | 394.26 |
| hybrid_tesseract | digital_spa | 0.00 | 0.00 | 1.48 |
| hybrid_tesseract | scanned_spa | 0.80 | 5.41 | 680.82 |
| hybrid_tesseract | digital_columns | 0.00 | 0.00 | 1.36 |
| hybrid_tesseract | mixed | 0.71 | 4.23 | 775.01 |
| hybrid_rapidocr | digital_eng | 0.00 | 0.00 | 1.48 |
| hybrid_rapidocr | scanned_eng | 12.94 | 11.76 | 2138.46 |
| hybrid_rapidocr | digital_spa | 0.00 | 0.00 | 1.65 |
| hybrid_rapidocr | scanned_spa | 12.75 | 13.51 | 2132.57 |
| hybrid_rapidocr | digital_columns | 0.00 | 0.00 | 1.68 |
| hybrid_rapidocr | mixed | 6.46 | 7.04 | 2103.45 |
| utf8 | plain_utf8 | 0.00 | 0.00 | 0.05 |
