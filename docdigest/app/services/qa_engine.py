"""RAG-based follow-up Q&A engine.

Retrieves the most relevant chunks via vector similarity search,
then sends them as context to Claude for a grounded answer with citations.

Supports both batch (answer_question) and streaming (answer_question_stream)
response modes.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from uuid import UUID

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.schemas import Chunk as ChunkModel
from app.services.embedder import embed_query

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


QA_SYSTEM = """You are a document analysis assistant answering questions about a specific document.

Rules:
- Answer ONLY based on the provided context passages.
- Cite page numbers in square brackets, e.g. [p.42] or [pp.42-45].
- If the context does not contain enough information to answer, say so explicitly.
- Be concise, accurate, and direct.
- Do NOT make up information or draw from external knowledge."""


async def _retrieve_context(
    db: AsyncSession,
    document_id: UUID,
    question: str,
    top_k: int,
) -> tuple[str, list[dict]]:
    """Shared retrieval step: embed question, fetch chunks, build context.

    Returns (context_string, sources_list).
    """
    q_embedding = await embed_query(question)

    result = await db.execute(
        select(ChunkModel)
        .where(ChunkModel.document_id == document_id)
        .where(ChunkModel.embedding.isnot(None))
        .order_by(ChunkModel.embedding.cosine_distance(q_embedding))
        .limit(top_k)
    )
    chunks = result.scalars().all()

    if not chunks:
        return "", []

    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        page_label = (
            f"Pages {chunk.page_start}-{chunk.page_end}"
            if chunk.page_start
            else "Page unknown"
        )
        heading = " > ".join(chunk.heading_path) if chunk.heading_path else "—"
        context_parts.append(
            f"[Passage {i} | {page_label} | Section: {heading}]\n"
            f"{chunk.text}"
        )

    context = "\n\n---\n\n".join(context_parts)

    sources = [
        {
            "pages": f"{c.page_start or '?'}-{c.page_end or '?'}",
            "section": " > ".join(c.heading_path) if c.heading_path else None,
            "preview": c.text[:250] + ("..." if len(c.text) > 250 else ""),
        }
        for c in chunks
    ]

    return context, sources


async def answer_question(
    db: AsyncSession,
    document_id: UUID,
    question: str,
    top_k: int | None = None,
) -> dict:
    """Non-streaming Q&A. Returns complete answer + sources."""
    k = top_k or settings.qa_top_k
    client = _get_client()

    logger.info("Embedding question: %s", question[:80])
    context, sources = await _retrieve_context(db, document_id, question, k)

    if not context:
        return {
            "answer": "No indexed content found for this document. "
                      "The document may still be processing.",
            "sources": [],
        }

    logger.info("Generating answer (non-streaming)...")
    try:
        response = await client.messages.create(
            model=settings.summary_model,
            max_tokens=1500,
            system=QA_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"Context from the document:\n\n{context}\n\n"
                    f"---\n\n"
                    f"Question: {question}"
                ),
            }],
        )
        answer = response.content[0].text
    except Exception as e:
        logger.error("Q&A generation failed: %s", e)
        answer = f"Sorry, I couldn't generate an answer: {e}"

    return {"answer": answer, "sources": sources}


async def answer_question_stream(
    db: AsyncSession,
    document_id: UUID,
    question: str,
    top_k: int | None = None,
) -> AsyncGenerator[str, None]:
    """Streaming Q&A. Yields Server-Sent Event strings.

    Event types:
      event: delta    — data: {"text": "partial text"}
      event: sources  — data: {"sources": [...]}
      event: error    — data: {"error": "message"}
      event: done     — data: {}
    """
    k = top_k or settings.qa_top_k
    client = _get_client()

    logger.info("Embedding question (streaming): %s", question[:80])
    context, sources = await _retrieve_context(db, document_id, question, k)

    if not context:
        yield f"event: error\ndata: {json.dumps({'error': 'No indexed content found.'})}\n\n"
        yield "event: done\ndata: {}\n\n"
        return

    logger.info("Generating answer (streaming)...")
    try:
        async with client.messages.stream(
            model=settings.summary_model,
            max_tokens=1500,
            system=QA_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"Context from the document:\n\n{context}\n\n"
                    f"---\n\n"
                    f"Question: {question}"
                ),
            }],
        ) as stream:
            async for text in stream.text_stream:
                yield f"event: delta\ndata: {json.dumps({'text': text})}\n\n"

    except Exception as e:
        logger.error("Streaming Q&A failed: %s", e)
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    # Send sources after the full answer has streamed
    yield f"event: sources\ndata: {json.dumps({'sources': sources})}\n\n"
    yield "event: done\ndata: {}\n\n"
