import enum
import uuid
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base


class EvidenceType(str, enum.Enum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    DOCUMENT = "DOCUMENT"
    VIDEO_METADATA = "VIDEO_METADATA"
    OTHER = "OTHER"


class ProcessingStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (CheckConstraint("file_size IS NULL OR file_size >= 0", name="ck_evidence_file_size_nonnegative"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    investigation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[EvidenceType] = mapped_column(Enum(EvidenceType, name="evidencetype", native_enum=False, length=32), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    original_filename: Mapped[str | None] = mapped_column(String(255))
    storage_path: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(120))
    file_size: Mapped[int | None] = mapped_column(Integer)
    checksum: Mapped[str | None] = mapped_column(String(64), index=True)
    text_content: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict, server_default="{}")
    clip_embedding: Mapped[list[float] | None] = mapped_column(JSON)
    clip_embedding_model: Mapped[str | None] = mapped_column(String(300))
    clip_embedding_version: Mapped[str | None] = mapped_column(String(64))
    clip_embedding_checksum: Mapped[str | None] = mapped_column(String(64))
    clip_embedding_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_status: Mapped[ProcessingStatus] = mapped_column(Enum(ProcessingStatus, name="processingstatus", native_enum=False, length=32), nullable=False, default=ProcessingStatus.READY, server_default="READY")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
