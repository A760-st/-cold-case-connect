from pydantic import BaseModel, ConfigDict, Field


class KeyFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str
    category: str
    status: str
    supporting_refs: list[str] = Field(default_factory=list)
    source_type: str = "EVIDENCE"


class InvestigationSynthesisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    executive_summary: str
    investigation_scope: dict
    key_facts: list[KeyFact] = Field(default_factory=list)
    evidence_overview: dict
    historical_context: dict
    timeline_summary: dict
    geographic_summary: dict
    source_summary: dict
    potential_connections: list[dict] = Field(default_factory=list)
    contradictions: list[dict] = Field(default_factory=list)
    research_gaps: list[dict] = Field(default_factory=list)
    unanswered_questions: list[dict] = Field(default_factory=list)
    research_activity: dict
    limitations: list[str] = Field(default_factory=list)
    provenance: dict
