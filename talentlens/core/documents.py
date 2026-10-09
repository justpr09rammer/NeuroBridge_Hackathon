"""PDF validation and text extraction (PyMuPDF).

Text that is invisible to a human reader (white text, near-zero font size) is
*not* included in the evidence text. It is stored separately and flagged,
because evidence a recruiter cannot see must never support a match.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from talentlens import config


class DocumentError(ValueError):
    """Raised for files that cannot be accepted (wrong type, too large, corrupt)."""


@dataclass
class ExtractedDocument:
    filename: str
    size_bytes: int
    page_count: int
    pages: list[str]
    hidden_text: list[dict] = field(default_factory=list)
    readability: str = "ok"
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.pages)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def safe_filename(name: str) -> str:
    base = Path(name).name  # strips directories
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip() or "document.pdf"
    return base[:150]


def validate_upload(filename: str, data: bytes) -> None:
    ext = Path(filename).suffix.lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise DocumentError(f"Unsupported file type '{ext or 'none'}'. Only PDF files are accepted.")
    if len(data) == 0:
        raise DocumentError("The file is empty.")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise DocumentError(
            f"File is {len(data) / 1_048_576:.1f} MB; the limit is {config.MAX_UPLOAD_BYTES // 1_048_576} MB."
        )
    if not data.lstrip()[:5].startswith(b"%PDF"):
        raise DocumentError("The file does not look like a valid PDF (missing PDF header).")


def _is_hidden(span: dict, page_bg_white: bool = True) -> bool:
    color = span.get("color", 0)
    size = span.get("size", 10)
    near_white = color >= 0xF0F0F0 if page_bg_white else False
    return near_white or size < 2.0


def _assess_readability(text: str) -> tuple[str, list[str]]:
    stripped = text.strip()
    warnings: list[str] = []
    if not stripped:
        return "unreadable", ["No extractable text. The PDF may be a scanned image; OCR is not included in this MVP."]
    printable = sum(ch.isprintable() or ch in "\n\t" for ch in stripped) / max(len(stripped), 1)
    letters = sum(ch.isalpha() for ch in stripped) / max(len(stripped), 1)
    if printable < 0.9 or letters < 0.4:
        return "unreadable", ["Extracted text looks garbled (encoding problem). Manual inspection needed."]
    if len(stripped) < config.MIN_READABLE_CHARS:
        warnings.append(f"Only {len(stripped)} characters extracted; the CV may be incomplete.")
        return "too_short", warnings
    return "ok", warnings


def extract_pdf(filename: str, data: bytes) -> ExtractedDocument:
    """Validate and extract visible text page by page."""
    validate_upload(filename, data)
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # corrupt file
        raise DocumentError(f"Could not open PDF: {exc.__class__.__name__}") from exc
    if doc.needs_pass:
        doc.close()
        raise DocumentError("The PDF is password-protected.")

    pages: list[str] = []
    hidden: list[dict] = []
    try:
        for pno, page in enumerate(doc, start=1):
            info = page.get_text("dict")
            out_lines: list[str] = []
            for block in info.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    visible_parts: list[str] = []
                    for span in line.get("spans", []):
                        txt = span.get("text", "")
                        if not txt.strip():
                            visible_parts.append(txt)
                            continue
                        if _is_hidden(span):
                            hidden.append({"page": pno, "text": txt.strip()[:300], "size": round(span.get("size", 0), 1)})
                        else:
                            visible_parts.append(txt)
                    joined = "".join(visible_parts).rstrip()
                    if joined.strip():
                        out_lines.append(joined)
            pages.append("\n".join(out_lines))
        page_count = doc.page_count
    finally:
        doc.close()

    text = "\n".join(pages)
    readability, warnings = _assess_readability(text)
    if hidden:
        warnings.append(f"{len(hidden)} hidden text fragment(s) found (white or microscopic text). Excluded from evidence.")
    return ExtractedDocument(
        filename=safe_filename(filename),
        size_bytes=len(data),
        page_count=page_count,
        pages=pages,
        hidden_text=hidden,
        readability=readability,
        warnings=warnings,
    )


def document_from_text(filename: str, text: str) -> ExtractedDocument:
    """Build an ExtractedDocument from plain text (tests and evaluation)."""
    pages = text.split("\f") if "\f" in text else [text]
    readability, warnings = _assess_readability(text)
    return ExtractedDocument(
        filename=safe_filename(filename), size_bytes=len(text.encode()), page_count=len(pages),
        pages=pages, readability=readability, warnings=warnings,
    )


def render_pdf(lines: list[str], hidden_lines: list[str] | None = None) -> bytes:
    """Render a simple single-column CV PDF (used for synthetic demo data)."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 56
    for raw in lines:
        is_header = raw.startswith("## ")
        is_title = raw.startswith("# ")
        # Base-14 PDF fonts lack some Unicode glyphs; keep the synthetic PDFs plain ASCII-friendly.
        txt = raw.lstrip("# ").rstrip().replace("–", "-").replace("—", "-").replace("’", "'")
        size = 16 if is_title else 11.5 if is_header else 9.5
        font = "hebo" if (is_header or is_title) else "helv"
        wrapped = _wrap(txt, 95 if size < 10 else 70)
        for w in wrapped or [""]:
            if y > 800:
                page = doc.new_page(width=595, height=842)
                y = 56
            page.insert_text((50, y), w, fontsize=size, fontname=font, color=(0.08, 0.1, 0.2))
            y += size + 5
        if is_header or is_title:
            y += 3
    for h in hidden_lines or []:
        page.insert_text((50, 830), h, fontsize=6, fontname="helv", color=(1, 1, 1))
    data = doc.tobytes()
    doc.close()
    return data


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines
