"""Hierarchical map-reduce summarisation using the Anthropic Claude API.

Pipeline:
1. MAP: Summarise each chunk independently (using Sonnet for speed/cost).
2. GROUP: Group chunk summaries by chapter / top-level heading.
3. REDUCE: Merge grouped summaries into chapter summaries (using Opus).
4. SYNTHESISE: Merge chapter summaries into key takeaways and executive brief.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import anthropic

from app.config import settings
from app.services.chunker import Chunk

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

CHUNK_SYSTEM = """You are a document analyst producing concise, accurate summaries.

Rules:
- Preserve key facts, arguments, data points, and conclusions.
- Use the section context (heading path) to understand what part of the document this is.
- Be concise but do not omit important details.
- Write in clear, professional prose.
- Do NOT add information that is not present in the source text."""

MERGE_SYSTEM = """You are a document analyst synthesising multiple section summaries into \
a single coherent summary.

Rules:
- Organise by theme, not by the order the summaries were given.
- Eliminate redundancy across sections.
- Preserve all key facts, arguments, and conclusions.
- Write in clear, professional prose with logical flow.
- Do NOT add information not present in the source summaries."""

BRIEF_SYSTEM = """You are a document analyst producing a concise executive brief.

Rules:
- Condense the entire document into ONE paragraph of roughly 100-150 words.
- Focus on: what is the document about, what are the main conclusions, and why it matters.
- Write for a busy professional who has 30 seconds to read this.
- Do NOT add information not present in the source summaries."""

TAKEAWAYS_SYSTEM = """You are a document analyst extracting key takeaways.

Rules:
- Produce 5-8 key takeaways as a numbered list.
- Each takeaway should be 1-2 sentences — specific and actionable where possible.
- Cover the most important insights from across the entire document.
- Order by importance, not by position in the document.
- Do NOT add information not present in the source summaries."""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SummaryResult:
    """Result from the summarisation pipeline."""
    brief: str                          # ~150 words
    takeaways: str                      # 5-8 bullet points
    chapter_summaries: dict[str, str]   # heading → summary
    section_summaries: dict[str, str]   # heading → summary
    chunk_summaries: list[str]          # per-chunk summaries


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

async def summarise_document(chunks: list[Chunk]) -> SummaryResult:
    """Run the full hierarchical summarisation pipeline.

    Args:
        chunks: Ordered list of document chunks with heading paths.

    Returns:
        A SummaryResult with summaries at every level.
    """
    client = _get_client()

    # ---- Step 1: MAP — Summarise each chunk (parallel, Sonnet) ----
    logger.info("Step 1/4: Summarising %d chunks...", len(chunks))
    chunk_summaries = await _map_chunks(client, chunks)

    # ---- Step 2: GROUP — Organise by chapter heading ----
    logger.info("Step 2/4: Grouping by chapter...")
    chapter_groups = _group_by_chapter(chunks, chunk_summaries)

    # ---- Step 3: REDUCE — Merge into chapter summaries (Opus) ----
    logger.info("Step 3/4: Generating chapter summaries...")
    chapter_summaries = await _reduce_chapters(client, chapter_groups)

    # ---- Step 4: SYNTHESISE — Generate takeaways and brief ----
    logger.info("Step 4/4: Generating executive brief and takeaways...")
    all_chapter_text = "\n\n---\n\n".join(
        f"## {heading}\n{summary}"
        for heading, summary in chapter_summaries.items()
    )

    takeaways, brief = await asyncio.gather(
        _generate_takeaways(client, all_chapter_text),
        _generate_brief(client, all_chapter_text),
    )

    # Section summaries = chunk summaries tagged by heading path
    section_summaries = {}
    for chunk, summary in zip(chunks, chunk_summaries):
        key = " > ".join(chunk.heading_path) if chunk.heading_path else f"Chunk {chunk.index}"
        section_summaries[key] = summary

    logger.info("Summarisation complete.")
    return SummaryResult(
        brief=brief,
        takeaways=takeaways,
        chapter_summaries=chapter_summaries,
        section_summaries=section_summaries,
        chunk_summaries=chunk_summaries,
    )


# ---------------------------------------------------------------------------
# Step 1: Map — individual chunk summaries
# ---------------------------------------------------------------------------

async def _map_chunks(
    client: anthropic.AsyncAnthropic,
    chunks: list[Chunk],
    concurrency: int = 10,
) -> list[str]:
    """Summarise each chunk in parallel with bounded concurrency."""
    semaphore = asyncio.Semaphore(concurrency)
    results: list[str | None] = [None] * len(chunks)

    async def _summarise_one(idx: int, chunk: Chunk):
        async with semaphore:
            results[idx] = await _call_llm(
                client=client,
                model=settings.summary_model,
                system=CHUNK_SYSTEM,
                user_message=(
                    f"Document section: {' > '.join(chunk.heading_path)}\n"
                    f"Pages: {chunk.page_start or '?'}-{chunk.page_end or '?'}\n\n"
                    f"{chunk.text}"
                ),
                max_tokens=600,
            )

    await asyncio.gather(*[
        _summarise_one(i, c) for i, c in enumerate(chunks)
    ])

    return [r or "[Summary unavailable]" for r in results]


# ---------------------------------------------------------------------------
# Step 2: Group chunk summaries by chapter
# ---------------------------------------------------------------------------

def _group_by_chapter(
    chunks: list[Chunk],
    summaries: list[str],
) -> dict[str, list[str]]:
    """Group chunk summaries under their top-level heading (chapter)."""
    groups: dict[str, list[str]] = {}
    for chunk, summary in zip(chunks, summaries):
        chapter = chunk.heading_path[0] if chunk.heading_path else "Untitled"
        groups.setdefault(chapter, []).append(summary)
    return groups


# ---------------------------------------------------------------------------
# Step 3: Reduce — merge into chapter summaries
# ---------------------------------------------------------------------------

async def _reduce_chapters(
    client: anthropic.AsyncAnthropic,
    groups: dict[str, list[str]],
) -> dict[str, str]:
    """Merge each chapter's chunk summaries into a single chapter summary."""
    results: dict[str, str] = {}

    async def _merge_one(heading: str, summaries: list[str]):
        if len(summaries) == 1:
            results[heading] = summaries[0]
            return

        combined = "\n\n---\n\n".join(
            f"[Section summary {i + 1}]\n{s}"
            for i, s in enumerate(summaries)
        )
        results[heading] = await _call_llm(
            client=client,
            model=settings.synthesis_model,
            system=MERGE_SYSTEM,
            user_message=(
                f"Chapter: {heading}\n\n"
                f"Merge these {len(summaries)} section summaries "
                f"into a single coherent chapter summary:\n\n{combined}"
            ),
            max_tokens=1500,
        )

    await asyncio.gather(*[
        _merge_one(h, sums) for h, sums in groups.items()
    ])

    return results


