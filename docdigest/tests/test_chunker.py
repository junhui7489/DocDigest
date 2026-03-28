"""Unit tests for the structure-aware chunker."""

import pytest

from app.services.chunker import Chunk, chunk_document, count_tokens
from app.services.parser import Paragraph, ParsedDocument, Section


def _make_document(sections: list[Section]) -> ParsedDocument:
    """Helper to create a ParsedDocument from sections."""
    all_text = " ".join(
        p.text for s in sections for p in s.paragraphs
    )
    return ParsedDocument(
        title="Test Document",
        author="Test Author",
        page_count=10,
        sections=sections,
        raw_text=all_text,
    )


class TestCountTokens:
    def test_empty_string(self):
        assert count_tokens("") == 0

    def test_simple_text(self):
        tokens = count_tokens("Hello, world!")
        assert tokens > 0
        assert tokens < 10

    def test_longer_text(self):
        text = "The quick brown fox jumps over the lazy dog. " * 50
        tokens = count_tokens(text)
        assert tokens > 100


class TestChunkDocument:
    def test_single_short_section(self):
        """A short document should produce a single chunk."""
        sections = [
            Section(
                heading="Introduction",
                level=1,
                paragraphs=[
                    Paragraph(text="This is a short paragraph.", page_number=1),
                ],
            ),
        ]
        doc = _make_document(sections)
        chunks = chunk_document(doc, target_tokens=500, overlap_tokens=50)

        assert len(chunks) == 1
        assert chunks[0].heading_path == ["Introduction"]
        assert chunks[0].page_start == 1
        assert "short paragraph" in chunks[0].text

    def test_long_section_splits(self):
        """A long section should be split into multiple chunks."""
        long_text = "This is a paragraph with some content. " * 100
        paragraphs = [
            Paragraph(text=long_text, page_number=i)
            for i in range(1, 6)
        ]
        sections = [
            Section(heading="Long Chapter", level=1, paragraphs=paragraphs),
        ]
        doc = _make_document(sections)
        chunks = chunk_document(doc, target_tokens=200, overlap_tokens=20)

        assert len(chunks) > 1
        # All chunks should have the heading path
        for chunk in chunks:
            assert chunk.heading_path == ["Long Chapter"]

    def test_preserves_heading_paths(self):
        """Chunks should carry their section's heading path."""
        sections = [
            Section(
                heading="Chapter 1",
                level=1,
                paragraphs=[
                    Paragraph(text="Content of chapter one. " * 20, page_number=1),
                ],
            ),
            Section(
                heading="Chapter 2",
                level=1,
                paragraphs=[
                    Paragraph(text="Content of chapter two. " * 20, page_number=5),
                ],
            ),
        ]
        doc = _make_document(sections)
        chunks = chunk_document(doc, target_tokens=100, overlap_tokens=10)

        headings = {tuple(c.heading_path) for c in chunks}
        assert ("Chapter 1",) in headings
        assert ("Chapter 2",) in headings

    def test_chunk_indices_are_sequential(self):
        """Chunk indices should be 0, 1, 2, ..."""
        sections = [
            Section(
                heading="Content",
                level=1,
                paragraphs=[
                    Paragraph(text=f"Paragraph {i}. " * 30, page_number=i)
                    for i in range(10)
                ],
            ),
        ]
        doc = _make_document(sections)
        chunks = chunk_document(doc, target_tokens=200, overlap_tokens=20)

        for i, chunk in enumerate(chunks):
            assert chunk.index == i

    def test_content_hash_is_deterministic(self):
        """Same text should produce the same content hash."""
        sections = [
            Section(
                heading="Test",
                level=1,
                paragraphs=[Paragraph(text="Deterministic content.")],
            ),
        ]
        doc = _make_document(sections)
        chunks_a = chunk_document(doc, target_tokens=500)
        chunks_b = chunk_document(doc, target_tokens=500)

        assert chunks_a[0].content_hash == chunks_b[0].content_hash

    def test_empty_document(self):
        """An empty document should produce no chunks."""
        doc = _make_document([])
        chunks = chunk_document(doc, target_tokens=500)
        assert len(chunks) == 0
