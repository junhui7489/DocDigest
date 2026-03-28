"""ORM models (SQLAlchemy) and request/response schemas (Pydantic)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from pydantic import BaseModel, Field
from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProcessingStatus(str, enum.Enum):
    PENDING = "pending"
    PARSING = "parsing"
    CHUNKING = "chunking"
    SUMMARISING = "summarising"
    EMBEDDING = "embedding"
    COMPLETED = "completed"
    FAILED = "failed"


class SummaryLevel(str, enum.Enum):
    BRIEF = "brief"
    TAKEAWAYS = "takeaways"
    CHAPTERS = "chapters"
    SECTIONS = "sections"


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class Document(Base):
    """A single uploaded document."""

    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(512), nullable=False)
    file_path = Column(String(1024), nullable=False)
    file_type = Column(String(20), nullable=False)  # pdf, epub, docx, txt
    file_size_bytes = Column(Integer, nullable=False)
    page_count = Column(Integer, nullable=True)
    title = Column(String(1024), nullable=True)
    author = Column(String(512), nullable=True)

    status = Column(
        Enum(ProcessingStatus),
        default=ProcessingStatus.PENDING,
        nullable=False,
    )
    progress = Column(Float, default=0.0)
    error_message = Column(Text, nullable=True)
    processing_seconds = Column(Float, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete")
    summaries = relationship("Summary", back_populates="document", cascade="all, delete")


class Chunk(Base):
    """A semantically coherent text chunk from a document."""

    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    index = Column(Integer, nullable=False)

    text = Column(Text, nullable=False)
    heading_path = Column(JSONB, default=list)  # e.g. ["Ch.3", "Section 3.2"]
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    token_count = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)  # SHA-256 for caching

    embedding = Column(Vector(1024), nullable=True)  # voyage-3 dimensions

    document = relationship("Document", back_populates="chunks")


class Summary(Base):
    """A generated summary at a particular level."""

    __tablename__ = "summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    level = Column(Enum(SummaryLevel), nullable=False)
    section_key = Column(String(256), nullable=True)  # e.g. "chapter_3"
    content = Column(Text, nullable=False)
    model_used = Column(String(128), nullable=False)
    token_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    document = relationship("Document", back_populates="summaries")


# ---------------------------------------------------------------------------
# Pydantic Schemas — Requests
# ---------------------------------------------------------------------------

class QuestionRequest(BaseModel):
    """Request body for the Q&A endpoint."""
    question: str = Field(..., min_length=3, max_length=2000)


# ---------------------------------------------------------------------------
# Pydantic Schemas — Responses
# ---------------------------------------------------------------------------

class DocumentResponse(BaseModel):
    """Response after uploading a document."""
    document_id: str
    filename: str
    status: ProcessingStatus
    message: str


class StatusResponse(BaseModel):
    """Processing status response."""
    document_id: str
    status: ProcessingStatus
    progress: float
    error_message: str | None = None


class SummaryResponse(BaseModel):
    """A summary at a given level."""
    document_id: str
    level: SummaryLevel
    content: str | list[dict]
    metadata: dict


class QAResponse(BaseModel):
    """Response from the Q&A endpoint."""
    answer: str
    sources: list[dict]


class DocumentListItem(BaseModel):
    """A document in the list view."""
    document_id: str
    filename: str
    title: str | None
    status: ProcessingStatus
    page_count: int | None
    created_at: datetime
