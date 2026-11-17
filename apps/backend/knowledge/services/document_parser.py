"""Parse validated RAG uploads into clean, structured document elements.

Safety validation belongs in ``document_safety`` and is deliberately repeated
at this boundary when a caller does not already supply a verified type. This
module never executes document code, follows document links, or opens embedded
objects; Step 2 has already rejected those active features.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import csv
import io
from typing import Callable
import re

from knowledge.services.document_safety import DetectedDocumentType, validate_uploaded_document


@dataclass(frozen=True)
class DocumentElement:
    """One meaningful unit of parsed document content plus its source context."""

    kind: str  # prose | heading | table | image_caption
    text: str
    metadata: dict[str, str | int] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedDocument:
    """Verified source content, kept structured until the later chunking phase."""

    document_type: str
    elements: list[DocumentElement]
    warnings: list[str] = field(default_factory=list)


def _normalise_rows(rows: list[list[object | None]]) -> list[list[str]]:
    normalised = [
        [("" if value is None else str(value)).strip().replace("\n", " ").replace("|", "\\|") for value in row]
        for row in rows
    ]
    return [row for row in normalised if any(cell for cell in row)]


def _rows_to_markdown(rows: list[list[object | None]]) -> tuple[str, list[str]] | None:
    cleaned = _normalise_rows(rows)
    if not cleaned:
        return None
    headers = cleaned[0]
    if len(cleaned) == 1:
        return " | ".join(headers), headers
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in cleaned[1:])
    return "\n".join(lines), headers


def _clean_ocr_text(text: str) -> str:
    """Keep OCR output only when it contains meaningful searchable text."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in (text or "").splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    # Logos, isolated punctuation, and OCR noise must not become fake chunks.
    return cleaned if len(re.findall(r"[A-Za-z0-9]", cleaned)) >= 3 else ""


def _ocr_image(image) -> str:
    try:
        import pytesseract
        from PIL import ImageOps
        normalized = ImageOps.exif_transpose(image).convert("L")
        return _clean_ocr_text(pytesseract.image_to_string(normalized, config="--psm 6"))
    except Exception as exc:
        raise RuntimeError("OCR is unavailable. Install the Tesseract OCR runtime to process scanned images.") from exc


def _parse_pdf(data: bytes) -> ParsedDocument:
    import pdfplumber

    elements: list[DocumentElement] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                elements.append(DocumentElement("prose", text, {"page": page_number}))
            else:
                # A page with no extractable PDF text is a scan. OCR the page
                # image; if it contains no readable text, deliberately add no
                # element rather than inventing a caption.
                try:
                    ocr_text = _ocr_image(page.to_image(resolution=200).original)
                except Exception:
                    raise
                if ocr_text:
                    elements.append(DocumentElement("prose", ocr_text, {"page": page_number, "source": "ocr"}))
            try:
                tables = page.extract_tables()
            except Exception:
                tables = []
            for table_number, table in enumerate(tables, start=1):
                parsed_table = _rows_to_markdown(table)
                if parsed_table is None:
                    continue
                table_text, headers = parsed_table
                elements.append(
                    DocumentElement(
                        "table",
                        table_text,
                        {"page": page_number, "table": table_number, "headers": ", ".join(headers)},
                    )
                )
    return ParsedDocument("pdf", elements)


def _iter_docx_blocks(document):
    """Yield Word paragraphs and tables in their original body order."""
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _heading_level(style_name: str) -> int | None:
    lowered = style_name.lower()
    if not lowered.startswith("heading"):
        return None
    tail = lowered.removeprefix("heading").strip()
    return int(tail) if tail.isdigit() else 1


def _parse_docx(data: bytes) -> ParsedDocument:
    from docx import Document as DocxDocument
    from docx.table import Table

    document = DocxDocument(io.BytesIO(data))
    elements: list[DocumentElement] = []
    heading_path: list[str] = []
    for block in _iter_docx_blocks(document):
        if isinstance(block, Table):
            parsed_table = _rows_to_markdown([[cell.text for cell in row.cells] for row in block.rows])
            if parsed_table is None:
                continue
            table_text, headers = parsed_table
            metadata: dict[str, str | int] = {"headers": ", ".join(headers)}
            if heading_path:
                metadata["heading_path"] = " > ".join(heading_path)
            elements.append(DocumentElement("table", table_text, metadata))
            continue

        text = block.text.strip()
        if not text:
            continue
        level = _heading_level(block.style.name)
        if level is not None:
            heading_path = heading_path[: level - 1] + [text]
            elements.append(DocumentElement("heading", text, {"level": level}))
            continue
        metadata = {"heading_path": " > ".join(heading_path)} if heading_path else {}
        elements.append(DocumentElement("prose", text, metadata))
    image_index = 0
    for part in document.part.related_parts.values():
        if not (part.content_type or "").startswith("image/"):
            continue
        image_index += 1
        try:
            from PIL import Image
            with Image.open(io.BytesIO(part.blob)) as image:
                ocr_text = _ocr_image(image)
        except Exception:
            continue
        if ocr_text:
            elements.append(DocumentElement("prose", ocr_text, {"image": image_index, "source": "ocr"}))
    return ParsedDocument("docx", elements)


