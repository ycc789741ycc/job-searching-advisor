"""Turning an uploaded resume into Evidence.

Runs in the worker only, never in a request handler, under size, page-count
and time limits. The file is untrusted: a PDF is an execution format, and a
resume is a document a stranger uploaded (docs/technical_boundaries.md
section 4).

No LLM is involved here. The text is split into traceable lines so every claim
the assessment later makes can point at a specific part of the document.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from advisor.profile._infra.connectors.base import EvidenceDraft
from kernel.errors import ValidationError

PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ACCEPTED_TYPES = frozenset({PDF_TYPE, DOCX_TYPE, "text/plain"})

# A resume line shorter than this is a heading or a stray token, not a claim.
_MIN_LINE_LENGTH = 24
_MAX_LINES = 120
_BULLET = re.compile(r"^[\s\-•●▪*+]+")


@dataclass(frozen=True, slots=True)
class ParsedResume:
    text: str
    page_count: int
    drafts: list[EvidenceDraft]


def parse(content: bytes, *, content_type: str, filename: str, max_pages: int) -> ParsedResume:
    if content_type not in ACCEPTED_TYPES:
        raise ValidationError(
            f"{content_type} is not a resume format we can read", content_type=content_type
        )

    if content_type == PDF_TYPE:
        text, pages = _read_pdf(content, max_pages=max_pages)
    elif content_type == DOCX_TYPE:
        text, pages = _read_docx(content)
    else:
        text, pages = content.decode("utf-8", errors="replace"), 1

    if not text.strip():
        raise ValidationError("no text could be read from this file", filename=filename)

    return ParsedResume(text=text, page_count=pages, drafts=_to_drafts(text, filename))


def _read_pdf(content: bytes, *, max_pages: int) -> tuple[str, int]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:
        raise ValidationError("this PDF could not be opened") from exc

    if len(reader.pages) > max_pages:
        raise ValidationError(
            f"a resume of more than {max_pages} pages is not accepted",
            pages=len(reader.pages),
        )
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages), len(pages)


def _read_docx(content: bytes) -> tuple[str, int]:
    from docx import Document

    try:
        document = Document(io.BytesIO(content))
    except Exception as exc:
        raise ValidationError("this Word document could not be opened") from exc
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    return "\n".join(paragraphs), 1


def _to_drafts(text: str, filename: str) -> list[EvidenceDraft]:
    """One draft per substantive line, each pointing back at where it came from."""
    drafts: list[EvidenceDraft] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = _BULLET.sub("", raw).strip()
        if len(line) < _MIN_LINE_LENGTH:
            continue
        drafts.append(
            EvidenceDraft(
                external_ref=f"resume:{filename}:{number}",
                reference=f"Resume · {filename} · line {number}",
                fact=line,
                observed_on=None,
                # Self-authored, so it is weaker evidence than a merged PR.
                confidence=0.6,
            )
        )
        if len(drafts) >= _MAX_LINES:
            break
    return drafts
