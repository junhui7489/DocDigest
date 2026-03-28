"""API routes for document upload, status, summary, Q&A, and management.

Includes SSE streaming endpoints for real-time response delivery.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import time
from uuid import UUID

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import async_session, get_db
from app.models.schemas import (
    Document,
    DocumentListItem,
    DocumentResponse,
    ProcessingStatus,
    QAResponse,
    QuestionRequest,
    StatusResponse,
    Summary,
    SummaryLevel,
    SummaryResponse,
)
from app.services.qa_engine import answer_question, answer_question_stream
from app.services.summariser import stream_summary_text

router = APIRouter()

ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "application/epub+zip": "epub",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
}


async def _run_processing(doc_id: str):
    """Run the document processing pipeline as a background task."""
    from app.worker import _process_document_async
    await _process_document_async(doc_id)


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Upload a document and start async processing."""
    logger.info("Upload started: %s", file.filename)

    # Validate file type
    content_type = file.content_type or ""
    file_type = ALLOWED_TYPES.get(content_type)
    if not file_type:
        ext = (file.filename or "").rsplit(".", 1)[-1].lower()
        file_type = ext if ext in ("pdf", "epub", "docx", "txt") else None
    if not file_type:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {content_type}. "
            f"Supported: PDF, EPUB, DOCX, TXT.",
        )
    logger.info("File type validated: %s", file_type)

    # Save file to disk
    logger.info("Ensuring upload dir...")
    upload_dir = settings.ensure_upload_dir()
    logger.info("Reading file content...")
    content = await file.read()
    logger.info("File read: %d bytes", len(content))
    file_hash = hashlib.sha256(content).hexdigest()[:12]
    safe_name = f"{file_hash}_{file.filename}"
    dest_path = upload_dir / safe_name

    with open(dest_path, "wb") as f:
        f.write(content)
    logger.info("File saved to: %s", dest_path)

    # Create database record
    logger.info("Creating DB record...")
    doc = Document(
        filename=file.filename or "unknown",
        file_path=str(dest_path),
        file_type=file_type,
        file_size_bytes=len(content),
        status=ProcessingStatus.PENDING,
    )
    db.add(doc)
    logger.info("Flushing to DB...")
    await db.flush()
    doc_id = str(doc.id)
    logger.info("DB record created: %s", doc_id)

    # Dispatch background task
    background_tasks.add_task(_run_processing, doc_id)
    logger.info("Background task scheduled.")

    return DocumentResponse(
        document_id=doc_id,
        filename=doc.filename,
        status=ProcessingStatus.PENDING,
        message="Document uploaded. Processing has started.",
    )


@router.get("/{doc_id}/status", response_model=StatusResponse)
async def get_status(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Check the processing status of a document."""
    doc = await _get_document_or_404(db, doc_id)
    return StatusResponse(
        document_id=str(doc.id),
        status=doc.status,
        progress=doc.progress or 0.0,
        error_message=doc.error_message,
    )


@router.get("/{doc_id}/summary", response_model=SummaryResponse)
async def get_summary(
    doc_id: UUID,
    level: SummaryLevel = SummaryLevel.BRIEF,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a summary at the requested level."""
    doc = await _get_document_or_404(db, doc_id)

    if doc.status != ProcessingStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Document is still {doc.status.value}. "
            f"Progress: {doc.progress:.0%}",
        )

    result = await db.execute(
        select(Summary).where(
            Summary.document_id == doc.id,
            Summary.level == level,
        )
    )
    summaries = result.scalars().all()

    if not summaries:
        raise HTTPException(404, f"No {level.value} summary found.")

    # For brief/takeaways return single string; for chapters/sections return list
    if level in (SummaryLevel.BRIEF, SummaryLevel.TAKEAWAYS):
        content = summaries[0].content
    else:
        content = [
            {"section": s.section_key, "content": s.content}
            for s in sorted(summaries, key=lambda s: s.section_key or "")
        ]

    return SummaryResponse(
        document_id=str(doc.id),
        level=level,
        content=content,
        metadata={
            "title": doc.title,
            "author": doc.author,
            "pages": doc.page_count,
            "processing_time_seconds": doc.processing_seconds,
        },
    )


