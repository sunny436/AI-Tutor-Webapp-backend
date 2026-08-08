"""
documents.py
------------
Reads the medical documents a user uploads (PDF files or images) and
returns the plain text found inside them.

- PDF files  -> we try pypdf, then pdfplumber as a backup.
- Image files -> we use OCR (pytesseract) to "read" text from the picture.

OCR needs the free "Tesseract" program installed on your system. If it is
not installed, image reading is skipped gracefully (the app still works).
"""

from pathlib import Path


def read_pdf(file_path: str) -> str:
    """Extract text from a PDF report."""
    text = ""

    # First try: pypdf (fast, works for most normal PDFs)
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        for page in reader.pages:
            text += (page.extract_text() or "") + "\n"
    except Exception:
        text = ""

    # Backup try: pdfplumber (better for tables / tricky layouts)
    if not text.strip():
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text += (page.extract_text() or "") + "\n"
        except Exception:
            pass

    return text.strip()


def read_image(file_path: str) -> str:
    """Extract text from an image of a report using OCR."""
    try:
        import pytesseract
        from PIL import Image
        image = Image.open(file_path)
        return pytesseract.image_to_string(image).strip()
    except Exception:
        # Tesseract not installed, or the image could not be read.
        return ""


def extract_text(file_path: str) -> str:
    """
    Main function: figure out the file type and read its text.
    Returns the extracted text (or an empty string if nothing was found).
    """
    suffix = Path(file_path).suffix.lower()

    if suffix == ".pdf":
        return read_pdf(file_path)

    if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"}:
        return read_image(file_path)

    # Plain text files, just in case.
    if suffix in {".txt", ".md"}:
        return Path(file_path).read_text(encoding="utf-8", errors="ignore").strip()

    return ""
