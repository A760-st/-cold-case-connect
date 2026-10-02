from enum import Enum
from uuid import UUID
from pydantic import BaseModel, Field, field_validator
from app.models.correlation import CorrelationObjectType, CorrelationType, CorrelationReviewStatus


class CorrelationScope(str, Enum):
    ALL = "ALL"
    EVIDENCE = "EVIDENCE"
    HISTORICAL = "HISTORICAL"
    WEB = "WEB"
    NEWS = "NEWS"
    IMAGES = "IMAGES"


class CorrelationRunRequest(BaseModel):
    scope: CorrelationScope = CorrelationScope.ALL


class ManualCorrelationRequest(BaseModel):
    source_type: CorrelationObjectType
    source_id: UUID
    target_type: CorrelationObjectType
    target_id: UUID
    correlation_type: CorrelationType = CorrelationType.POTENTIAL_CONNECTION
    note: str = Field(min_length=1, max_length=1000)

    @field_validator("note")
    @classmethod
    def note_not_blank(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("note cannot be blank")
        return value


class CorrelationReviewRequest(BaseModel):
    review_status: CorrelationReviewStatus
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value):
        return " ".join(value.split()) if value is not None else None
