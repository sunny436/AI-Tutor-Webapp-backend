"""Text extraction for one uploaded file. Runs ONLY as a separate, sandboxed process.

    python -m app.files.extract --kind pdf --ocr-langs eng+hin < file > result.json

In production it runs as a systemd transient unit (app/files/processing.py): a throwaway
user, no network, no secrets, a read-only filesystem and its own memory limit. The file is
untrusted, so everything that parses it lives here, and nothing else imports this module or
its parsers (the API process never loads them).

Protocol (PROTOCOL): stdin is the file's bytes; stdout is one JSON object:
  {"ok": true,  "protocol": 1, "pages": [{"text": str, "meta": {...}}], "pageCount": n, "ocrPages": n}
  {"ok": false, "protocol": 1, "code": <one of FAILURE_CODES>}
Exit 0 for both. Exit 3 means the environment is broken (a parser or Tesseract is missing),
not the file: the caller re-queues the file instead of failing it.

Only the standard library at import time; each parser is imported where it is used.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import re
import sys
import unicodedata
import zipfile
from datetime import date, datetime, time

PROTOCOL = 1
ENVIRONMENT_ERROR = 3

MAX_INPUT_BYTES = 25 * 1024 * 1024
MAX_PAGES = 1_000  # PDF pages or PPTX slides
MAX_CHARS = 1_500_000
MIN_CHARS = 20
# PDF pages with little text and a large image are scanned; they are read with OCR.
OCR_MAX_PAGES = 30
SCANNED_PAGE_TEXT = 200
SCANNED_PAGE_IMAGE_SHARE = 0.5
OCR_MAX_PIXELS = 12_000_000
OCR_MIN_CONFIDENCE = 60.0
IMAGE_MAX_PIXELS = 40_000_000
IMAGE_MAX_EDGE = 4_000
# Office files are zip archives: bounded before any XML is parsed.
ZIP_MAX_ENTRIES = 5_000
ZIP_MAX_PART = 40 * 1024 * 1024
ZIP_MAX_TOTAL = 150 * 1024 * 1024
ZIP_MAX_RATIO = 100
XLSX_MAX_SHEETS, XLSX_MAX_ROWS, XLSX_MAX_COLUMNS = 20, 5_000, 50

FAILURE_CODES = frozenset(
    {
        "corrupt",
        "encrypted",
        "no_text",
        "unreadable_text",
        "invalid_encoding",
        "too_many_pages",
        "too_many_scanned_pages",
        "too_many_rows",
        "content_too_large",
    }
)

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


class Failure(Exception):
    """The file cannot be used; `code` says why (shown to the student)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class EnvironmentProblem(Exception):
    """This machine cannot extract right now (a missing parser or OCR engine)."""


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = _CONTROL.sub("", text)
    text = _TRAILING_SPACE.sub("\n", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


# --------------------------------------------------------------------------- OCR
def _ocr(image, langs: str) -> tuple[str, float]:
    """Text and mean word confidence (0-100) of a PIL image."""
    try:
        import pytesseract
    except ImportError as error:
        raise EnvironmentProblem("pytesseract") from error
    try:
        data = pytesseract.image_to_data(image, lang=langs, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractNotFoundError as error:
        raise EnvironmentProblem("tesseract") from error
    lines: dict[tuple, list[str]] = {}
    confidences: list[float] = []
    for i, word in enumerate(data["text"]):
        confidence = float(data["conf"][i])
        if not word.strip() or confidence < 0:
            continue
        confidences.append(confidence)
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)
    if not confidences:
        return "", 0.0
    return "\n".join(" ".join(words) for words in lines.values()), sum(confidences) / len(confidences)


# --------------------------------------------------------------------------- PDF
def _pdf(data: bytes, langs: str) -> tuple[list[dict], int, int]:
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_c
    except ImportError as error:
        raise EnvironmentProblem("pypdfium2") from error
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        raise Failure(
            "encrypted" if getattr(error, "err_code", None) == pdfium_c.FPDF_ERR_PASSWORD else "corrupt"
        ) from error
    try:
        count = len(pdf)
        if count > MAX_PAGES:
            raise Failure("too_many_pages")
        texts: list[str] = []
        scanned: list[int] = []
        for index in range(count):
            page = pdf[index]
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            textpage.close()
            texts.append(text)
            if len(text.strip()) < SCANNED_PAGE_TEXT:
                width, height = page.get_size()
                covered = 0.0
                for obj in page.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_IMAGE,)):
                    left, bottom, right, top = obj.get_bounds()
                    covered += max(0.0, right - left) * max(0.0, top - bottom)
                if width * height > 0 and covered / (width * height) >= SCANNED_PAGE_IMAGE_SHARE:
                    scanned.append(index)
            page.close()

        ocr_pages = 0
        if len(scanned) > OCR_MAX_PAGES:
            if len(scanned) >= count * 0.5:
                raise Failure("too_many_scanned_pages")
            scanned = []  # figure pages in a text document: their words are not the content
        for index in scanned:
            page = pdf[index]
            width, height = page.get_size()
            scale = min(2.5, math.sqrt(OCR_MAX_PIXELS / max(1.0, width * height)))
            image = page.render(scale=scale).to_pil().convert("L")
            page.close()
            text, confidence = _ocr(image, langs)
            ocr_pages += 1
            if confidence >= OCR_MIN_CONFIDENCE:
                texts[index] = f"{texts[index]}\n{text}"
        pages = [{"text": text, "meta": {"page": index + 1}} for index, text in enumerate(texts)]
        return pages, count, ocr_pages
    finally:
        pdf.close()


