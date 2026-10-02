import enum
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base


class AgentRunStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class AgentActionStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class AgentActionType(str, enum.Enum):
    GET_INVESTIGATION = "GET_INVESTIGATION"
    GET_EVIDENCE = "GET_EVIDENCE"
    GET_RESEARCH_HISTORY = "GET_RESEARCH_HISTORY"
    SEARCH_HISTORICAL_TEXT = "SEARCH_HISTORICAL_TEXT"
    SEARCH_HISTORICAL_IMAGES = "SEARCH_HISTORICAL_IMAGES"
    SEARCH_WEB = "SEARCH_WEB"
    SEARCH_NEWS = "SEARCH_NEWS"
    SEARCH_IMAGES = "SEARCH_IMAGES"
    STOP = "STOP"


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    investigation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    objective: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[AgentRunStatus] = mapped_column(Enum(AgentRunStatus, native_enum=False, length=32), nullable=False, default=AgentRunStatus.QUEUED, index=True)
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    max_actions: Mapped[int] = mapped_column(Integer, nullable=False)
    max_serpapi_queries: Mapped[int] = mapped_column(Integer, nullable=False)
    actions_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    queries_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    results_collected: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    stop_reason: Mapped[str | None] = mapped_column(String(80))
    stop_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict, server_default="{}")


class AgentAction(Base):
    __tablename__ = "agent_actions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    investigation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    research_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("research_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[AgentActionType] = mapped_column(Enum(AgentActionType, native_enum=False, length=40), nullable=False)
    status: Mapped[AgentActionStatus] = mapped_column(Enum(AgentActionStatus, native_enum=False, length=32), nullable=False, default=AgentActionStatus.PENDING)
    input_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    output_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
