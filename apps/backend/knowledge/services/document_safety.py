"""Small, dependency-free safety gate for uploaded RAG documents.

This is intentionally before parsing: a filename and a browser ``accept``
attribute are hints, not proof of the bytes a server received.  The parser can
only be called after this module has established that an upload is one of the
formats the product currently supports and that an OOXML archive is bounded.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
import io
import zipfile
from xml.etree import ElementTree

from knowledge.config import get_knowledge_settings


class DocumentUploadError(ValueError):
    """A user-safe reason an uploaded document must not be parsed."""


@dataclass(frozen=True)
class UploadLimits:
    max_upload_bytes: int
    max_office_members: int
    max_office_uncompressed_bytes: int
    max_office_compression_ratio: int


@dataclass(frozen=True)
class DetectedDocumentType:
    kind: str
    mime_type: str


_TEXT_TYPES = {
    ".txt": DetectedDocumentType("text", "text/plain"),
    ".md": DetectedDocumentType("markdown", "text/markdown"),
    ".csv": DetectedDocumentType("csv", "text/csv"),
}
_IMAGE_TYPES = {
    ".jpg": DetectedDocumentType("image", "image/jpeg"),
    ".jpeg": DetectedDocumentType("image", "image/jpeg"),
    ".png": DetectedDocumentType("image", "image/png"),
}
_OFFICE_TYPES = {
    ".docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "word/document.xml"),
    ".xlsx": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xl/workbook.xml"),
}

_OLE_COMPOUND_FILE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_OFFICE_MACRO_MEMBER = "vbaproject.bin"
_OFFICE_EMBEDDED_MEMBER_PREFIXES = ("word/embeddings/", "xl/embeddings/")
_OFFICE_ACTIVE_MEMBER_PREFIXES = ("word/activex/", "xl/activex/")
_OFFICE_EXTERNAL_MEMBER_PREFIXES = ("xl/externallinks/",)
_OFFICE_EXTERNAL_MEMBERS = {"xl/connections.xml"}


def upload_limits() -> UploadLimits:
    settings = get_knowledge_settings()
    return UploadLimits(
        max_upload_bytes=settings.RAG_MAX_UPLOAD_BYTES,
        max_office_members=settings.RAG_MAX_OFFICE_ARCHIVE_MEMBERS,
        max_office_uncompressed_bytes=settings.RAG_MAX_OFFICE_UNCOMPRESSED_BYTES,
        max_office_compression_ratio=settings.RAG_MAX_OFFICE_COMPRESSION_RATIO,
    )


def _reject_unsafe_office_members(members: list[zipfile.ZipInfo]) -> None:
    """Reject active Office features without extracting or executing them."""
    for member in members:
        name = member.filename.lower()
        if PurePath(name).name == _OFFICE_MACRO_MEMBER:
            raise DocumentUploadError("Upload blocked: macro-enabled Office content is not allowed.")
        if name.startswith(_OFFICE_EMBEDDED_MEMBER_PREFIXES):
            raise DocumentUploadError("Upload blocked: embedded Office objects are not allowed.")
        if name.startswith(_OFFICE_ACTIVE_MEMBER_PREFIXES):
            raise DocumentUploadError("Upload blocked: active Office controls are not allowed.")
        if name.startswith(_OFFICE_EXTERNAL_MEMBER_PREFIXES) or name in _OFFICE_EXTERNAL_MEMBERS:
            raise DocumentUploadError("Upload blocked: external Office references are not allowed.")


def _reject_external_office_relationships(archive: zipfile.ZipFile, members: list[zipfile.ZipInfo]) -> None:
    """Reject OOXML relationships that instruct clients to resolve external targets.

    Relationship files are small XML metadata parts. Reading only these parts
    keeps the inspection static and avoids following any URL or network path.
    """
    for member in members:
        if not member.filename.lower().endswith(".rels"):
            continue
        try:
            root = ElementTree.fromstring(archive.read(member))
        except (ElementTree.ParseError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
            raise DocumentUploadError("The Office document contains invalid relationship metadata.") from exc
        for relationship in root:
            target_mode = relationship.attrib.get("TargetMode", "").lower()
            if target_mode == "external":
                raise DocumentUploadError("Upload blocked: external Office references are not allowed.")


def _validate_office_archive(data: bytes, expected_member: str, limits: UploadLimits) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > limits.max_office_members:
                raise DocumentUploadError("The Office document contains too many files to process safely.")

            total_uncompressed = 0
            found_expected_member = False
            for member in members:
                # OOXML is a ZIP archive. Reject path traversal, encrypted entries and
                # compressed archives whose expanded size is beyond our parser budget.
                path = PurePath(member.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise DocumentUploadError("The Office document contains an unsafe archive path.")
                if member.flag_bits & 0x1:
                    raise DocumentUploadError("Password-protected Office documents are not supported.")
                total_uncompressed += member.file_size
                if total_uncompressed > limits.max_office_uncompressed_bytes:
                    raise DocumentUploadError("The Office document expands beyond the processing limit.")
                if member.compress_size > 0 and member.file_size / member.compress_size > limits.max_office_compression_ratio:
                    raise DocumentUploadError("The Office document has an unsafe compression ratio.")
                if member.filename == expected_member:
                    found_expected_member = True

            if not found_expected_member:
                raise DocumentUploadError("The file contents do not match its Office document type.")

            _reject_unsafe_office_members(members)
            _reject_external_office_relationships(archive, members)
    except zipfile.BadZipFile as exc:
        raise DocumentUploadError("The file is not a valid Office document.") from exc


def _reject_unsafe_pdf_features(data: bytes) -> None:
    """Reject encrypted and active PDF features without rendering the PDF.

    This is static screening, not malware detection. The bounded object walk
    catches JavaScript and launch actions even when they are not referenced by
    the document catalog directly.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # Deployment error, not an unsafe upload.
        raise RuntimeError("PDF safety screening requires pypdf.") from exc

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise DocumentUploadError("Password-protected PDF documents are not supported.")
        root = reader.trailer["/Root"]
    except DocumentUploadError:
        raise
    except Exception as exc:
        raise DocumentUploadError("The file is not a readable PDF document.") from exc

    visited: set[int] = set()

    def inspect(value: object, depth: int = 0) -> None:
        # A depth/node limit prevents pathological object graphs from turning
        # static screening itself into an unbounded parser workload.
        if depth > 25 or len(visited) > 20_000:
            raise DocumentUploadError("The PDF structure is too complex to process safely.")
        try:
            resolved = value.get_object() if hasattr(value, "get_object") else value
        except Exception as exc:
            raise DocumentUploadError("The PDF contains an unreadable object.") from exc
        identity = id(resolved)
        if identity in visited:
            return
        visited.add(identity)

        if isinstance(resolved, dict):
            action = str(resolved.get("/S", ""))
            if action in {"/JavaScript", "/Launch"}:
                raise DocumentUploadError("Upload blocked: active PDF actions are not allowed.")
            if "/OpenAction" in resolved or "/AA" in resolved:
                raise DocumentUploadError("Upload blocked: automatic PDF actions are not allowed.")
            if "/JavaScript" in resolved or "/EmbeddedFiles" in resolved:
                raise DocumentUploadError("Upload blocked: PDF JavaScript or embedded files are not allowed.")
            for child in resolved.values():
                inspect(child, depth + 1)
        elif isinstance(resolved, (list, tuple)):
            for child in resolved:
                inspect(child, depth + 1)

    inspect(root)


