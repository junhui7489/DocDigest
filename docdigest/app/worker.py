"""Celery worker and background task definitions.

The main task `process_document` runs the full pipeline:
parse → chunk → summarise → embed → store.
"""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import UUID

from celery import Celery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Celery app
# ---------------------------------------------------------------------------

celery_app = Celery(
    "docdigest",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_timeout=5,
    broker_connection_retry=False,
)


# ---------------------------------------------------------------------------
# Helper: run async code from sync Celery task
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine from a sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Main processing task
# ---------------------------------------------------------------------------

@celery_app.task(name="process_document", bind=True, max_retries=2)
def process_document_task(self, document_id: str):
    """Full document processing pipeline.

    Stages:
    1. PARSING — Extract text and structure from the file.
    2. CHUNKING — Split into semantically coherent chunks.
    3. SUMMARISING — Hierarchical map-reduce summarisation.
    4. EMBEDDING — Generate vector embeddings for each chunk.
    5. STORING — Persist chunks, embeddings, and summaries.
    """
    _run_async(_process_document_async(document_id))


async def _process_document_async(document_id: str):
    """Async implementation of the processing pipeline."""
    from app.models.database import async_session
    from app.models.schemas import (
        Chunk as ChunkModel,
        Document,
        ProcessingStatus,
        Summary,
        SummaryLevel,
    )
    from app.services.chunker import chunk_document
    from app.services.embedder import embed_texts
    from app.services.parser import parse_document
    from app.services.summariser import summarise_document

    start_time = time.time()
    doc_uuid = UUID(document_id)

    async with async_session() as db:
        # Fetch document record
        result = await db.execute(
            select(Document).where(Document.id == doc_uuid)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            logger.error("Document %s not found.", document_id)
            return

        try:
            # ---- Stage 1: PARSING ----
            await _update_status(db, doc, ProcessingStatus.PARSING, 0.1)
            logger.info("[%s] Stage 1: Parsing %s", document_id[:8], doc.filename)

            parsed = parse_document(doc.file_path)
            doc.title = parsed.title or doc.filename
            doc.author = parsed.author
            doc.page_count = parsed.page_count
            await db.commit()

            # ---- Stage 2: CHUNKING ----
            await _update_status(db, doc, ProcessingStatus.CHUNKING, 0.2)
            logger.info("[%s] Stage 2: Chunking...", document_id[:8])

            chunks = chunk_document(parsed)
            logger.info("[%s] Produced %d chunks.", document_id[:8], len(chunks))

            # ---- Stage 3: SUMMARISING ----
            await _update_status(db, doc, ProcessingStatus.SUMMARISING, 0.3)
            logger.info("[%s] Stage 3: Summarising...", document_id[:8])

            summary_result = await summarise_document(chunks)
            await _update_status(db, doc, ProcessingStatus.SUMMARISING, 0.7)

            # ---- Stage 4: EMBEDDING ----
            await _update_status(db, doc, ProcessingStatus.EMBEDDING, 0.8)
            logger.info("[%s] Stage 4: Generating embeddings...", document_id[:8])

            texts_to_embed = [c.text for c in chunks]
            embeddings = await embed_texts(texts_to_embed)

            # ---- Stage 5: STORING ----
            logger.info("[%s] Stage 5: Storing results...", document_id[:8])

            # Store chunks with embeddings
            for chunk, embedding in zip(chunks, embeddings):
                db_chunk = ChunkModel(
                    document_id=doc_uuid,
                    index=chunk.index,
                    text=chunk.text,
                    heading_path=chunk.heading_path,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    token_count=chunk.token_count,
                    content_hash=chunk.content_hash,
                    embedding=embedding,
                )
                db.add(db_chunk)

            # Store summaries at each level
            _add_summary(db, doc_uuid, SummaryLevel.BRIEF, summary_result.brief)
            _add_summary(db, doc_uuid, SummaryLevel.TAKEAWAYS, summary_result.takeaways)

            for heading, content in summary_result.chapter_summaries.items():
                _add_summary(
                    db, doc_uuid, SummaryLevel.CHAPTERS, content,
                    section_key=heading,
                )

            for heading, content in summary_result.section_summaries.items():
                _add_summary(
                    db, doc_uuid, SummaryLevel.SECTIONS, content,
                    section_key=heading,
                )

            # Mark complete
            elapsed = time.time() - start_time
            doc.processing_seconds = round(elapsed, 2)
            await _update_status(db, doc, ProcessingStatus.COMPLETED, 1.0)
            await db.commit()

            logger.info(
                "[%s] Processing complete in %.1fs (%d chunks).",
                document_id[:8], elapsed, len(chunks),
            )

        except Exception as e:
            logger.exception("[%s] Processing failed: %s", document_id[:8], e)
            doc.status = ProcessingStatus.FAILED
            doc.error_message = str(e)[:2000]
            await db.commit()
            raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_summary(
    db: AsyncSession,
    document_id: UUID,
    level: str,
    content: str,
    section_key: str | None = None,
):
    """Add a summary record to the session."""
    from app.models.schemas import Summary

    model_used = (
        settings.synthesis_model
        if level in ("brief", "takeaways", "chapters")
        else settings.summary_model
    )

    db.add(Summary(
        document_id=document_id,
        level=level,
        section_key=section_key,
        content=content,
        model_used=model_used,
    ))


async def _update_status(
    db: AsyncSession,
    doc,
    status,
    progress: float,
):
    """Update document processing status."""
    doc.status = status
    doc.progress = progress
    await db.commit()
