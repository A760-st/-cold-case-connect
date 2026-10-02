import enum
import uuid
from datetime import datetime
from sqlalchemy import DateTime, Enum, Float, ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base


class CorrelationObjectType(str, enum.Enum):
    EVIDENCE = "EVIDENCE"
    HISTORICAL_CASE = "HISTORICAL_CASE"
    HISTORICAL_IMAGE = "HISTORICAL_IMAGE"
    WEB_RESULT = "WEB_RESULT"
    NEWS_RESULT = "NEWS_RESULT"
    IMAGE_RESULT = "IMAGE_RESULT"
    SOURCE = "SOURCE"


class CorrelationType(str, enum.Enum):
    POTENTIAL_CONNECTION = "POTENTIAL_CONNECTION"
    SHARED_ATTRIBUTE = "SHARED_ATTRIBUTE"
    SEMANTIC_SIMILARITY = "SEMANTIC_SIMILARITY"
    VISUAL_SIMILARITY = "VISUAL_SIMILARITY"
    GEOGRAPHIC_OVERLAP = "GEOGRAPHIC_OVERLAP"
    TEMPORAL_OVERLAP = "TEMPORAL_OVERLAP"
    TEMPORAL_PROXIMITY = "TEMPORAL_PROXIMITY"
    ENTITY_OVERLAP = "ENTITY_OVERLAP"
    SOURCE_REFERENCE = "SOURCE_REFERENCE"
    CONTEXTUAL_RELEVANCE = "CONTEXTUAL_RELEVANCE"


class CorrelationCreatedBy(str, enum.Enum):
    AI = "AI"
    INVESTIGATOR = "INVESTIGATOR"


class CorrelationReviewStatus(str, enum.Enum):
    RELEVANT = "RELEVANT"
    NOT_RELEVANT = "NOT_RELEVANT"
    REQUIRES_VERIFICATION = "REQUIRES_VERIFICATION"


class Correlation(Base):
    __tablename__ = "correlations"
    __table_args__ = (UniqueConstraint("investigation_id", "source_type", "source_id", "target_type", "target_id", "correlation_type", name="uq_correlation_pair_type"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    investigation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type: Mapped[CorrelationObjectType] = mapped_column(Enum(CorrelationObjectType, native_enum=False, length=32), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_type: Mapped[CorrelationObjectType] = mapped_column(Enum(CorrelationObjectType, native_enum=False, length=32), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    correlation_type: Mapped[CorrelationType] = mapped_column(Enum(CorrelationType, native_enum=False, length=40), nullable=False, index=True)
    score: Mapped[float | None] = mapped_column(Float)
    confidence_label: Mapped[str | None] = mapped_column(String(16))
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_attributes: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    evidence_basis: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    created_by: Mapped[CorrelationCreatedBy] = mapped_column(Enum(CorrelationCreatedBy, native_enum=False, length=16), nullable=False, default=CorrelationCreatedBy.AI)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CorrelationReview(Base):
    __tablename__ = "correlation_reviews"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("correlations.id", ondelete="CASCADE"), nullable=False, index=True)
    review_status: Mapped[CorrelationReviewStatus] = mapped_column(Enum(CorrelationReviewStatus, native_enum=False, length=32), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
