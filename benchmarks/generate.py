"""Generate a fixed synthetic corpus and ground truth without using OCR output."""

import hashlib
import json
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageEnhance, ImageFilter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus"
EN = [
    "Document Intelligence - Operations Note",
    "Reference: DS-2026-0919",
    "The service accepts documents and stores each original file.",
    "A worker extracts text while the client checks job progress.",
    "Queue messages contain identifiers rather than document bytes.",
    "Retries must preserve the original job and avoid duplicate results.",
    "Upload limit: 20 MiB. Maximum PDF length: 100 pages.",
    "Measured values: 42 records, 98.5 percent, and 1250.75 units.",
    "Contact: research@example.org",
    "Status: ready for review.",
]
ES = [
    "Inteligencia documental - Nota de operaciones",
    "Referencia: MX-2026-0919",
    "El sistema recibe documentos y conserva el archivo original.",
    "La extracción continúa mientras el usuario consulta el progreso.",
    "La información incluye tamaño, fecha y método de análisis.",
    "Un reinicio no debe perder trabajos ni duplicar los resultados.",
    "Revisión: miércoles. Ubicación: Ciudad de México.",
    "Valores: 42 registros, 98.5 por ciento y 1250.75 unidades.",
    "Caracteres: á, é, í, ó, ú, ü, ñ, ¿qué?, ¡sí!",
    "Estado: listo para revisión.",
]
LEFT = [
    "Ingestion",
    "Accept the file.",
    "Validate its format.",
    "Store its original bytes.",
    "Register the job.",
    "Return its identifier.",
]
RIGHT = [
    "Processing",
    "Read a queued identifier.",
    "Locate the saved file.",
    "Extract its text.",
    "Save the result.",
    "Report the final state.",
]


def write_pdf(path, lines):
    document = canvas.Canvas(str(path), pagesize=(612, 792), invariant=1, pageCompression=1)
    document.setFont("Helvetica", 12)
    for i, line in enumerate(lines):
        document.drawString(42, 738 - i * 27, line)
    document.save()


def render(path, dpi=180):
    with pdfium.PdfDocument(path) as document:
        page = document[0]
        bitmap = page.render(scale=dpi / 72)
        image = bitmap.to_pil().convert("RGB").copy()
        bitmap.close()
        page.close()
    return image