@router.post("/{doc_id}/ask", response_model=QAResponse)
async def ask(
    doc_id: UUID,
    body: QuestionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Ask a follow-up question about the document (RAG)."""
    doc = await _get_document_or_404(db, doc_id)

    if doc.status != ProcessingStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail="Document processing is not yet complete.",
        )

    result = await answer_question(
        db=db,
        document_id=doc.id,
        question=body.question,
        top_k=settings.qa_top_k,
    )

    return QAResponse(answer=result["answer"], sources=result["sources"])


# ---------------------------------------------------------------------------
# Streaming endpoints (Server-Sent Events)
# ---------------------------------------------------------------------------

@router.post("/{doc_id}/ask/stream")
async def ask_stream(
    doc_id: UUID,
    body: QuestionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Stream a Q&A answer token-by-token via Server-Sent Events.

    SSE event types:
      event: delta    → {"text": "partial"}  (each token/chunk)
      event: sources  → {"sources": [...]}    (after answer completes)
      event: error    → {"error": "msg"}      (on failure)
      event: done     → {}                    (stream finished)
    """
    doc = await _get_document_or_404(db, doc_id)

    if doc.status != ProcessingStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail="Document processing is not yet complete.",
        )

    return StreamingResponse(
        answer_question_stream(
            db=db,
            document_id=doc.id,
            question=body.question,
            top_k=settings.qa_top_k,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/{doc_id}/summary/stream")
async def get_summary_stream(
    doc_id: UUID,
    level: SummaryLevel = SummaryLevel.BRIEF,
    db: AsyncSession = Depends(get_db),
):
    """Stream a pre-computed summary with a typing effect via SSE.

    This streams the already-generated summary text in small chunks
    for a real-time reading experience. No additional API calls are made.

    SSE event types:
      event: meta     → {"level": "brief"}
      event: delta    → {"text": "partial"}
      event: done     → {}
    """
    doc = await _get_document_or_404(db, doc_id)

    if doc.status != ProcessingStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Document is still {doc.status.value}.",
        )

    result = await db.execute(
        select(Summary).where(
            Summary.document_id == doc.id,
            Summary.level == level,
        )
    )
    summaries = result.scalars().all()

    if not summaries:
        raise HTTPException(404, f"No {level.value} summary found.")

    # For brief/takeaways, stream the single text
    if level in (SummaryLevel.BRIEF, SummaryLevel.TAKEAWAYS):
        text = summaries[0].content
    else:
        # For chapters, concatenate with headers
        parts = []
        for s in sorted(summaries, key=lambda s: s.section_key or ""):
            if s.section_key:
                parts.append(f"\n## {s.section_key}\n\n")
            parts.append(s.content + "\n\n")
        text = "".join(parts)

    return StreamingResponse(
        stream_summary_text(text, level=level.value),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{doc_id}/export")
async def export_summary(
    doc_id: UUID,
    level: SummaryLevel = SummaryLevel.BRIEF,
    db: AsyncSession = Depends(get_db),
):
    """Export a summary as Markdown."""
    doc = await _get_document_or_404(db, doc_id)

    result = await db.execute(
        select(Summary).where(
            Summary.document_id == doc.id,
            Summary.level == level,
        )
    )
    summaries = result.scalars().all()
    if not summaries:
        raise HTTPException(404, "No summary found at this level.")

    title = doc.title or doc.filename
    lines = [f"# {title}\n", f"*Summary level: {level.value}*\n"]

    for s in sorted(summaries, key=lambda s: s.section_key or ""):
        if s.section_key:
            lines.append(f"\n## {s.section_key}\n")
        lines.append(s.content + "\n")

    return {"markdown": "\n".join(lines)}


@router.get("", response_model=list[DocumentListItem])
async def list_documents(
    db: AsyncSession = Depends(get_db),
):
    """List all uploaded documents."""
    result = await db.execute(
        select(Document).order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    return [
        DocumentListItem(
            document_id=str(d.id),
            filename=d.filename,
            title=d.title,
            status=d.status,
            page_count=d.page_count,
            created_at=d.created_at,
        )
        for d in docs
    ]


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a document and all associated data."""
    doc = await _get_document_or_404(db, doc_id)

    # Remove file from disk
    import os
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)

    await db.delete(doc)
    return {"deleted": True, "document_id": str(doc.id)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_document_or_404(db: AsyncSession, doc_id: UUID) -> Document:
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc
