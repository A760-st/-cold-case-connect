import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base


class HistoricalCaseImage(Base):
    __tablename__ = "historical_case_images"
    __table_args__ = (UniqueConstraint("historical_case_id", "checksum", name="uq_historical_case_image_checksum"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    historical_case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("historical_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    image_url: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(120))
    checksum: Mapped[str | None] = mapped_column(String(64), index=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict, server_default="{}")
    embedding_model: Mapped[str | None] = mapped_column(String(300))
    embedding_version: Mapped[str | None] = mapped_column(String(64))
    embedding_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
