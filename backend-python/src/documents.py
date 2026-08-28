"""
documents.py
------------
Reads the medical documents a user uploads (PDF files or images) and
returns the plain text found inside them.

- PDF files   -> pypdf, then pdfplumber, then OCR if there is no text layer.
- Image files -> OCR (pytesseract) straight away.

OCR needs the free "Tesseract" program installed, with the `eng` and `hin`
language data. If it is missing, reading degrades rather than failing - see
`_ocr`.
"""

from pathlib import Path

# Tesseract reads only the languages it is asked for, and defaults to English
# alone. People photograph reports that are partly Devanagari - the letterhead,
# the advice line, sometimes the whole page - and every one of those characters
# was being dropped before this.
#
# "eng+hin" rather than "hin": Indian lab reports are overwhelmingly English
# values on a form that may be Hindi around the edges, so both scripts have to be
# recognised in the same pass. Adding a language costs accuracy on the others, so
# this is two, not a list of everything available.
_OCR_LANGS = "eng+hin"

# How many pages of a SCANNED pdf to read. A lab report is one to three pages;
# this exists so a 300-page scan cannot turn one upload into 300 OCR passes
# inside a single request. Pages past this are not read - the right trade
# against holding the request open for several minutes.
_OCR_PAGE_LIMIT = 10

# Rasterising resolution. 200 dpi is the usual floor for reliable OCR of body
# text; below it Devanagari matras start to merge into their consonants. Higher
# costs memory linearly on a 3.8 GB host for no gain on report-sized type.
_OCR_DPI = 200


def _ocr(image) -> str:
    """OCR one PIL image, in English and Hindi.

    The nested fallback matters beyond this function. Asking tesseract for a
    language it does not have RAISES, and every caller here swallows exceptions
    into "" - so on a machine without the `hin` traineddata, naming it would turn
    every photographed report into an empty document, English ones included. That
    failure is invisible: the upload returns 200 with chars: 0 and the user is
    told their scan was unreadable. Retrying with the default costs Devanagari
    rather than everything.
    """
    import pytesseract

    try:
        return pytesseract.image_to_string(image, lang=_OCR_LANGS).strip()
    except pytesseract.TesseractError:
        return pytesseract.image_to_string(image).strip()


def _ocr_pdf(file_path: str) -> str:
    """Read a SCANNED pdf by rendering each page and running OCR on it.

    Only reached when both text extractors came back empty, which is exactly
    what a scan looks like: the page is a picture of a document, so there is no
    text layer to parse. That is the common form of an Indian lab report, and
    before this it produced nothing at all - the same report succeeded as a JPG
    and failed as a PDF, a difference no user could be expected to predict.

    Pages are rendered and released one at a time: holding ten 200-dpi bitmaps
    at once is around 100 MB of pixels for no reason.
    """
    try:
        import pymupdf
        from PIL import Image
    except Exception:
        return ""

    out = []
    try:
        with pymupdf.open(file_path) as doc:
            for page in doc[:_OCR_PAGE_LIMIT]:
                pixmap = page.get_pixmap(dpi=_OCR_DPI)
                image = Image.frombytes(
                    "RGB", (pixmap.width, pixmap.height), pixmap.samples
                )
                try:
                    out.append(_ocr(image))
                finally:
                    image.close()
    except Exception:
        # Corrupt, password-protected, or tesseract missing. Return whatever was
        # read before it broke; the caller already had nothing.
        pass

    return chr(10).join(out).strip()


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

    # Last try: no text layer at all, so read the pages as pictures.
    if not text.strip():
        text = _ocr_pdf(file_path)

    return text.strip()


def read_image(file_path: str) -> str:
    """Extract text from an image of a report using OCR."""
    try:
        from PIL import Image

        with Image.open(file_path) as image:
            return _ocr(image)
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
