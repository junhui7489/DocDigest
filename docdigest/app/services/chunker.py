"""Structure-aware document chunking.

Splits parsed documents into semantically coherent chunks that respect
structural boundaries (chapters, sections, paragraphs) and maintain
heading-path context for each chunk.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

import tiktoken

from app.config import settings
from app.services.parser import ParsedDocument, Section

logger = logging.getLogger(__name__)

# Use cl100k_base (GPT-4 / Claude-compatible tokeniser) for counting
_ENCODER = tiktoken.get_encoding("cl100k_base")


@dataclass
class Chunk:
    """A single chunk of text with structural metadata."""
    text: str
    index: int
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    token_count: int
    content_hash: str = ""

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = hashlib.sha256(
                self.text.encode("utf-8")
            ).hexdigest()


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken."""
    return len(_ENCODER.encode(text))


def chunk_document(
    parsed: ParsedDocument,
    target_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[Chunk]:
    """Split a parsed document into chunks.

    Strategy:
    1. Walk the document's section tree depth-first.
    2. Accumulate paragraph text until reaching `target_tokens`.
    3. Prefer to split at paragraph boundaries.
    4. Add overlap from the end of the previous chunk for continuity.
    5. Tag each chunk with its heading path for structural context.
    """
    target = target_tokens or settings.chunk_target_tokens
    overlap = overlap_tokens or settings.chunk_overlap_tokens

    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_tokens = 0
    buffer_pages: list[int] = []
    current_path: list[str] = []

    def _flush():
        nonlocal buffer, buffer_tokens, buffer_pages
        if not buffer:
            return
        text = "\n\n".join(buffer)
        chunks.append(Chunk(
            text=text,
            index=len(chunks),
            heading_path=list(current_path),
            page_start=min(buffer_pages) if buffer_pages else None,
            page_end=max(buffer_pages) if buffer_pages else None,
            token_count=buffer_tokens,
        ))
        # Keep overlap text from the end
        overlap_buf = _get_overlap_text(buffer, overlap)
        buffer = overlap_buf
        buffer_tokens = count_tokens("\n\n".join(buffer)) if buffer else 0
        buffer_pages = buffer_pages[-1:] if buffer_pages else []

    def _walk(section: Section, path: list[str]):
        nonlocal buffer, buffer_tokens, buffer_pages, current_path

        new_path = path + [section.heading]
        current_path = new_path

        for para in section.paragraphs:
            para_tokens = count_tokens(para.text)

            if buffer_tokens + para_tokens > target and buffer_tokens > 0:
                _flush()
                current_path = new_path

            buffer.append(para.text)
            buffer_tokens += para_tokens
            if para.page_number is not None:
                buffer_pages.append(para.page_number)

        for child in section.children:
            _walk(child, new_path)

    for section in parsed.sections:
        _walk(section, [])

    _flush()

    logger.info(
        "Chunked document into %d chunks (target=%d, overlap=%d)",
        len(chunks), target, overlap,
    )
    return chunks


def _get_overlap_text(paragraphs: list[str], max_overlap_tokens: int) -> list[str]:
    """Extract trailing paragraphs that fit within the overlap budget."""
    result: list[str] = []
    total = 0
    for para in reversed(paragraphs):
        tokens = count_tokens(para)
        if total + tokens > max_overlap_tokens:
            break
        result.insert(0, para)
        total += tokens
    return result