# --------------------------------------------------------------------------- Office
def _check_zip(data: bytes) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise Failure("corrupt") from error
    with archive:
        entries = archive.infolist()
        if len(entries) > ZIP_MAX_ENTRIES:
            raise Failure("content_too_large")
        total = 0
        for entry in entries:
            if entry.flag_bits & 0x1:
                raise Failure("encrypted")
            if entry.file_size > ZIP_MAX_PART:
                raise Failure("content_too_large")
            if entry.file_size > 1024 * 1024 and entry.file_size > ZIP_MAX_RATIO * max(1, entry.compress_size):
                raise Failure("content_too_large")
            total += entry.file_size
        if total > ZIP_MAX_TOTAL:
            raise Failure("content_too_large")
        try:
            content_types = archive.read("[Content_Types].xml")
        except KeyError as error:
            raise Failure("corrupt") from error
    if b"macroEnabled" in content_types:
        raise Failure("corrupt")  # .docm/.pptm/.xlsm renamed: never opened


def _walk_word(element, out: list[str]) -> None:
    """Text of a Word body in document order: paragraphs, tables, text boxes, equations."""
    tag = element.tag
    if tag in (_W + "t", _M + "t"):
        out.append(element.text or "")
    elif tag == _W + "tab":
        out.append("\t")
    elif tag in (_W + "br", _W + "cr"):
        out.append("\n")
    for child in element:
        _walk_word(child, out)
    if tag == _W + "p":
        out.append("\n")
    elif tag == _W + "tc":
        out.append("\t")


def _docx(data: bytes) -> tuple[list[dict], int]:
    _check_zip(data)
    try:
        import docx
    except ImportError as error:
        raise EnvironmentProblem("python-docx") from error
    try:
        document = docx.Document(io.BytesIO(data))
        out: list[str] = []
        _walk_word(document.element.body, out)
    except (ValueError, KeyError, RecursionError, zipfile.BadZipFile) as error:
        raise Failure("corrupt") from error
    return [{"text": "".join(out), "meta": {}}], 1


def _shape_text(shape, out: list[str]) -> None:
    from pptx.shapes.group import GroupShape

    try:
        if isinstance(shape, GroupShape):
            for child in shape.shapes:
                _shape_text(child, out)
            return
        if shape.has_text_frame:
            out.append(shape.text_frame.text)
        if getattr(shape, "has_table", False) and shape.has_table:
            for row in shape.table.rows:
                out.append("\t".join(cell.text for cell in row.cells))
    except NotImplementedError:
        return  # a shape python-pptx cannot describe (ink, an unusual autoshape): skip it, keep the deck


def _pptx(data: bytes) -> tuple[list[dict], int]:
    _check_zip(data)
    try:
        import pptx
    except ImportError as error:
        raise EnvironmentProblem("python-pptx") from error
    try:
        presentation = pptx.Presentation(io.BytesIO(data))
        slides = list(presentation.slides)
        if len(slides) > MAX_PAGES:
            raise Failure("too_many_pages")
        pages = []
        for number, slide in enumerate(slides, start=1):
            out: list[str] = []
            for shape in slide.shapes:
                _shape_text(shape, out)
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
                out.append(slide.notes_slide.notes_text_frame.text)
            pages.append({"text": "\n".join(out), "meta": {"slide": number}})
    except Failure:
        raise
    except (ValueError, KeyError, RecursionError, zipfile.BadZipFile) as error:
        raise Failure("corrupt") from error
    return pages, len(slides)


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _xlsx(data: bytes) -> tuple[list[dict], int]:
    _check_zip(data)
    try:
        import openpyxl
    except ImportError as error:
        raise EnvironmentProblem("openpyxl") from error
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as error:  # noqa: BLE001 - any failure to open is an unreadable workbook
        raise Failure("corrupt") from error
    try:
        sheets = workbook.worksheets
        if len(sheets) > XLSX_MAX_SHEETS:
            raise Failure("too_many_rows")
        pages = []
        for sheet in sheets:
            buffer = io.StringIO()
            writer = csv.writer(buffer, lineterminator="\n")
            for number, row in enumerate(sheet.iter_rows(values_only=True)):
                if number >= XLSX_MAX_ROWS:
                    raise Failure("too_many_rows")
                values = [_cell(value) for value in row]
                while values and not values[-1]:
                    values.pop()
                if len(values) > XLSX_MAX_COLUMNS:
                    raise Failure("too_many_rows")
                if values:
                    writer.writerow(values)
            pages.append({"text": buffer.getvalue(), "meta": {"sheet": str(sheet.title)[:100]}})
    finally:
        workbook.close()
    return pages, len(pages)


