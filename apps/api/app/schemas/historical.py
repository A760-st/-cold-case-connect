from datetime import date
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, model_validator


class HistoricalSearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=50000)
    top_k: int = Field(default=10, ge=1, le=20)
    location: str | None = Field(default=None, max_length=500)
    case_type: str | None = Field(default=None, max_length=160)
    status: str | None = Field(default=None, max_length=120)
    date_from: date | None = None
    date_to: date | None = None

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Query must contain at least three characters")
        return value

    @model_validator(mode="after")
    def valid_date_range(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self


class InvestigationHistoricalSearchRequest(BaseModel):
    evidence_ids: list[UUID] = Field(min_length=1, max_length=20)
    top_k: int = Field(default=10, ge=1, le=20)


class InvestigationHistoricalImageSearchRequest(BaseModel):
    evidence_id: UUID
    top_k: int = Field(default=10, ge=1, le=20)


class HistoricalCaseRead(BaseModel):
    id: UUID
    external_id: str | None
    title: str
    summary: str | None
    description: str | None
    date: date | None
    location: str | None
    case_type: str | None
    status: str | None
    source_name: str | None
    source_url: str | None
