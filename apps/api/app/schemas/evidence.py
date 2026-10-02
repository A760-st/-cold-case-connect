from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.models.evidence import EvidenceType, ProcessingStatus


class TextEvidenceCreate(BaseModel):
    type: EvidenceType = EvidenceType.TEXT
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=10000)
    text_content: str | None = Field(default=None, max_length=200000)
    metadata: dict = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value

    @field_validator("text_content")
    @classmethod
    def non_blank_text(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("Text content cannot be blank")
        return value

    @field_validator("type")
    @classmethod
    def manual_type_only(cls, value: EvidenceType) -> EvidenceType:
        if value not in {EvidenceType.TEXT, EvidenceType.VIDEO_METADATA, EvidenceType.OTHER}:
            raise ValueError("Image and document evidence must be uploaded as files")
        return value


class EvidenceUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10000)
    metadata: dict | None = None

    @field_validator("title")
    @classmethod
    def non_blank_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Title cannot be blank")
        return value


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: UUID
    investigation_id: UUID
    type: EvidenceType
    title: str
    description: str
    original_filename: str | None
    mime_type: str | None
    file_size: int | None
    checksum: str | None
    text_content: str | None
    metadata: dict = Field(validation_alias="metadata_json")
    processing_status: ProcessingStatus
    created_at: datetime
    updated_at: datetime
