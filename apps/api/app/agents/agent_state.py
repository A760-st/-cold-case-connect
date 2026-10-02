from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class InvestigationAgentState:
    investigation_id: UUID
    objective: str
    evidence_ids: list[UUID] = field(default_factory=list)
    completed_actions: list[str] = field(default_factory=list)
    discovered_sources: list[str] = field(default_factory=list)
    historical_matches: list[dict] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 5
    serpapi_queries_used: int = 0
    max_serpapi_queries: int = 10
    results_collected: int = 0
    max_results: int = 50
    historical_searches_used: int = 0
    max_historical_searches: int = 5
    image_searches_used: int = 0
    max_image_searches: int = 5
    status: str = "QUEUED"
    stop_reason: str | None = None
    research_history: list[dict] = field(default_factory=list)
    investigation: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)
