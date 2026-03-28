"""Unit tests for the summarisation pipeline.

Uses mocked Anthropic API calls to test the pipeline logic
without making real API requests.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.chunker import Chunk
from app.services.summariser import (
    SummaryResult,
    _group_by_chapter,
    summarise_document,
)


def _make_chunk(
    index: int,
    text: str = "Some text content.",
    heading_path: list[str] | None = None,
) -> Chunk:
    return Chunk(
        text=text,
        index=index,
        heading_path=heading_path or [f"Chapter {index + 1}"],
        page_start=index * 10 + 1,
        page_end=(index + 1) * 10,
        token_count=50,
    )


class TestGroupByChapter:
    def test_groups_by_first_heading(self):
        chunks = [
            _make_chunk(0, heading_path=["Chapter 1"]),
            _make_chunk(1, heading_path=["Chapter 1"]),
            _make_chunk(2, heading_path=["Chapter 2"]),
        ]
        summaries = ["Sum A", "Sum B", "Sum C"]

        groups = _group_by_chapter(chunks, summaries)

        assert "Chapter 1" in groups
        assert "Chapter 2" in groups
        assert groups["Chapter 1"] == ["Sum A", "Sum B"]
        assert groups["Chapter 2"] == ["Sum C"]

    def test_empty_heading_path(self):
        chunks = [_make_chunk(0, heading_path=[])]
        summaries = ["Sum A"]

        groups = _group_by_chapter(chunks, summaries)
        assert "Untitled" in groups

    def test_single_chunk(self):
        chunks = [_make_chunk(0, heading_path=["Intro"])]
        summaries = ["Summary"]

        groups = _group_by_chapter(chunks, summaries)
        assert groups == {"Intro": ["Summary"]}


class TestSummariseDocument:
    @pytest.fixture
    def mock_client(self):
        """Create a mocked Anthropic async client."""
        mock = AsyncMock()

        # The mock returns a message with content
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Mocked summary response.")]
        mock.messages.create = AsyncMock(return_value=mock_response)

        return mock

    @pytest.mark.asyncio
    async def test_full_pipeline(self, mock_client):
        """Test that the full pipeline runs without error."""
        chunks = [
            _make_chunk(0, text="Content A " * 20, heading_path=["Ch 1"]),
            _make_chunk(1, text="Content B " * 20, heading_path=["Ch 1"]),
            _make_chunk(2, text="Content C " * 20, heading_path=["Ch 2"]),
        ]

        with patch(
            "app.services.summariser._get_client", return_value=mock_client
        ):
            result = await summarise_document(chunks)

        assert isinstance(result, SummaryResult)
        assert result.brief == "Mocked summary response."
        assert result.takeaways == "Mocked summary response."
        assert "Ch 1" in result.chapter_summaries
        assert "Ch 2" in result.chapter_summaries
        assert len(result.chunk_summaries) == 3

    @pytest.mark.asyncio
    async def test_single_chunk(self, mock_client):
        """Pipeline works with just one chunk."""
        chunks = [_make_chunk(0, text="Only chunk.", heading_path=["Only"])]

        with patch(
            "app.services.summariser._get_client", return_value=mock_client
        ):
            result = await summarise_document(chunks)

        assert isinstance(result, SummaryResult)
        assert len(result.chunk_summaries) == 1

    @pytest.mark.asyncio
    async def test_api_called_correct_number_of_times(self, mock_client):
        """Verify the expected number of API calls."""
        chunks = [
            _make_chunk(0, heading_path=["Ch 1"]),
            _make_chunk(1, heading_path=["Ch 2"]),
        ]

        with patch(
            "app.services.summariser._get_client", return_value=mock_client
        ):
            result = await summarise_document(chunks)

        # Expected calls:
        # 2 chunk summaries (map)
        # 0 chapter merges (each chapter has only 1 chunk, so skip merge)
        # 1 takeaways + 1 brief (synthesis)
        # Total = 4
        assert mock_client.messages.create.call_count == 4