# --------------------------------------------------------------------------- text and images
def _text(data: bytes) -> tuple[list[dict], int]:
    if data.startswith(b"\xef\xbb\xbf"):
        try:
            text = data[3:].decode("utf-8")
        except UnicodeDecodeError as error:
            raise Failure("invalid_encoding") from error
    elif data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            text = data.decode("utf-16")
        except UnicodeDecodeError as error:
            raise Failure("invalid_encoding") from error
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")
    if "\x00" in text:
        raise Failure("invalid_encoding")
    bad = sum(1 for ch in text if (ord(ch) < 32 and ch not in "\t\n\r") or 0x7F <= ord(ch) <= 0x9F or ch == "�")
    if text and bad > 0.05 * len(text):
        raise Failure("invalid_encoding")
    return [{"text": text, "meta": {}}], 1


def _image(data: bytes, langs: str) -> tuple[list[dict], int, int]:
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as error:
        raise EnvironmentProblem("Pillow") from error
    Image.MAX_IMAGE_PIXELS = IMAGE_MAX_PIXELS
    try:
        image = Image.open(io.BytesIO(data))
        width, height = image.size
        if width * height > IMAGE_MAX_PIXELS:
            raise Failure("content_too_large")
        image.seek(0)
        image = ImageOps.exif_transpose(image).convert("L")
    except Failure:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise Failure("corrupt") from error
    if max(image.size) > IMAGE_MAX_EDGE:
        image.thumbnail((IMAGE_MAX_EDGE, IMAGE_MAX_EDGE))
    text, confidence = _ocr(image, langs)
    if len(text.strip()) < MIN_CHARS:
        raise Failure("no_text")
    if confidence < OCR_MIN_CONFIDENCE:
        raise Failure("unreadable_text")
    return [{"text": text, "meta": {}}], 1, 1


# --------------------------------------------------------------------------- entry point
def extract(kind: str, data: bytes, langs: str) -> dict:
    ocr_pages = 0
    if kind == "pdf":
        pages, count, ocr_pages = _pdf(data, langs)
    elif kind == "docx":
        pages, count = _docx(data)
    elif kind == "pptx":
        pages, count = _pptx(data)
    elif kind == "xlsx":
        pages, count = _xlsx(data)
    elif kind in ("csv", "txt", "md"):
        pages, count = _text(data)
    elif kind == "image":
        pages, count, ocr_pages = _image(data, langs)
    else:
        raise Failure("corrupt")
    pages = [{"text": text, "meta": page["meta"]} for page in pages if (text := normalize(page["text"]))]
    total = sum(len(page["text"]) for page in pages)
    if total > MAX_CHARS:
        raise Failure("content_too_large")
    if total < MIN_CHARS:
        raise Failure("unreadable_text" if ocr_pages else "no_text")
    return {"ok": True, "protocol": PROTOCOL, "pages": pages, "pageCount": count, "ocrPages": ocr_pages}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--ocr-langs", default="eng+hin")
    args = parser.parse_args(argv)
    # Only the JSON answer may reach stdout: anything a parser prints (openpyxl does) goes to
    # stderr, which the caller drops. The answer is written as UTF-8 bytes, whatever the locale.
    answer = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    try:
        if len(data) > MAX_INPUT_BYTES:
            raise Failure("content_too_large")
        result = extract(args.kind, data, args.ocr_langs)
    except Failure as failure:
        result = {"ok": False, "protocol": PROTOCOL, "code": failure.code}
    except (EnvironmentProblem, ImportError):
        return ENVIRONMENT_ERROR
    except MemoryError:
        result = {"ok": False, "protocol": PROTOCOL, "code": "content_too_large"}
    except Exception:  # noqa: BLE001 - a parser crash on this file is a corrupt file, never a traceback
        result = {"ok": False, "protocol": PROTOCOL, "code": "corrupt"}
    answer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    answer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
