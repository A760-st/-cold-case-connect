import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class InvestigationSynthesisStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    BUILDING_CONTEXT = "BUILDING_CONTEXT"
    GENERATING = "GENERATING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class InvestigationSynthesisReviewStatus(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
    DISMISSED = "DISMISSED"


class InvestigationSynthesis(Base):
    __tablename__ = "investigation_syntheses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    investigation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=InvestigationSynthesisStatus.QUEUED.value, server_default=InvestigationSynthesisStatus.QUEUED.value)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False, default="mock-model")
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False, default="phase12-v1")
    context_hash: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    synthesis_json: Mapped[dict] = mapped_column("synthesis_json", JSON, nullable=False, default=dict, server_default="{}")
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    claim_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    contradiction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    research_gap_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    token_usage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class InvestigationSynthesisReview(Base):
    __tablename__ = "investigation_synthesis_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    synthesis_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("investigation_syntheses.id", ondelete="CASCADE"), nullable=False, index=True)
    investigation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    section: Mapped[str] = mapped_column(String(120), nullable=False)
    item_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default=InvestigationSynthesisReviewStatus.NEEDS_VERIFICATION.value)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