# ---------------------------------------------------------------------------
# Step 4: Synthesise — brief and takeaways
# ---------------------------------------------------------------------------

async def _generate_brief(
    client: anthropic.AsyncAnthropic,
    chapter_text: str,
) -> str:
    return await _call_llm(
        client=client,
        model=settings.synthesis_model,
        system=BRIEF_SYSTEM,
        user_message=(
            f"Generate an executive brief (one paragraph, ~150 words) "
            f"for the following document:\n\n{chapter_text}"
        ),
        max_tokens=500,
    )


async def _generate_takeaways(
    client: anthropic.AsyncAnthropic,
    chapter_text: str,
) -> str:
    return await _call_llm(
        client=client,
        model=settings.synthesis_model,
        system=TAKEAWAYS_SYSTEM,
        user_message=(
            f"Extract 5-8 key takeaways from the following document:\n\n"
            f"{chapter_text}"
        ),
        max_tokens=1000,
    )


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------

async def _call_llm(
    client: anthropic.AsyncAnthropic,
    model: str,
    system: str,
    user_message: str,
    max_tokens: int = 1000,
    max_retries: int = 3,
) -> str:
    """Call the Anthropic API with retry logic."""
    for attempt in range(1, max_retries + 1):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text
        except anthropic.RateLimitError:
            wait = 2 ** attempt
            logger.warning(
                "Rate limited (attempt %d/%d). Retrying in %ds...",
                attempt, max_retries, wait,
            )
            await asyncio.sleep(wait)
        except Exception as e:
            logger.error("LLM call failed (attempt %d/%d): %s", attempt, max_retries, e)
            if attempt == max_retries:
                return f"[Summary generation failed: {e}]"
            await asyncio.sleep(1)

    return "[Summary generation failed after retries]"


# ---------------------------------------------------------------------------
# Streaming summary generation (for real-time delivery to frontend)
# ---------------------------------------------------------------------------

async def stream_summary_text(
    text: str,
    level: str = "brief",
) -> AsyncGenerator[str, None]:
    """Stream a re-generation of a summary for real-time delivery.

    Takes the already-stored summary text and re-generates it via Claude
    with streaming enabled so the frontend can display it token by token.

    For pre-computed summaries that are already in the database, we stream
    the stored text directly (no API call needed) — this is much faster
    and doesn't cost extra tokens.

    Yields SSE-formatted strings:
      event: delta    — data: {"text": "partial text"}
      event: meta     — data: {"level": "brief", ...}
      event: done     — data: {}
    """
    import json

    # Send metadata first
    yield f"event: meta\ndata: {json.dumps({'level': level})}\n\n"

    # Stream the pre-computed text in small chunks to simulate real-time
    # delivery. This gives the same visual effect as LLM streaming but
    # is instant and free. Chunk size balances smoothness vs overhead.
    chunk_size = 8  # characters per tick
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        yield f"event: delta\ndata: {json.dumps({'text': chunk})}\n\n"
        # Small delay for natural reading feel (40ms ≈ fast typing speed)
        await asyncio.sleep(0.04)

    yield "event: done\ndata: {}\n\n"


from collections.abc import AsyncGenerator