def _parse_image(data: bytes) -> ParsedDocument:
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        text = _ocr_image(image)
    return ParsedDocument("image", [DocumentElement("prose", text, {"source": "ocr"})] if text else [])


def _parse_xlsx(data: bytes) -> ParsedDocument:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    elements: list[DocumentElement] = []
    try:
        for sheet in workbook.worksheets:
            rows_with_numbers: list[tuple[int, list[object | None]]] = []
            for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if any(value not in (None, "") for value in row):
                    rows_with_numbers.append((row_number, list(row)))
            if not rows_with_numbers:
                continue
            parsed_table = _rows_to_markdown([row for _, row in rows_with_numbers])
            if parsed_table is None:
                continue
            table_text, headers = parsed_table
            elements.append(
                DocumentElement(
                    "table",
                    table_text,
                    {
                        "sheet": sheet.title,
                        "headers": ", ".join(headers),
                        "row_start": rows_with_numbers[0][0],
                        "row_end": rows_with_numbers[-1][0],
                    },
                )
            )
    finally:
        workbook.close()
    return ParsedDocument("xlsx", elements)


def _parse_csv(data: bytes) -> ParsedDocument:
    rows = list(csv.reader(io.StringIO(data.decode("utf-8"))))
    parsed_table = _rows_to_markdown(rows)
    if parsed_table is None:
        return ParsedDocument("csv", [])
    table_text, headers = parsed_table
    return ParsedDocument("csv", [DocumentElement("table", table_text, {"headers": ", ".join(headers), "row_start": 1, "row_end": len(rows)})])


def _parse_markdown(data: bytes) -> ParsedDocument:
    elements: list[DocumentElement] = []
    prose_lines: list[str] = []
    heading_path: list[str] = []

    def emit_prose() -> None:
        nonlocal prose_lines
        text = "\n".join(prose_lines).strip()
        if text:
            metadata = {"heading_path": " > ".join(heading_path)} if heading_path else {}
            elements.append(DocumentElement("prose", text, metadata))
        prose_lines = []

    for raw_line in data.decode("utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            marker, _, title = stripped.partition(" ")
            level = len(marker)
            if title and marker == "#" * level:
                emit_prose()
                heading_path = heading_path[: level - 1] + [title]
                elements.append(DocumentElement("heading", title, {"level": level}))
                continue
        prose_lines.append(raw_line)
    emit_prose()
    return ParsedDocument("markdown", elements)


def _parse_text(data: bytes) -> ParsedDocument:
    text = data.decode("utf-8").strip()
    return ParsedDocument("text", [DocumentElement("prose", text)] if text else [])


_PARSERS: dict[str, Callable[[bytes], ParsedDocument]] = {
    "pdf": _parse_pdf,
    "docx": _parse_docx,
    "xlsx": _parse_xlsx,
    "csv": _parse_csv,
    "markdown": _parse_markdown,
    "text": _parse_text,
    "image": _parse_image,
}


def parse_document(
    filename: str,
    data: bytes,
    document_type: DetectedDocumentType | None = None,
) -> ParsedDocument:
    """Select a parser from the verified document type and return elements."""
    detected = document_type or validate_uploaded_document(filename, data)
    parser = _PARSERS.get(detected.kind)
    if parser is None:
        raise ValueError(f"No parser is registered for {detected.kind!r}.")
    return parser(data)


def enrich_pdf_image_ocr(document: ParsedDocument, data: bytes) -> ParsedDocument:
    """Read text inside embedded PDF images without generating captions."""
    if document.document_type != "pdf":
        return document
    from pypdf import PdfReader

    elements = list(document.elements)
    seen = {element.text.strip() for element in elements if element.text.strip()}
    reader = PdfReader(io.BytesIO(data))
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            images = list(page.images)
        except Exception:
            images = []
        for image_file in images:
            try:
                image = image_file.image
                if image is None:
                    continue
                text = _ocr_image(image)
            except Exception:
                continue
            if text and text not in seen:
                seen.add(text)
                elements.append(DocumentElement("prose", text, {"page": page_number, "source": "ocr_image"}))
    return ParsedDocument(document.document_type, elements, document.warnings)
