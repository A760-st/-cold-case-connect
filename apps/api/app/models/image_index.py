from datetime import datetime
from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base


class ImageIndexState(Base):
    __tablename__ = "historical_image_index_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_INITIALIZED", server_default="NOT_INITIALIZED")
    collection_name: Mapped[str] = mapped_column(String(240), nullable=False, default="historical_case_images", server_default="historical_case_images")
    embedding_model: Mapped[str] = mapped_column(String(300), nullable=False)
    database_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
