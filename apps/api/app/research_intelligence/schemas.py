from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator
from app.models.research_intelligence import ResearchGapStatus, InvestigationQuestionStatus

Priority = Literal["HIGH", "MEDIUM", "LOW"]

class GapReview(BaseModel):
    status: ResearchGapStatus | None = None
    priority: Priority | None = None
    investigator_note: str | None = Field(default=None, max_length=5000)

class QuestionCreate(BaseModel):
    question: str = Field(min_length=5, max_length=1000)
    priority: Priority = "MEDIUM"
    related_evidence_ids: list[UUID] = Field(default_factory=list, max_length=100)
    related_timeline_event_ids: list[UUID] = Field(default_factory=list, max_length=100)
    related_location_ids: list[UUID] = Field(default_factory=list, max_length=100)
    related_source_ids: list[UUID] = Field(default_factory=list, max_length=100)
    related_gap_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @field_validator("question")
    @classmethod
    def clean_question(cls, value):
        value = " ".join(value.split())
        if len(value) < 5:
            raise ValueError("question must contain at least five characters")
        return value

class QuestionUpdate(BaseModel):
    question: str | None = Field(default=None, min_length=5, max_length=1000)
    status: InvestigationQuestionStatus | None = None
    priority: Priority | None = None
    related_gap_ids: list[UUID] | None = Field(default=None, max_length=100)

    @field_validator("question")
    @classmethod
    def clean_question(cls, value):
        return " ".join(value.split()) if value is not None else value