def validate_uploaded_document(
    filename: str | None,
    data: bytes,
    *,
    limits: UploadLimits | None = None,
) -> DetectedDocumentType:
    """Validate supported upload bytes and return the verified document type.

    Current product scope intentionally matches the Knowledge Bases browser
    picker: PDF, DOCX, XLSX, CSV, Markdown, and plain text. More formats can
    be added through a parser adapter after they have fixtures and limits.
    """
    active_limits = limits or upload_limits()
    suffix = PurePath(filename or "").suffix.lower()

    if not filename or not suffix:
        raise DocumentUploadError("Choose a file with a supported extension.")
    if not data:
        raise DocumentUploadError("The uploaded file is empty.")
    if len(data) > active_limits.max_upload_bytes:
        raise DocumentUploadError("The uploaded file exceeds the size limit.")

    if suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise DocumentUploadError("The file contents do not match a PDF document.")
        _reject_unsafe_pdf_features(data)
        return DetectedDocumentType("pdf", "application/pdf")

    if suffix in _OFFICE_TYPES:
        kind, mime_type, expected_member = _OFFICE_TYPES[suffix]
        if data.startswith(_OLE_COMPOUND_FILE_HEADER):
            raise DocumentUploadError("Password-protected Office documents are not supported.")
        if not data.startswith(b"PK\x03\x04"):
            raise DocumentUploadError("The file contents do not match an Office document.")
        _validate_office_archive(data, expected_member, active_limits)
        return DetectedDocumentType(kind, mime_type)

    image_type = _IMAGE_TYPES.get(suffix)
    if image_type is not None:
        try:
            from PIL import Image
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"JPEG", "PNG"}:
                    raise DocumentUploadError("The file contents do not match its image type.")
                if image.width * image.height > 40_000_000:
                    raise DocumentUploadError("The image has too many pixels to process safely.")
        except DocumentUploadError:
            raise
        except Exception as exc:
            raise DocumentUploadError("The file is not a readable JPG or PNG image.") from exc
        return image_type

    text_type = _TEXT_TYPES.get(suffix)
    if text_type is not None:
        if b"\x00" in data:
            raise DocumentUploadError("The file appears to be binary, not a text document.")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentUploadError("Text uploads must be UTF-8 encoded.") from exc
        return text_type

    allowed = "PDF, DOCX, XLSX, CSV, Markdown, text, JPG, or PNG"
    raise DocumentUploadError(f"Unsupported document type. Upload {allowed}.")
