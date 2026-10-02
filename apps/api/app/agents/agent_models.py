from enum import Enum
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, model_validator
from app.config import settings


class ActionType(str, Enum):
    GET_INVESTIGATION = "GET_INVESTIGATION"
    GET_EVIDENCE = "GET_EVIDENCE"
    GET_RESEARCH_HISTORY = "GET_RESEARCH_HISTORY"
    SEARCH_HISTORICAL_TEXT = "SEARCH_HISTORICAL_TEXT"
    SEARCH_HISTORICAL_IMAGES = "SEARCH_HISTORICAL_IMAGES"
    SEARCH_WEB = "SEARCH_WEB"
    SEARCH_NEWS = "SEARCH_NEWS"
    SEARCH_IMAGES = "SEARCH_IMAGES"
    STOP = "STOP"


class AgentActionSpec(BaseModel):
    action: ActionType
    query: str | None = Field(default=None, max_length=2000)
    reason: str = Field(default="", max_length=500)
    priority: int = Field(default=3, ge=1, le=5)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value):
        if value is None:
            return None
        clean = " ".join(value.split())
        if not clean or len(clean) > settings.max_search_query_length:
            raise ValueError(f"query must contain 1 to {settings.max_search_query_length} characters")
        return clean

    @field_validator("reason")
    @classmethod
    def safe_reason(cls, value):
        return " ".join(value.split())[:500]

    @model_validator(mode="after")
    def require_query_for_search(self):
        search_actions = {ActionType.SEARCH_WEB, ActionType.SEARCH_NEWS, ActionType.SEARCH_IMAGES}
        if self.action in search_actions and not self.query:
            raise ValueError("public search actions require a non-empty query")
        if self.action not in search_actions and self.query is not None:
            raise ValueError("query is only supported for public search actions")
        return self


class AgentRunRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=1000)
    max_iterations: int | None = Field(default=None, ge=1)
    max_serpapi_queries: int | None = Field(default=None, ge=0)

    @field_validator("objective")
    @classmethod
    def normalize_objective(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("objective cannot be blank")
        return value
