import uuid
from datetime import date, datetime
from sqlalchemy import Date, DateTime, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base


class HistoricalCase(Base):
    __tablename__ = "historical_cases"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_historical_cases_fingerprint"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    external_id: Mapped[str | None] = mapped_column(String(240), unique=True, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    case_date: Mapped[date | None] = mapped_column("date", Date)
    location: Mapped[str | None] = mapped_column(String(500))
    case_type: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str | None] = mapped_column(String(120))
    source_name: Mapped[str | None] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict, server_default="{}")
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_model: Mapped[str | None] = mapped_column(String(300))
    embedding_version: Mapped[str | None] = mapped_column(String(64))
    embedding_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
