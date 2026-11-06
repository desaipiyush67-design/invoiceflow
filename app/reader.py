"""Turn an uploaded file into text. Digital PDFs use their text layer; scans and photos go through OCR."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

MIN_TEXT_CHARS = 40  # fewer characters than this on the text layer means the PDF is a scanned image
_ocr = None


@dataclass
class ReadResult:
    text: str
    method: str                 # "text-layer" | "ocr"
    pages: int
    sha256: str
    ocr_confidence: float | None = None
    notes: list[str] = field(default_factory=list)


def _ocr_engine():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR  # ONNX models, runs on CPU, no system install
        _ocr = RapidOCR()
    return _ocr


def _ocr_image(png: bytes) -> tuple[str, list[float]]:
    result, _ = _ocr_engine()(png)
    if not result:
        return "", []
    # result: [[box, text, score], ...]. Rebuild reading order: group boxes into rows by their vertical centre.
    items = sorted(((sum(p[1] for p in box) / 4, box[0][0], text, score) for box, text, score in result))
    rows, current, last_y = [], [], None
    for y, x, text, score in items:
        if last_y is not None and abs(y - last_y) > 12:
            rows.append(current)
            current = []
        current.append((x, text, score))
        last_y = y
    if current:
        rows.append(current)
    lines = ["  ".join(t for _, t, _ in sorted(r)) for r in rows]
    return "\n".join(lines), [float(s) for *_, s in items]


def _page_rows(page) -> str:
    """Text layer rebuilt as visual rows: table cells on the same line stay on the same line."""
    words = sorted(page.get_text("words"), key=lambda w: (round(w[3]), w[0]))
    rows, current, last_y = [], [], None
    for x0, y0, x1, y1, word, *_ in words:
        if last_y is not None and abs(y1 - last_y) > 3:
            rows.append(current)
            current = []
        current.append((x0, x1, word))
        last_y = y1
    if current:
        rows.append(current)
    out = []
    for r in rows:
        r.sort()
        line, prev_x1 = "", None
        for x0, x1, w in r:
            line += ("" if prev_x1 is None else ("  " if x0 - prev_x1 > 12 else " ")) + w
            prev_x1 = x1
        out.append(line)
    return "\n".join(out)


def read_document(path: Path) -> ReadResult:
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    suffix = path.suffix.lower()

    if suffix in {".png", ".jpg", ".jpeg"}:
        text, scores = _ocr_image(data)
        return ReadResult(text, "ocr", 1, sha, round(sum(scores) / len(scores), 3) if scores else 0.0)

    doc = pymupdf.open(stream=data, filetype="pdf")
    text = "\n".join(_page_rows(page) for page in doc)
    if len(text.strip()) >= MIN_TEXT_CHARS:
        return ReadResult(text, "text-layer", doc.page_count, sha)

    parts, scores = [], []
    for page in doc:
        png = page.get_pixmap(dpi=200).tobytes("png")
        t, s = _ocr_image(png)
        parts.append(t)
        scores += s
    conf = round(sum(scores) / len(scores), 3) if scores else 0.0
    notes = ["No text layer - the PDF is a scanned image, read with OCR."]
    if conf < 0.85:
        notes.append(f"Low OCR confidence ({conf:.0%}); numbers are cross-checked before deciding.")
    return ReadResult("\n".join(parts), "ocr", doc.page_count, sha, conf, notes)
