import enum
import uuid
from datetime import datetime
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base


class ResearchStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ResearchTrigger(str, enum.Enum):
    MANUAL = "MANUAL"
    EVIDENCE_RESEARCH = "EVIDENCE_RESEARCH"


class SearchType(str, enum.Enum):
    WEB = "WEB"
    NEWS = "NEWS"
    NEWS_TAB = "NEWS_TAB"
    IMAGE = "IMAGE"


class ResultType(str, enum.Enum):
    WEB = "WEB"
    NEWS = "NEWS"
    IMAGE = "IMAGE"


class ResearchRun(Base):
    __tablename__ = "research_runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    investigation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    objective: Mapped[str] = mapped_column(String(500), nullable=False)
    trigger: Mapped[ResearchTrigger] = mapped_column(Enum(ResearchTrigger, native_enum=False, length=32), nullable=False)
    status: Mapped[ResearchStatus] = mapped_column(Enum(ResearchStatus, native_enum=False, length=32), nullable=False, default=ResearchStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict, server_default="{}")


class ResearchSearch(Base):
    __tablename__ = "research_searches"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    investigation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    research_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    engine: Mapped[str] = mapped_column(String(64), nullable=False)
    search_type: Mapped[SearchType] = mapped_column(Enum(SearchType, native_enum=False, length=32), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    serpapi_search_id: Mapped[str | None] = mapped_column(String(120))
    serpapi_status: Mapped[str | None] = mapped_column(String(80))
    search_timestamp: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[ResearchStatus] = mapped_column(Enum(ResearchStatus, native_enum=False, length=32), nullable=False, default=ResearchStatus.PENDING)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebSource(Base):
    __tablename__ = "web_sources"
    __table_args__ = (UniqueConstraint("investigation_id", "canonical_url", name="uq_web_sources_investigation_canonical_url"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    investigation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(500))
    title: Mapped[str | None] = mapped_column(String(1000))
    source_name: Mapped[str | None] = mapped_column(String(500))
    source_type: Mapped[ResultType] = mapped_column(Enum(ResultType, native_enum=False, length=16), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict, server_default="{}")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WebSearchResult(Base):
    __tablename__ = "web_search_results"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    investigation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    research_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    search_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("research_searches.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("web_sources.id", ondelete="SET NULL"), index=True)
    result_type: Mapped[ResultType] = mapped_column(Enum(ResultType, native_enum=False, length=16), nullable=False)
    title: Mapped[str | None] = mapped_column(String(1000))
    url: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(String(500))
    displayed_url: Mapped[str | None] = mapped_column(String(1000))
    published_at: Mapped[str | None] = mapped_column(String(120))
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ResearchRunEvidence(Base):
    __tablename__ = "research_run_evidence"
    research_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("research_runs.id", ondelete="CASCADE"), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True)
