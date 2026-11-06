"""Turn an uploaded file into page images (for the vision model) plus any embedded text layer."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

MIN_TEXT_CHARS = 40   # fewer characters than this means the PDF is a scanned image
MAX_PAGES = 3
DPI = 150


@dataclass
class Document:
    images: list[bytes]          # PNG per page
    text: str                    # text layer, empty for scans and photos
    kind: str                    # "digital-pdf" | "scanned-pdf" | "image"
    pages: int
    sha256: str
    notes: list[str] = field(default_factory=list)


def read_document(path: Path) -> Document:
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        png = pymupdf.Pixmap(data).tobytes("png")
        return Document([png], "", "image", 1, sha, ["Photo or image upload: the AI reads it visually."])

    doc = pymupdf.open(stream=data, filetype="pdf")
    pages = list(doc)[:MAX_PAGES]
    images = [p.get_pixmap(dpi=DPI).tobytes("png") for p in pages]
    text = "\n".join(p.get_text("text") for p in pages).strip()
    notes = [] if doc.page_count <= MAX_PAGES else [f"Only the first {MAX_PAGES} of {doc.page_count} pages were read."]
    if len(text) < MIN_TEXT_CHARS:
        return Document(images, "", "scanned-pdf", doc.page_count, sha, notes + ["No text layer: a scanned image, read visually by the AI."])
    return Document(images, text, "digital-pdf", doc.page_count, sha, notes)
