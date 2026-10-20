"""Turn an uploaded file into an ordered list of elements (headings, paragraphs,
tables) with page numbers and positions. PDF, DOCX, legacy DOC and images go
through Docling; plain text and RTF are split into paragraphs directly."""

import logging
import re
import sys
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from io import BytesIO

from app.config import get_settings

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
DOCLING_EXTENSIONS = {".pdf", ".docx", ".doc"} | IMAGE_EXTENSIONS

# A PDF page with less extractable text than this is treated as scanned (OCR'd).
_MIN_TEXT_LAYER_CHARS = 20

# Docling's models aren't documented as thread-safe, and conversions are memory
# hungry, so convert one file at a time per process.
_convert_lock = threading.Lock()


class ExtractionError(Exception):
    pass


@dataclass
class Element:
    kind: str  # "heading" | "text" | "table"
    text: str
    page_start: int | None = None
    page_end: int | None = None
    # [{"page", "x", "y", "width", "height"}] as fractions of the page size, origin
    # top-left, so a viewer can scale them to whatever size it renders the page at.
    bboxes: list[dict] = field(default_factory=list)
    source: str = "text_layer"  # or "ocr"


@dataclass
class ParsedDocument:
    elements: list[Element]
    page_count: int | None


def parse(data: bytes, ext: str) -> ParsedDocument:
    if ext in DOCLING_EXTENSIONS:
        parsed = _parse_with_docling(data, ext)
    elif ext == ".rtf":
        from striprtf.striprtf import rtf_to_text

        parsed = ParsedDocument(_plain_text_elements(rtf_to_text(data.decode(errors="replace"))), None)
    elif ext == ".txt":
        parsed = ParsedDocument(_plain_text_elements(data.decode(errors="replace")), None)
    else:
        raise ExtractionError(f"No parser for {ext}")

    if not parsed.elements:
        raise ExtractionError("No text found in the document")
    return parsed


def _plain_text_elements(text: str) -> list[Element]:
    return [Element("text", " ".join(p.split())) for p in re.split(r"\n\s*\n", text) if p.strip()]


@lru_cache
def _converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        HeadingHierarchyOptions,
        OcrAutoOptions,
        OcrMacOptions,
        PdfPipelineOptions,
    )
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

    engine = get_settings().ocr_engine
    if engine == "ocrmac" and sys.platform != "darwin":
        engine = "auto"
    options = PdfPipelineOptions(
        # Default OCR mode only OCRs regions without a text layer, so digital
        # PDFs keep their exact text.
        do_ocr=engine != "none",
        ocr_options=OcrMacOptions() if engine == "ocrmac" else OcrAutoOptions(),
        do_table_structure=True,
        heading_hierarchy_options=HeadingHierarchyOptions(enabled=True),
    )
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=options),
        }
    )


def _parse_with_docling(data: bytes, ext: str) -> ParsedDocument:
    """PDFs are converted `PARSE_PAGE_BATCH` pages at a time, so Docling's memory
    stays bounded on long documents; page numbers stay those of the whole file."""
    settings = get_settings()
    if ext == ".pdf":
        page_total = _pdf_page_count(data)
        if page_total > settings.max_pages:
            raise ExtractionError(f"Document has {page_total} pages; the limit is {settings.max_pages}")
        ocr_pages = _pages_without_text_layer(data)
        batch = max(1, settings.parse_page_batch)
        elements: list[Element] = []
        for first in range(1, page_total + 1, batch):
            doc = _convert(data, ext, page_range=(first, min(first + batch - 1, page_total)))
            elements.extend(_elements(doc, ocr_pages))
        return ParsedDocument(elements, page_total)

    doc = _convert(data, ext)
    if ext in IMAGE_EXTENSIONS:
        return ParsedDocument(_elements(doc, None), doc.num_pages())  # everything is OCR
    return ParsedDocument(_elements(doc, set()), None)


def _convert(data: bytes, ext: str, page_range: tuple[int, int] | None = None):
    from docling_core.types.io import DocumentStream

    kwargs = {"page_range": page_range} if page_range else {}
    try:
        with _convert_lock:
            result = _converter().convert(DocumentStream(name=f"document{ext}", stream=BytesIO(data)), **kwargs)
    except Exception as exc:
        if ext == ".doc":
            raise ExtractionError("Legacy .doc conversion failed (it needs LibreOffice installed)") from exc
        raise
    return result.document


def _elements(doc, ocr_pages: set[int] | None) -> list[Element]:
    """`ocr_pages`: pages without a text layer; None means everything was OCR'd."""
    from docling_core.types.doc import DocItemLabel

    headings = {DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER}
    texts = {
        DocItemLabel.TEXT,
        DocItemLabel.PARAGRAPH,
        DocItemLabel.LIST_ITEM,
        DocItemLabel.FOOTNOTE,
        DocItemLabel.CODE,
        DocItemLabel.FORMULA,
        DocItemLabel.HANDWRITTEN_TEXT,
    }
    # Captions are folded into their table; the table of contents would create
    # fake clause boundaries; pictures carry no text.
    elements: list[Element] = []
    for item, _level in doc.iterate_items():
        if item.label in headings:
            kind, text = "heading", item.text
        elif item.label in texts:
            kind, text = "text", item.text
            marker = getattr(item, "marker", "") or ""
            if getattr(item, "enumerated", False) and marker and not text.startswith(marker):
                text = f"{marker} {text}"
        elif item.label == DocItemLabel.TABLE:
            kind, text = "table", item.export_to_markdown(doc=doc)
            caption = item.caption_text(doc)
            if caption:
                text = f"{caption}\n{text}"
        else:
            continue

        text = text.strip()
        if not text:
            continue
        pages = sorted({p.page_no for p in item.prov})
        elements.append(
            Element(
                kind=kind,
                text=text,
                page_start=pages[0] if pages else None,
                page_end=pages[-1] if pages else None,
                bboxes=[box for p in item.prov if (box := _relative_bbox(doc, p)) is not None],
                # Approximation: Docling may also OCR a bitmap region on an otherwise digital page.
                source="ocr" if ocr_pages is None or (pages and set(pages) <= ocr_pages) else "text_layer",
            )
        )
    return elements


def _pdf_page_count(data: bytes) -> int:
    from pypdf import PdfReader

    try:
        return len(PdfReader(BytesIO(data)).pages)
    except Exception as exc:
        raise ExtractionError("Couldn't read the PDF") from exc


def _relative_bbox(doc, prov) -> dict | None:
    page = doc.pages.get(prov.page_no)
    if page is None or not page.size.width or not page.size.height:
        return None
    width, height = page.size.width, page.size.height
    box = prov.bbox.to_top_left_origin(page_height=height)
    return {
        "page": prov.page_no,
        "x": round(box.l / width, 4),
        "y": round(box.t / height, 4),
        "width": round((box.r - box.l) / width, 4),
        "height": round((box.b - box.t) / height, 4),
    }


def _pages_without_text_layer(data: bytes) -> set[int]:
    from pypdf import PdfReader

    try:
        return {
            n
            for n, page in enumerate(PdfReader(BytesIO(data)).pages, start=1)
            if len((page.extract_text() or "").strip()) < _MIN_TEXT_LAYER_CHARS
        }
    except Exception:
        log.warning("Couldn't inspect the PDF text layer; marking all text as text_layer", exc_info=True)
        return set()