def generate():
    CORPUS.mkdir(parents=True, exist_ok=True)
    manifest = []

    def register(name, group, language, lines, note):
        path = CORPUS / name
        truth = path.stem + ".expected.txt"
        (CORPUS / truth).write_text("\n".join(lines) + "\n", encoding="utf-8")
        manifest.append(
            {
                "id": path.stem,
                "file": name,
                "group": group,
                "language": language,
                "expected": truth,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "description": note,
            }
        )

    for lang, lines in (("eng", EN), ("spa", ES)):
        pdf = CORPUS / f"digital_{lang}.pdf"
        write_pdf(pdf, lines)
        register(
            pdf.name, "digital_pdf", lang, lines, "Single-column selectable text, Helvetica 12."
        )
        image = render(pdf)
        name = f"clean_{lang}.png"
        image.save(CORPUS / name)
        register(name, "image", lang, lines, "Clean synthetic scan at 180 DPI.")
        scan = CORPUS / f"scanned_{lang}.pdf"
        document = canvas.Canvas(str(scan), pagesize=(612, 792), invariant=1)
        document.drawImage(ImageReader(image), 0, 0, width=612, height=792)
        document.save()
        register(scan.name, "scanned_pdf", lang, lines, "Image-only PDF; no text layer.")

    columns = CORPUS / "digital_columns.pdf"
    document = canvas.Canvas(str(columns), pagesize=(612, 792), invariant=1)
    document.setFont("Helvetica", 12)
    for x, lines in ((42, LEFT), (330, RIGHT)):
        for i, line in enumerate(lines):
            document.drawString(x, 738 - i * 27, line)
    document.save()
    register(
        columns.name,
        "digital_pdf",
        "eng",
        LEFT + RIGHT,
        "Two columns; ground truth reads the left column before the right column.",
    )

    image = render(CORPUS / "digital_eng.pdf", dpi=120)
    degraded = ImageEnhance.Contrast(image).enhance(0.60).filter(ImageFilter.GaussianBlur(0.7))
    degraded = degraded.rotate(
        2.5, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white"
    )
    degraded.save(CORPUS / "degraded_eng.jpg", quality=45)
    register(
        "degraded_eng.jpg",
        "image",
        "eng",
        EN,
        "120 DPI, 2.5-degree skew, 0.60 contrast, 0.7 blur, JPEG quality 45.",
    )

    receipt = [
        "MERCADO CENTRAL",
        "Fecha: 19/09/2026",
        "Ticket: MX-0042",
        "Café molido: 125.50",
        "Pan integral: 48.00",
        "Azúcar: 32.25",
        "Total: 205.75",
        "Pago recibido: 250.00",
        "Cambio: 44.25",
        "¡Gracias por su compra!",
    ]
    # Build this image directly from a temporary PDF to keep the same font renderer.
    import io

    buffer = io.BytesIO()
    document = canvas.Canvas(buffer, pagesize=(300, 400), invariant=1)
    document.setFont("Courier", 12)
    for i, line in enumerate(receipt):
        document.drawString(15, 375 - i * 30, line)
    document.save()
    with pdfium.PdfDocument(buffer.getvalue()) as pdf:
        page = pdf[0]
        bitmap = page.render(scale=2)
        bitmap.to_pil().convert("RGB").save(CORPUS / "receipt_spa.jpg", quality=75)
        bitmap.close()
        page.close()
    register(
        "receipt_spa.jpg", "image", "spa", receipt, "Synthetic receipt, 144 DPI, JPEG quality 75."
    )

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.append(CORPUS / "digital_eng.pdf")
    writer.append(CORPUS / "scanned_spa.pdf")
    writer.write(CORPUS / "mixed.pdf")
    writer.close()
    register(
        "mixed.pdf",
        "mixed_pdf",
        "spa+eng",
        EN + ES,
        "Two pages: English selectable text, then a Spanish scanned page.",
    )
    (CORPUS / "plain_utf8.txt").write_text("\n".join(EN + ES) + "\n", encoding="utf-8")
    register("plain_utf8.txt", "text", "spa+eng", EN + ES, "UTF-8 direct-read baseline.")
    (CORPUS / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Visual QA contact sheet for every PDF page and image sample.
    cards = []
    from PIL import ImageDraw

    for sample in manifest:
        path = CORPUS / sample["file"]
        if path.suffix == ".txt":
            continue
        images = []
        if path.suffix == ".pdf":
            with pdfium.PdfDocument(path) as pdf:
                for page in pdf:
                    bitmap = page.render(scale=1)
                    images.append(bitmap.to_pil().convert("RGB").copy())
                    bitmap.close()
                    page.close()
        else:
            with Image.open(path) as image:
                images.append(image.convert("RGB").copy())
        for number, image in enumerate(images, 1):
            card = Image.new("RGB", (340, 470), "#e5e7eb")
            image.thumbnail((330, 435))
            card.paste(image, ((340 - image.width) // 2, 30))
            ImageDraw.Draw(card).text((8, 8), f"{sample['id']} / {number}", fill="black")
            cards.append(card)
    sheet = Image.new("RGB", (340 * 4, 470 * ((len(cards) + 3) // 4)), "white")
    for i, card in enumerate(cards):
        sheet.paste(card, ((i % 4) * 340, (i // 4) * 470))
    (ROOT / "results").mkdir(exist_ok=True)
    sheet.save(ROOT / "results" / "corpus-preview.png")
    print(f"Generated {len(manifest)} samples with independent expected text.")


if __name__ == "__main__":
    generate()
